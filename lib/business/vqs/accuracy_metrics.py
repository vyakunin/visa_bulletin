"""VQS prediction accuracy metrics.

Metric 1 – Bulletin-by-bulletin: For each bulletin, pretend knowledge date is
just before publication; predict every cutoff in that bulletin; compute error
vs actual; aggregate by bulletin (and optionally by visa_class, country).

Metric 2 – Long-term "final ready date": For each month M and each (visa_class,
country, action_type), with data as of M predict when the next cutoff will
appear. Compare to first bulletin where that cutoff was reached. If predicted
date is past but cutoff not yet seen, estimate error >= 1.5 * (last_bulletin - pred).

Metric 3 – Multi-horizon composite: For each knowledge date, predict at
horizons h=1,3,6,12 months; combine horizon-weighted errors with period
discounting and optional trend (direction) scoring.
"""

import json
import logging
import time
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

from lib.business.vqs.metric_config import MetricConfig
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


@dataclass
class MultiHorizonRow:
    """One prediction vs actual at a specific horizon from a single knowledge date."""

    knowledge_date: date
    bulletin_date: date  # actual bulletin at knowledge_date + horizon
    visa_class: str
    country: int
    action_type: str
    horizon: int  # months ahead (1, 3, 6, 12)
    predicted_cutoff: date | None
    actual_cutoff: date | None
    error_days: int | None
    direction_correct: bool | None = None  # did we predict the right sign of movement?
    current_cutoff: date | None = None  # cutoff at knowledge_date (baseline)


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


def _build_actuals_by_horizon(
    visa_class: str,
    country: int,
    action_type: str,
    pub_date: date,
    horizon_weights: dict[int, float],
) -> dict[int, date] | None:
    """Look up actual cutoffs at h=3,6,12 months ahead for online learning."""
    from lib.business.vqs.data_cache import get_cutoff_at_date

    horizons_needed = [h for h in horizon_weights if h > 1]
    if not horizons_needed:
        return None
    abh: dict[int, date] = {}
    for h in horizons_needed:
        target_pub = _add_months(pub_date, h - 1)
        future_actual = get_cutoff_at_date(
            visa_class=visa_class,
            country=country,
            action_type=action_type,
            as_of=target_pub,
        )
        if future_actual is not None:
            abh[h] = future_actual
    return abh if abh else None


def compute_bulletin_accuracy(
    bulletins=None,
    visa_category: str = "employment_based",
    monthly_supply: int | None = None,
    checkpoint_dir: Path | None = None,
    meta: "VqsMetaParams | None" = None,  # noqa: F821
    aggregator: "ExpertAggregator | None" = None,  # noqa: F821
    facts: list | None = None,
    exclude_eb4: bool = False,
    action_type: str | None = None,
    horizon: int = 1,
    metric_config: MetricConfig | None = None,
    use_contextual_ensemble: bool = False,
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
        is_current_at_date,
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
        # Exclude Unavailable (NULL cutoff) AND Current rows. A Current cutoff is
        # stored as the bulletin-month sentinel date, not a real cutoff, so
        # scoring it fabricates a spurious error / "↑ 1m" move. Mirrors the
        # existing Unavailable exclusion.
        cutoffs = (
            VisaCutoffDate.objects.filter(
                bulletin__publication_date=t,
                visa_category=visa_category,
                visa_class__in=target_classes,
            )
            .exclude(cutoff_date__isnull=True)
            .exclude(is_current=True)
        )

        # Filter by action_type if specified
        if action_type:
            cutoffs = cutoffs.filter(action_type=action_type)

        for row in cutoffs:
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=row.visa_class,
                country=row.country,
                action_type=row.action_type,
                monthly_supply=monthly_supply,
                facts=current_facts,
                meta=meta,
                aggregator=aggregator,
                metric_config=metric_config,
            )
            next_cutoff = outcome.predicted_cutoff
            metadata = outcome.metadata
            solver_results = outcome.results
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
                # A Current (no-backlog) actual is the bulletin-month sentinel,
                # not a real cutoff. For horizon 1 the row is already excluded
                # above; for longer horizons the actual comes from
                # get_cutoff_at_date and may land on a Current sentinel, so guard.
                actual_as_of = t if horizon == 1 else future_pub_est
                if not is_current_at_date(
                    row.visa_class, row.country, row.action_type, actual_as_of
                ):
                    error_days = abs((pred_cutoff - actual).days)

            # Online Learning Update with multi-horizon actuals
            if aggregator and actual is not None:
                abh = _build_actuals_by_horizon(
                    row.visa_class, row.country, row.action_type, t,
                    aggregator.metric_config.horizon_weights,
                )
                aggregator.update(
                    row.visa_class,
                    row.country,
                    knowledge_date,
                    actual,
                    action_type=row.action_type,
                    actuals_by_horizon=abh,
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
            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=visa_class,
                country=country,
                action_type=action_type,
                monthly_supply=monthly_supply,
                facts=facts,
            )
            next_cutoff = outcome.predicted_cutoff
            results = outcome.results
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


def compare_to_no_change_baseline(
    rows: list[BulletinAccuracyRow],
    exclude_eb4: bool = True,
    recent_only: bool = False,
    recent_cutoff: date | None = None,
) -> dict:
    """
    Compare model predictions to the no-change baseline (prev cutoff = next cutoff).

    Returns dict with:
        model_mean_error, baseline_mean_error, model_wins, baseline_wins,
        ties, total, model_win_pct, rows_where_differ, model_mean_when_differ,
        baseline_mean_when_differ.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    if recent_cutoff is None and recent_only:
        recent_cutoff = date(2024, 1, 1)

    filtered = rows
    if exclude_eb4:
        filtered = [r for r in filtered if r.visa_class != "4th"]
    if recent_only and recent_cutoff:
        filtered = [r for r in filtered if r.bulletin_date >= recent_cutoff]

    model_errors = []
    baseline_errors = []
    model_wins = 0
    baseline_wins = 0
    ties = 0
    differ_model = []
    differ_baseline = []

    for r in filtered:
        if r.error_days is None or r.predicted_cutoff is None:
            continue

        prev_cutoff = get_cutoff_at_date(
            r.visa_class, r.country, r.action_type,
            r.bulletin_date - timedelta(days=1),
        )
        if prev_cutoff is None:
            continue

        baseline_err = abs((prev_cutoff - r.actual_cutoff).days)
        model_err = r.error_days

        model_errors.append(model_err)
        baseline_errors.append(baseline_err)

        if model_err < baseline_err:
            model_wins += 1
        elif baseline_err < model_err:
            baseline_wins += 1
        else:
            ties += 1

        if r.predicted_cutoff != prev_cutoff:
            differ_model.append(model_err)
            differ_baseline.append(baseline_err)

    total = len(model_errors)
    return {
        "total": total,
        "model_mean_error": round(sum(model_errors) / total, 1) if total else None,
        "baseline_mean_error": round(sum(baseline_errors) / total, 1) if total else None,
        "model_wins": model_wins,
        "baseline_wins": baseline_wins,
        "ties": ties,
        "model_win_pct": round(100 * model_wins / total, 1) if total else None,
        "rows_where_differ": len(differ_model),
        "model_mean_when_differ": round(sum(differ_model) / len(differ_model), 1) if differ_model else None,
        "baseline_mean_when_differ": round(sum(differ_baseline) / len(differ_baseline), 1) if differ_baseline else None,
        "beats_baseline": (sum(model_errors) / total < sum(baseline_errors) / total) if total else False,
    }


def _add_months(d: date, months: int) -> date:
    """Return first day of month d + months."""
    year, month = d.year, d.month
    month += months
    while month > 12:
        month -= 12
        year += 1
    while month < 1:
        month += 12
        year -= 1
    return date(year, month, 1)


def compute_multi_horizon_accuracy(
    bulletins: list[date] | None = None,
    visa_category: str = "employment_based",
    horizons: list[int] | None = None,
    monthly_supply: int | None = None,
    meta: "VqsMetaParams | None" = None,  # noqa: F821
    aggregator: "ExpertAggregator | None" = None,  # noqa: F821
    facts: list | None = None,
    exclude_eb4: bool = True,
    action_type: str | None = None,
    metric_config: MetricConfig | None = None,
    use_contextual_ensemble: bool = False,
) -> list[MultiHorizonRow]:
    """Predict at multiple horizons from each knowledge date, compare to actuals.

    For each bulletin_date B and each (visa_class, country) series:
    1. Set knowledge_date = B - 1 day.
    2. Call solver once to get solver_results (list of monthly steps).
    3. For each horizon h in horizons: extract prediction at step h-1,
       look up actual cutoff at B + h months, record error.
    """
    from lib.business.vqs.data_cache import (
        get_all_bulletins,
        get_cutoff_at_date,
        is_current_at_date,
    )
    from lib.business.vqs.solver import predict_next_bulletin_and_maturity
    from models.raw_facts import RawFactsLedger
    from models.visa_cutoff_date import VisaCutoffDate

    if horizons is None:
        horizons = [1, 3, 6, 12]

    if bulletins is None:
        bulletins = [b.publication_date for b in get_all_bulletins()]
    else:
        bulletins = list(bulletins)

    max_horizon = max(horizons)
    # Trim bulletins so we have room for the longest horizon
    all_pub_dates = sorted(bulletins)
    if not all_pub_dates:
        return []
    last_available = all_pub_dates[-1]
    eval_bulletins = [
        b for b in all_pub_dates if _add_months(b, max_horizon) <= last_available
    ]

    target_classes = QUEUE_DRIVEN_CLASSES if exclude_eb4 else EVALUABLE_VISA_CLASSES

    total = len(eval_bulletins)
    logger.info(
        "Multi-horizon accuracy: %d bulletins, horizons=%s", total, horizons
    )

    n_facts = len(facts) if facts is not None else 0
    fact_idx = 0
    rows: list[MultiHorizonRow] = []
    start_time = time.time()

    for i, pub_date in enumerate(eval_bulletins):
        knowledge_date = pub_date - timedelta(days=1)

        current_facts = None
        if facts is not None:
            while fact_idx < n_facts and facts[fact_idx].publication_date <= knowledge_date:
                fact_idx += 1
            current_facts = facts[:fact_idx]
        else:
            current_facts = list(
                RawFactsLedger.objects.filter(publication_date__lte=knowledge_date)
            )

        # Exclude Unavailable (NULL cutoff) AND Current base rows (bulletin-month
        # sentinel, not a real cutoff) — mirrors the Unavailable exclusion.
        cutoffs = (
            VisaCutoffDate.objects.filter(
                bulletin__publication_date=pub_date,
                visa_category=visa_category,
                visa_class__in=target_classes,
            )
            .exclude(cutoff_date__isnull=True)
            .exclude(is_current=True)
        )

        if action_type:
            cutoffs = cutoffs.filter(action_type=action_type)

        for row in cutoffs:
            current_cutoff = row.cutoff_date

            if use_contextual_ensemble:
                # Update weights up to knowledge_date
                # We can just call warmup_history which is idempotent and fast if we optimize it,
                # but ContextualTrajectoryAggregator doesn't have a fast path yet.
                # Actually, we can just call it.
                aggregator.warmup_history(
                    visa_class=row.visa_class,
                    country=row.country,
                    action_type=row.action_type,
                    knowledge_date=knowledge_date,
                    horizons=horizons,
                )

                for h in horizons:
                    target_month = _add_months(pub_date, h - 1)
                    pred, _ = aggregator.predict(
                        visa_class=row.visa_class,
                        country=row.country,
                        action_type=row.action_type,
                        target_date=target_month,
                        horizon=h,
                    )

                    actual = get_cutoff_at_date(
                        visa_class=row.visa_class,
                        country=row.country,
                        action_type=row.action_type,
                        as_of=target_month,
                    )

                    error = None
                    direction_correct = None
                    # Skip Current (no-backlog) actuals: the stored cutoff is the
                    # bulletin-month sentinel, so differencing it fabricates a
                    # spurious error / movement.
                    actual_is_current = is_current_at_date(
                        row.visa_class, row.country, row.action_type, target_month
                    )
                    if pred is not None and actual is not None and not actual_is_current:
                        error = abs((pred - actual).days)
                        if current_cutoff is not None:
                            pred_move = (pred - current_cutoff).days
                            actual_move = (actual - current_cutoff).days
                            if actual_move == 0 and pred_move == 0:
                                direction_correct = True
                            elif actual_move != 0:
                                direction_correct = (
                                    (pred_move > 0 and actual_move > 0)
                                    or (pred_move < 0 and actual_move < 0)
                                )

                    rows.append(
                        MultiHorizonRow(
                            knowledge_date=knowledge_date,
                            bulletin_date=target_month,
                            visa_class=row.visa_class,
                            country=row.country,
                            action_type=row.action_type,
                            horizon=h,
                            predicted_cutoff=pred,
                            actual_cutoff=actual,
                            error_days=error,
                            direction_correct=direction_correct,
                            current_cutoff=current_cutoff,
                        )
                    )
                continue

            outcome = predict_next_bulletin_and_maturity(
                knowledge_date=knowledge_date,
                visa_class=row.visa_class,
                country=row.country,
                action_type=row.action_type,
                monthly_supply=monthly_supply,
                facts=current_facts,
                meta=meta,
                aggregator=aggregator,
                metric_config=metric_config,
            )
            next_cutoff = outcome.predicted_cutoff
            solver_results = outcome.results

            for h in horizons:
                # Prediction at horizon h
                if h == 1:
                    pred = next_cutoff
                else:
                    idx = h - 1
                    pred = solver_results[idx].cutoff_date if idx < len(solver_results) else None

                # Actual cutoff at horizon h
                target_pub = _add_months(pub_date, h - 1)
                actual = get_cutoff_at_date(
                    visa_class=row.visa_class,
                    country=row.country,
                    action_type=row.action_type,
                    as_of=target_pub,
                )

                error = None
                direction_correct = None
                # Skip Current (no-backlog) actuals: the stored cutoff is the
                # bulletin-month sentinel, so differencing it fabricates a
                # spurious error / movement.
                actual_is_current = is_current_at_date(
                    row.visa_class, row.country, row.action_type, target_pub
                )
                if pred is not None and actual is not None and not actual_is_current:
                    error = abs((pred - actual).days)

                    if current_cutoff is not None:
                        pred_move = (pred - current_cutoff).days
                        actual_move = (actual - current_cutoff).days
                        if actual_move == 0 and pred_move == 0:
                            direction_correct = True
                        elif actual_move != 0:
                            direction_correct = (
                                (pred_move > 0 and actual_move > 0)
                                or (pred_move < 0 and actual_move < 0)
                            )

                rows.append(
                    MultiHorizonRow(
                        knowledge_date=knowledge_date,
                        bulletin_date=target_pub,
                        visa_class=row.visa_class,
                        country=row.country,
                        action_type=row.action_type,
                        horizon=h,
                        predicted_cutoff=pred,
                        actual_cutoff=actual,
                        error_days=error,
                        direction_correct=direction_correct,
                        current_cutoff=current_cutoff,
                    )
                )

        if (i + 1) % 10 == 0 or (i + 1) == total:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed if elapsed > 0 else 0
            logger.info(
                "[MultiHorizon] %d/%d bulletins | %.1f/sec | %d rows",
                i + 1, total, rate, len(rows),
            )

    return rows


def compute_composite_metric(
    rows: list[MultiHorizonRow],
    config: MetricConfig | None = None,
    use_predictability_weight: bool = False,
    facts: list | None = None,
) -> dict:
    """Compute the weighted composite metric from multi-horizon rows.

    Returns dict with per-horizon MAE, composite score, trend score,
    and overall weighted metric.

    When use_predictability_weight=True, each data point is additionally
    weighted by I-140 coverage and recent cutoff volatility, focusing
    the metric on series where the model can realistically be accurate.
    """
    if config is None:
        config = MetricConfig.defaults()

    pred_weight_cache: dict[tuple[str, int, str], float] = {}

    by_horizon: dict[int, list[tuple[float, float]]] = defaultdict(list)

    for r in rows:
        if r.error_days is None:
            continue

        actual_move = None
        if r.actual_cutoff and r.current_cutoff:
            actual_move = (r.actual_cutoff - r.current_cutoff).days

        w = config.composite_weight(
            d=r.knowledge_date,
            visa_class=r.visa_class,
            country=r.country,
            target_month=r.bulletin_date.month if r.bulletin_date else None,
            actual_move_days=actual_move,
        )

        if use_predictability_weight:
            cache_key = (r.visa_class, r.country, r.knowledge_date.isoformat())
            if cache_key not in pred_weight_cache:
                pred_weight_cache[cache_key] = predictability_weight(
                    r.visa_class, r.country, r.knowledge_date,
                    facts=facts, config=config,
                )
            w *= pred_weight_cache[cache_key]

        by_horizon[r.horizon].append((float(r.error_days), w))

    per_horizon: dict[int, dict] = {}
    for h in sorted(by_horizon.keys()):
        errors_weights = by_horizon[h]
        total_w = sum(w for _, w in errors_weights)
        if total_w == 0:
            continue
        weighted_mae = sum(e * w for e, w in errors_weights) / total_w
        count = len(errors_weights)
        per_horizon[h] = {"mae": round(weighted_mae, 1), "count": count}

    composite = 0.0
    total_hw = 0.0
    for h, stats in per_horizon.items():
        hw = config.horizon_weights.get(h, 0.0)
        composite += hw * stats["mae"]
        total_hw += hw
    if total_hw > 0:
        composite /= total_hw

    # Trend (direction) score per horizon
    trend_by_horizon: dict[int, dict] = {}
    for h in sorted(by_horizon.keys()):
        h_rows = [r for r in rows if r.horizon == h and r.direction_correct is not None]
        if h_rows:
            correct = sum(1 for r in h_rows if r.direction_correct)
            trend_by_horizon[h] = {
                "direction_accuracy": round(correct / len(h_rows), 3),
                "count": len(h_rows),
            }

    overall_trend = 0.0
    trend_total_hw = 0.0
    for h, stats in trend_by_horizon.items():
        hw = config.horizon_weights.get(h, 0.0)
        overall_trend += hw * stats["direction_accuracy"]
        trend_total_hw += hw
    if trend_total_hw > 0:
        overall_trend /= trend_total_hw

    # Final blended metric: lower is better.
    # composite MAE (lower = better) vs direction (higher = better),
    # so we use (1 - direction_accuracy) scaled by composite for the trend term.
    alpha = config.trend_weight
    if alpha > 0 and composite > 0:
        final = (1.0 - alpha) * composite + alpha * composite * (1.0 - overall_trend)
    else:
        final = composite

    return {
        "composite_mae": round(composite, 1),
        "overall_trend_accuracy": round(overall_trend, 3),
        "blended_metric": round(final, 1),
        "per_horizon": per_horizon,
        "trend_by_horizon": trend_by_horizon,
    }


def predictability_weight(
    visa_class: str,
    country: int,
    knowledge_date: date,
    facts: list | None = None,
    config: MetricConfig | None = None,
) -> float:
    """Weight reflecting how predictable a (series, time) cell is.

    Combines I-140 data confidence with recent cutoff volatility.
    """
    from lib.business.vqs.seasonal_predictor import get_last_N_moves
    from lib.business.vqs.solver import compute_confidence

    if config is None:
        config = MetricConfig.defaults()

    conf = compute_confidence(facts or [], visa_class, country)
    conf_w = {"high": 1.0, "medium": 0.6, "low": 0.2}.get(conf, 0.2)

    recent_moves = get_last_N_moves(
        visa_class, country, "final_action", knowledge_date, 6
    )
    vol_w = config.volatility_weight([float(m) for m in recent_moves] if recent_moves else [])

    return conf_w * vol_w


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


@dataclass
class CICoverageResult:
    """Confidence interval calibration metrics."""

    total_with_ci: int
    hits: int
    coverage_rate: float
    mean_ci_width_days: float
    by_series: dict[str, dict]


def compute_ci_coverage(
    rows: list[BulletinAccuracyRow],
    exclude_eb4: bool = True,
) -> CICoverageResult:
    """Measure how often actual cutoffs fall within predicted confidence intervals.

    Target coverage: ~80%. If actual coverage is much lower, the CI computation
    (asymmetric 30%/70% spread in solver.py) needs widening. If much higher,
    the intervals are too conservative and could be tightened.
    """
    filtered = rows
    if exclude_eb4:
        filtered = [r for r in filtered if r.visa_class != "4th"]

    total_with_ci = 0
    hits = 0
    ci_widths: list[int] = []
    by_series: dict[str, dict[str, int]] = defaultdict(lambda: {"total": 0, "hits": 0, "widths": []})

    for r in filtered:
        if r.confidence_low is None or r.confidence_high is None:
            continue
        if r.actual_cutoff is None:
            continue
        total_with_ci += 1
        width = (r.confidence_high - r.confidence_low).days
        ci_widths.append(width)
        key = f"{r.visa_class}/{r.country}"
        by_series[key]["total"] += 1
        by_series[key]["widths"].append(width)

        if r.confidence_low <= r.actual_cutoff <= r.confidence_high:
            hits += 1
            by_series[key]["hits"] += 1

    coverage = hits / total_with_ci if total_with_ci > 0 else 0.0
    mean_width = sum(ci_widths) / len(ci_widths) if ci_widths else 0.0

    series_summary = {}
    for key, data in sorted(by_series.items()):
        t = data["total"]
        h = data["hits"]
        w = data["widths"]
        series_summary[key] = {
            "total": t,
            "hits": h,
            "coverage_rate": round(h / t, 3) if t > 0 else 0.0,
            "mean_ci_width_days": round(sum(w) / len(w), 1) if w else 0.0,
        }

    return CICoverageResult(
        total_with_ci=total_with_ci,
        hits=hits,
        coverage_rate=round(coverage, 3),
        mean_ci_width_days=round(mean_width, 1),
        by_series=series_summary,
    )
