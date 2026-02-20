"""VQS prediction accuracy metrics.

Metric 1 – Bulletin-by-bulletin: For each bulletin, pretend knowledge date is
just before publication; predict every cutoff in that bulletin; compute error
vs actual; aggregate by bulletin (and optionally by visa_class, country).

Metric 2 – Long-term "final ready date": For each month M and each (visa_class,
country, action_type), with data as of M predict when the next cutoff will
appear. Compare to first bulletin where that cutoff was reached. If predicted
date is past but cutoff not yet seen, estimate error >= 1.5 * (last_bulletin - pred).
"""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from lib.business.vqs.solver import (
    predict_next_bulletin_and_maturity,
)

logger = logging.getLogger(__name__)

# Only evaluate these visa classes -- the solver produces meaningful predictions
# for standard EB categories. Obscure sub-classes ("Certain Religious Workers",
# "Schedule A Workers", etc.) add noise without value.
EVALUABLE_VISA_CLASSES = {"1st", "2nd", "3rd", "4th", "5th"}

# Queue-driven classes (exclude EB4 which is policy-driven)
QUEUE_DRIVEN_CLASSES = {"1st", "2nd", "3rd", "5th"}


@dataclass
class BulletinAccuracyRow:
    """One prediction vs actual for a single cutoff in a bulletin."""

    bulletin_date: date
    visa_class: str
    country: int
    action_type: str
    predicted_cutoff: date | None
    actual_cutoff: date
    error_days: int | None  # None if no prediction or C/U
    confidence_low: date | None = None
    confidence_high: date | None = None


def _horizon_months(knowledge_month: date, ready_month: date | None) -> int | None:
    """Months from knowledge_month to ready_month (predicted horizon)."""
    if ready_month is None:
        return None
    return (ready_month.year - knowledge_month.year) * 12 + (
        ready_month.month - knowledge_month.month
    )


def _horizon_bucket(horizon_months: int | None) -> str | None:
    """Bucket: 1-3, 3-6, 6-12, 12+."""
    if horizon_months is None:
        return None
    if horizon_months <= 3:
        return "1-3"
    if horizon_months <= 6:
        return "3-6"
    if horizon_months <= 12:
        return "6-12"
    return "12+"


@dataclass
class LongtermAccuracyRow:
    """One long-term prediction: predicted vs actual "ready" month."""

    knowledge_month: date  # first day of month
    visa_class: str
    country: int
    action_type: str
    predicted_ready_month: date | None
    predicted_cutoff: date | None
    actual_ready_month: date | None  # first bulletin month where cutoff reached
    error_days: int | None  # None if excluded (still unknown)
    error_note: str | None  # e.g. "no_prediction", "pred_past_not_seen", "ok"
    horizon_months: int | None = (
        None  # predicted horizon (knowledge -> predicted_ready)
    )
    horizon_bucket: str | None = None  # "1-3", "3-6", "6-12", "12+"


def _last_day_of_month(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _serialize_date(d):
    """JSON serializer helper for date objects."""
    if isinstance(d, date):
        return d.isoformat()
    return d


def _save_checkpoint(path: Path, rows: list, completed_keys: set) -> None:
    """Save checkpoint: list of serialized rows + set of completed keys."""
    data = {
        "completed_keys": sorted(str(k) for k in completed_keys),
        "rows": [{k: _serialize_date(v) for k, v in asdict(r).items()} for r in rows],
    }
    # Write atomically via temp file
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.rename(path)


def _load_checkpoint(path: Path) -> tuple[list[dict], set[str]] | None:
    """Load checkpoint if it exists. Returns (raw_row_dicts, completed_keys_set)."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data["rows"], set(data["completed_keys"])
    except Exception as e:
        logger.warning("Could not load checkpoint %s: %s", path, e)
        return None


def compute_bulletin_accuracy(
    bulletins=None,
    visa_category: str = "employment_based",
    monthly_supply: int | None = None,
    checkpoint_dir: Path | None = None,
    meta: "VqsMetaParams | None" = None,
    aggregator: "ExpertAggregator | None" = None,
    facts: list | None = None,
    exclude_eb4: bool = False,
    action_type: str | None = None,
    horizon: int = 1,
) -> list[BulletinAccuracyRow]:
    """
    Compute accuracy metrics for a set of bulletins.

    If bulletins is None, uses all available bulletins + 3 future months (hypothetical).
    If monthly_supply is provided, uses that constant supply.
    If checkpoint_dir is provided, loads/saves results there to resume.
    If aggregator is provided, uses it for predictions.
    If facts provided, uses them instead of querying (must be sorted by publication_date).
    If exclude_eb4 is True, skips EB4 series (policy-driven).
    If action_type is provided, only evaluates that action type ("final_action" or "filing_date").
    """
    from lib.business.vqs.data_cache import (
        get_all_bulletins,
        get_cutoff_at_date,
    )
    from lib.business.vqs.solver import predict_next_bulletin_and_maturity
    from models.raw_facts import RawFactsLedger
    from models.visa_cutoff_date import VisaCutoffDate

    if bulletins is None:
        bulletins = [b.publication_date for b in get_all_bulletins()]
    else:
        bulletins = list(bulletins)

    total = len(bulletins)
    logger.info("Bulletin accuracy: %d bulletins to process", total)

    # Load checkpoint
    ckpt_path = (
        (checkpoint_dir / "bulletin_accuracy_ckpt.json") if checkpoint_dir else None
    )
    completed_dates: set[str] = set()
    rows: list[BulletinAccuracyRow] = []
    if ckpt_path:
        loaded = _load_checkpoint(ckpt_path)
        if loaded:
            raw_rows, completed_dates = loaded
            for rd in raw_rows:
                rows.append(
                    BulletinAccuracyRow(
                        bulletin_date=date.fromisoformat(rd["bulletin_date"]),
                        visa_class=rd["visa_class"],
                        country=rd["country"],
                        action_type=rd["action_type"],
                        predicted_cutoff=date.fromisoformat(rd["predicted_cutoff"])
                        if rd["predicted_cutoff"]
                        else None,
                        actual_cutoff=date.fromisoformat(rd["actual_cutoff"]),
                        error_days=rd["error_days"],
                        confidence_low=date.fromisoformat(rd["confidence_low"])
                        if rd.get("confidence_low")
                        else None,
                        confidence_high=date.fromisoformat(rd["confidence_high"])
                        if rd.get("confidence_high")
                        else None,
                    )
                )
            logger.info(
                "Resumed from checkpoint: %d bulletins already done, %d rows loaded",
                len(completed_dates),
                len(rows),
            )

    start_time = time.time()
    processed = 0
    skipped = 0

    # Pre-calculate facts length if provided
    n_facts = len(facts) if facts is not None else 0
    fact_idx = 0

    target_classes = QUEUE_DRIVEN_CLASSES if exclude_eb4 else EVALUABLE_VISA_CLASSES

    for i, pub_date in enumerate(bulletins):
        t = pub_date if isinstance(pub_date, date) else pub_date
        date_key = t.isoformat()
        if date_key in completed_dates:
            skipped += 1
            continue

        knowledge_date = t - timedelta(days=1)

        # Slice facts for this knowledge_date
        # Assumes 'bulletins' iteration is chronological and 'facts' is sorted by date
        current_facts = None
        if facts is not None:
            while (
                fact_idx < n_facts
                and facts[fact_idx].publication_date <= knowledge_date
            ):
                fact_idx += 1
            current_facts = facts[:fact_idx]
        else:
            current_facts = list(
                RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
            )
        cutoffs = VisaCutoffDate.objects.filter(
            bulletin__publication_date=t,
            visa_category=visa_category,
            visa_class__in=target_classes,
        ).exclude(cutoff_date__isnull=True)

        # Filter by action_type if specified
        if action_type:
            cutoffs = cutoffs.filter(action_type=action_type)

        for row in cutoffs:
            next_cutoff, metadata, solver_results, _ = (
                predict_next_bulletin_and_maturity(
                    knowledge_date=knowledge_date,
                    visa_class=row.visa_class,
                    country=row.country,
                    action_type=row.action_type,
                    monthly_supply=monthly_supply,
                    facts=current_facts,
                    meta=meta,
                    aggregator=aggregator,
                )
            )
            # Use next_cutoff (horizon 1) or specific maturity result
            if horizon == 1:
                pred_cutoff = next_cutoff
            else:
                # results is list of SolverResult (month, cutoff_date)
                # index horizon-1 is the requested horizon
                idx = horizon - 1
                if idx < len(solver_results):
                    pred_cutoff = solver_results[idx].cutoff_date
                else:
                    pred_cutoff = None

            # Actual cutoff lookup at horizon
            if horizon == 1:
                actual = row.cutoff_date
            else:
                actual = None
                # Estimate future bulletin date (approx pub_date + horizon months)
                future_pub_est = t + timedelta(days=31 * (horizon - 1))
                # Find the actual cutoff at this future date
                from lib.business.vqs.data_cache import get_cutoff_at_date

                actual = get_cutoff_at_date(
                    visa_class=row.visa_class,
                    country=row.country,
                    action_type=row.action_type,
                    as_of=future_pub_est,
                )

            error_days = None
            if pred_cutoff is not None and actual is not None:
                error_days = abs((pred_cutoff - actual).days)

            # Online Learning Update
            if aggregator and actual is not None:
                aggregator.update(
                    row.visa_class,
                    row.country,
                    knowledge_date,
                    actual,
                    action_type=row.action_type,
                )

            # Extract confidence intervals from metadata if available
            conf_low = None
            conf_high = None
            if isinstance(metadata, dict):
                conf_low = metadata.get("confidence_low")
                conf_high = metadata.get("confidence_high")

            rows.append(
                BulletinAccuracyRow(
                    bulletin_date=t,
                    visa_class=row.visa_class,
                    country=row.country,
                    action_type=row.action_type,
                    predicted_cutoff=pred_cutoff,
                    actual_cutoff=actual,
                    error_days=error_days,
                    confidence_low=conf_low,
                    confidence_high=conf_high,
                )
            )
        completed_dates.add(date_key)
        processed += 1

        # Progress logging every 10 bulletins or at end
        if processed % 10 == 0 or (i + 1) == total:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = total - skipped - processed
            eta_sec = remaining / rate if rate > 0 else 0
            logger.info(
                "[Bulletin] %d/%d done (skipped %d) | %.1f bull/sec | ETA %.0fs | %d rows so far",
                skipped + processed,
                total,
                skipped,
                rate,
                eta_sec,
                len(rows),
            )
            # Save checkpoint
            if ckpt_path:
                _save_checkpoint(ckpt_path, rows, completed_dates)

    # Final checkpoint
    if ckpt_path and processed > 0:
        _save_checkpoint(ckpt_path, rows, completed_dates)
        logger.info(
            "Bulletin checkpoint saved: %d bulletins, %d rows",
            len(completed_dates),
            len(rows),
        )

    return rows


def compute_longterm_accuracy(
    months: list[date] | None = None,
    visa_category: str = "employment_based",
    action_type: str = "final_action",
    monthly_supply: int | None = None,
    today: date | None = None,
    checkpoint_dir: Path | None = None,
    force_recompute: bool = False,
) -> list[LongtermAccuracyRow]:
    """
    For each month M and each (visa_class, country), with data as of end of M,
    predict the "ready" month (when next cutoff will appear). Compare to first
    bulletin where that cutoff was actually reached.

    - If actual is in the past: error = |actual_ready_month - predicted_ready_month|.
    - If predicted ready is in the past but we haven't seen that cutoff yet:
      error_estimate >= 1.5 * (last_bulletin_date - predicted_ready_month).
    - If actual is still unknown (future): exclude from metric (error_days=None).
    """
    from models.bulletin import Bulletin
    from models.raw_facts import RawFactsLedger
    from models.visa_cutoff_date import VisaCutoffDate

    if today is None:
        today = date.today()
    if months is None:
        bulletins = list(
            Bulletin.objects.order_by("publication_date").values_list(
                "publication_date", flat=True
            )
        )
        if not bulletins:
            return []
        months = list(bulletins)
    last_bulletin_date = (
        Bulletin.objects.order_by("-publication_date")
        .values_list("publication_date", flat=True)
        .first()
    )
    if not last_bulletin_date:
        return []

    # Clear default ordering to avoid including bulletin FK in DISTINCT
    distinct_series = list(
        VisaCutoffDate.objects.filter(
            visa_category=visa_category,
            visa_class__in=EVALUABLE_VISA_CLASSES,
        )
        .values_list("visa_class", "country")
        .order_by("visa_class", "country")
        .distinct()
    )

    total_months = len(months)
    total_iterations = total_months * len(distinct_series)
    logger.info(
        "Long-term accuracy: %d months x %d series = %d iterations",
        total_months,
        len(distinct_series),
        total_iterations,
    )

    # Load checkpoint
    ckpt_path = (
        (checkpoint_dir / "longterm_accuracy_ckpt.json") if checkpoint_dir else None
    )
    completed_months: set[str] = set()
    out: list[LongtermAccuracyRow] = []

    if ckpt_path and not force_recompute:
        loaded = _load_checkpoint(ckpt_path)
        if loaded:
            raw_rows, completed_months = loaded
            for rd in raw_rows:
                out.append(
                    LongtermAccuracyRow(
                        knowledge_month=date.fromisoformat(rd["knowledge_month"]),
                        visa_class=rd["visa_class"],
                        country=rd["country"],
                        action_type=rd["action_type"],
                        predicted_ready_month=date.fromisoformat(
                            rd["predicted_ready_month"]
                        )
                        if rd.get("predicted_ready_month")
                        else None,
                        predicted_cutoff=date.fromisoformat(rd["predicted_cutoff"])
                        if rd.get("predicted_cutoff")
                        else None,
                        actual_ready_month=date.fromisoformat(rd["actual_ready_month"])
                        if rd.get("actual_ready_month")
                        else None,
                        error_days=rd.get("error_days"),
                        error_note=rd.get("error_note"),
                        horizon_months=rd.get("horizon_months"),
                        horizon_bucket=rd.get("horizon_bucket"),
                    )
                )
            logger.info(
                "Resumed from checkpoint: %d months already done, %d rows loaded",
                len(completed_months),
                len(out),
            )

    start_time = time.time()
    processed = 0
    skipped = 0
    for i, m in enumerate(months):
        if isinstance(m, date):
            month_first = date(m.year, m.month, 1) if (m.day != 1) else m
        else:
            month_first = m

        month_key = month_first.isoformat()
        if month_key in completed_months:
            skipped += 1
            continue

        knowledge_date = _last_day_of_month(month_first)
        facts = list(
            RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
        )

        for visa_class, country in distinct_series:
            next_cutoff, _, results, _ = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                monthly_supply=monthly_supply,
                facts=facts,
            )
            pred_ready_month = results[0].month if results else None
            pred_cutoff = results[0].cutoff_date if results else next_cutoff

            if pred_ready_month is None or pred_cutoff is None:
                out.append(
                    LongtermAccuracyRow(
                        knowledge_month=month_first,
                        visa_class=visa_class,
                        country=country,
                        action_type=action_type,
                        predicted_ready_month=None,
                        predicted_cutoff=None,
                        actual_ready_month=None,
                        error_days=None,
                        error_note="no_prediction",
                        horizon_months=None,
                        horizon_bucket=None,
                    )
                )
                continue

            actual_ready_month = None
            first_row = (
                VisaCutoffDate.objects.filter(
                    visa_category=visa_category,
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    bulletin__publication_date__gt=knowledge_date,
                    cutoff_date__gte=pred_cutoff,
                )
                .select_related("bulletin")
                .order_by("bulletin__publication_date")
                .first()
            )
            if first_row:
                actual_ready_month = first_row.bulletin.publication_date

            error_days = None
            error_note = "ok"
            if actual_ready_month is not None:
                error_days = abs((actual_ready_month - pred_ready_month).days)
            else:
                if pred_ready_month < today:
                    diff = (last_bulletin_date - pred_ready_month).days
                    error_days = max(0, int(1.5 * diff))
                    error_note = "pred_past_not_seen"
                else:
                    error_note = "unknown_future"

            h_months = _horizon_months(month_first, pred_ready_month)
            h_bucket = _horizon_bucket(h_months)
            out.append(
                LongtermAccuracyRow(
                    knowledge_month=month_first,
                    visa_class=visa_class,
                    country=country,
                    action_type=action_type,
                    predicted_ready_month=pred_ready_month,
                    predicted_cutoff=pred_cutoff,
                    actual_ready_month=actual_ready_month,
                    error_days=error_days,
                    error_note=error_note,
                    horizon_months=h_months,
                    horizon_bucket=h_bucket,
                )
            )

        completed_months.add(month_key)
        processed += 1

        # Progress logging every 5 months or at end
        if processed % 5 == 0 or (i + 1) == total_months:
            elapsed = time.time() - start_time
            rate = processed / elapsed if elapsed > 0 else 0
            remaining = total_months - skipped - processed
            eta_sec = remaining / rate if rate > 0 else 0
            eta_min = eta_sec / 60
            logger.info(
                "[Longterm] %d/%d months done (skipped %d) | %.2f months/sec | ETA %.1f min | %d rows",
                skipped + processed,
                total_months,
                skipped,
                rate,
                eta_min,
                len(out),
            )
            # Save checkpoint
            if ckpt_path:
                _save_checkpoint(ckpt_path, out, completed_months)

    # Final checkpoint
    if ckpt_path and processed > 0:
        _save_checkpoint(ckpt_path, out, completed_months)
        logger.info(
            "Longterm checkpoint saved: %d months, %d rows",
            len(completed_months),
            len(out),
        )

    return out


def aggregate_bulletin_errors_by_date(
    rows: list[BulletinAccuracyRow],
    filter_visa_class: str | None = None,
    filter_country: int | None = None,
) -> list[tuple[date, float, int]]:
    """Return (bulletin_date, mean_error_days, count) for plotting over time."""
    if filter_visa_class:
        rows = [r for r in rows if r.visa_class == filter_visa_class]
    if filter_country is not None:
        rows = [r for r in rows if r.country == filter_country]
    by_date: dict[date, list[int]] = {}
    for r in rows:
        if r.error_days is not None:
            by_date.setdefault(r.bulletin_date, []).append(r.error_days)
    return [
        (d, sum(errs) / len(errs), len(errs))
        for d in sorted(by_date.keys())
        for errs in [by_date[d]]
    ]


def aggregate_longterm_errors_by_month(
    rows: list[LongtermAccuracyRow],
    filter_visa_class: str | None = None,
    filter_country: int | None = None,
) -> list[tuple[date, float, int]]:
    """Return (knowledge_month, mean_error_days, count) for plotting over time."""
    if filter_visa_class:
        rows = [r for r in rows if r.visa_class == filter_visa_class]
    if filter_country is not None:
        rows = [r for r in rows if r.country == filter_country]
    by_month: dict[date, list[int]] = {}
    for r in rows:
        if r.error_days is not None:
            by_month.setdefault(r.knowledge_month, []).append(r.error_days)
    return [
        (m, sum(errs) / len(errs), len(errs))
        for m in sorted(by_month.keys())
        for errs in [by_month[m]]
    ]


def aggregate_longterm_by_horizon_and_series(
    rows: list[LongtermAccuracyRow],
) -> dict:
    """
    Aggregate long-term accuracy by horizon bucket and by (visa_class, country).

    Returns a dict suitable for longterm_accuracy_summary.json:
      by_horizon: { "1-3": { mean_error_days, count, n_ok }, ... }
      by_series: { "2nd/3": { "1-3": { mean_error_days, count }, ... }, ... }
    """
    from collections import defaultdict

    by_horizon: dict[str, list[int]] = defaultdict(list)
    by_series: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))

    for r in rows:
        if r.error_days is None or r.horizon_bucket is None:
            continue
        by_horizon[r.horizon_bucket].append(r.error_days)
        key = f"{r.visa_class}/{r.country}"
        by_series[key][r.horizon_bucket].append(r.error_days)

    def stats(errs: list[int]) -> dict:
        if not errs:
            return {"mean_error_days": None, "count": 0}
        return {
            "mean_error_days": round(sum(errs) / len(errs), 1),
            "count": len(errs),
        }

    summary = {
        "by_horizon": {
            bucket: stats(errs) for bucket, errs in sorted(by_horizon.items())
        },
        "by_series": {
            series: {bucket: stats(errs) for bucket, errs in sorted(buckets.items())}
            for series, buckets in sorted(by_series.items())
        },
    }
    return summary
