"""Fiscal Year utilization tracking from DOS issuance data.

Computes cumulative visa issuance within each fiscal year and
correlates utilization rate with FY transition magnitudes (Oct jumps,
Aug/Sep retrogressions). This module provides the features for the
conditional FY transition predictor.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from statistics import median

from lib.business.vqs.data_cache import (
    get_cutoff_at_date,
    get_cutoffs_for_series,
    is_current_at_date,
    is_unavailable_at_date,
)
from lib.business.vqs.estimators import (
    DEFAULT_ANNUAL_EB_LIMIT,
    PER_CLASS_SHARE,
    PER_COUNTRY_SHARE,
)

logger = logging.getLogger(__name__)


@dataclass
class FYTransition:
    """Data about a single fiscal year boundary transition."""
    fiscal_year: int
    visa_class: str
    country: int
    october_jump_days: int | None
    september_move_days: int | None
    august_move_days: int | None
    utilization_rate: float | None
    backlog_depth_days: int | None
    prior_fy_avg_pace: float | None


def get_fiscal_year(month_date: date) -> int:
    """Return the fiscal year for a given date. FY starts in October."""
    return month_date.year if month_date.month >= 10 else month_date.year - 1


def compute_fy_issuance(
    facts: list,
    visa_class: str,
    country: int,
    knowledge_date: date,
) -> dict[int, dict[int, float]]:
    """Compute cumulative issuance by FY and month from DOS issuance facts.

    Returns: {fiscal_year: {month: cumulative_issuance}} where month is 10-12, 1-9.
    Only uses facts published before knowledge_date (walk-forward safe).
    """
    monthly: dict[int, dict[int, float]] = defaultdict(lambda: defaultdict(float))

    for f in facts:
        if f.metric != "visa_issuance_monthly":
            continue
        if f.publication_date >= knowledge_date:
            continue

        dims = f.dimensions if isinstance(f.dimensions, dict) else {}
        if str(dims.get("country")) != str(country):
            continue
        fact_vc = dims.get("visa_class", "")
        if str(fact_vc) != str(visa_class):
            continue

        ref_month = f.reference_period_start.month
        fy = get_fiscal_year(f.reference_period_start)

        val = f.value
        if isinstance(val, list) and len(val) > 0:
            monthly[fy][ref_month] += float(val[0])
        elif isinstance(val, (int, float)):
            monthly[fy][ref_month] += float(val)

    # Convert to cumulative within each FY
    cumulative: dict[int, dict[int, float]] = {}
    fy_month_order = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    for fy, month_vals in monthly.items():
        cumulative[fy] = {}
        running = 0.0
        for m in fy_month_order:
            running += month_vals.get(m, 0.0)
            if month_vals.get(m, 0.0) > 0:
                cumulative[fy][m] = running

    return cumulative


def compute_utilization_rate(
    facts: list,
    visa_class: str,
    country: int,
    knowledge_date: date,
    as_of_month: int | None = None,
) -> dict[int, float]:
    """Compute FY utilization rate = cumulative_issuance / annual_allocation.

    Returns: {fiscal_year: utilization_rate}
    If as_of_month is given, uses cumulative up to that month only.
    """
    cumulative = compute_fy_issuance(facts, visa_class, country, knowledge_date)

    class_share = PER_CLASS_SHARE.get(visa_class, 0.286)
    annual_allocation = DEFAULT_ANNUAL_EB_LIMIT * PER_COUNTRY_SHARE * class_share

    rates: dict[int, float] = {}
    fy_month_order = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]

    for fy, months in cumulative.items():
        if as_of_month is not None:
            target_months = []
            for m in fy_month_order:
                target_months.append(m)
                if m == as_of_month:
                    break
            last_val = 0.0
            for m in target_months:
                if m in months:
                    last_val = months[m]
            rates[fy] = last_val / annual_allocation if annual_allocation > 0 else 0.0
        else:
            if months:
                max_cumul = max(months.values())
                rates[fy] = max_cumul / annual_allocation if annual_allocation > 0 else 0.0

    return rates


def compute_backlog_depth(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
) -> int | None:
    """Compute backlog depth = (knowledge_date - current_cutoff).days.

    Larger values mean deeper backlog. Returns 0 for a "Current" series (the
    cutoff has caught up, so there is no backlog) and None for "Unavailable" or
    no-data (a real backlog exists but its depth is not derivable from a stale
    pre-Unavailable cutoff).
    """
    # Must guard Current/Unavailable BEFORE reading get_cutoff_at_date, which
    # returns a stale years-old cutoff during those spells → phantom huge backlog.
    if is_current_at_date(visa_class, country, action_type, knowledge_date):
        return 0
    if is_unavailable_at_date(visa_class, country, action_type, knowledge_date):
        return None
    latest_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if latest_cutoff is None:
        return None
    return (knowledge_date - latest_cutoff).days


def collect_fy_transitions(
    visa_class: str,
    country: int,
    action_type: str,
    start_year: int = 2017,
    end_year: int = 2025,
    facts: list | None = None,
) -> list[FYTransition]:
    """Collect all FY transitions for a series with contextual features.

    For each FY boundary year, records:
    - October jump magnitude (Sep->Oct cutoff change in days)
    - September move magnitude (Aug->Sep cutoff change)
    - August move magnitude (Jul->Aug cutoff change)
    - FY utilization rate (cumulative DOS issuance / allocation at end of prior FY)
    - Backlog depth at time of transition
    - Average pace in the 6 months before transition
    """
    all_cutoffs = get_cutoffs_for_series(visa_class, country, action_type)

    by_ym: dict[tuple[int, int], date] = {}
    for c in all_cutoffs:
        if c.cutoff_date is not None:
            pub = c.bulletin.publication_date
            by_ym[(pub.year, pub.month)] = c.cutoff_date

    transitions: list[FYTransition] = []

    for year in range(start_year, end_year + 1):
        oct_cutoff = by_ym.get((year, 10))
        sep_cutoff = by_ym.get((year, 9))
        aug_cutoff = by_ym.get((year, 8))
        jul_cutoff = by_ym.get((year, 7))

        october_jump = None
        if oct_cutoff and sep_cutoff:
            october_jump = (oct_cutoff - sep_cutoff).days

        september_move = None
        if sep_cutoff and aug_cutoff:
            september_move = (sep_cutoff - aug_cutoff).days

        august_move = None
        if aug_cutoff and jul_cutoff:
            august_move = (aug_cutoff - jul_cutoff).days

        # Utilization rate at end of prior FY (Sept of current year)
        util_rate = None
        if facts is not None:
            knowledge = date(year, 10, 1)
            rates = compute_utilization_rate(facts, visa_class, country, knowledge, as_of_month=9)
            # The FY ending in September of 'year' is FY (year-1)
            # e.g., Sept 2024 is end of FY2024 (Oct 2023 - Sep 2024)
            prior_fy = year - 1
            util_rate = rates.get(prior_fy)

        backlog = compute_backlog_depth(
            visa_class, country, action_type, date(year, 9, 15)
        )

        # Average pace in 6 months before September
        pace_moves = []
        for m_offset in range(6):
            check_year = year
            check_month = 9 - m_offset
            if check_month <= 0:
                check_month += 12
                check_year -= 1
            prev_month = check_month - 1
            prev_year = check_year
            if prev_month <= 0:
                prev_month += 12
                prev_year -= 1

            c1 = by_ym.get((prev_year, prev_month))
            c2 = by_ym.get((check_year, check_month))
            if c1 and c2:
                pace_moves.append((c2 - c1).days)

        avg_pace = sum(pace_moves) / len(pace_moves) if pace_moves else None

        if october_jump is not None or september_move is not None:
            transitions.append(FYTransition(
                fiscal_year=year,
                visa_class=visa_class,
                country=country,
                october_jump_days=october_jump,
                september_move_days=september_move,
                august_move_days=august_move,
                utilization_rate=util_rate,
                backlog_depth_days=backlog,
                prior_fy_avg_pace=avg_pace,
            ))

    return transitions


def predict_october_jump_conditional(
    transitions: list[FYTransition],
    target_year: int,
    current_backlog: int | None = None,
    current_utilization: float | None = None,
) -> tuple[int, dict]:
    """Predict October jump magnitude using conditional features.

    Uses leave-one-out: excludes target_year from training data.
    Falls back to unconditional median if features are missing.

    Returns: (predicted_jump_days, diagnostics_dict)
    """
    train = [t for t in transitions if t.fiscal_year != target_year and t.october_jump_days is not None]

    if not train:
        return 0, {"method": "no_data"}

    jumps = [t.october_jump_days for t in train]
    unconditional_median = int(median(jumps))

    # If we have feature data, use weighted nearest-neighbor approach
    has_backlog = current_backlog is not None and any(t.backlog_depth_days is not None for t in train)
    has_util = current_utilization is not None and any(t.utilization_rate is not None for t in train)

    if not has_backlog and not has_util:
        return unconditional_median, {
            "method": "unconditional_median",
            "n_samples": len(train),
            "median": unconditional_median,
        }

    # Simple weighted regression: weight historical transitions by feature similarity
    weighted_sum = 0.0
    weight_total = 0.0

    for t in train:
        similarity = 1.0

        if has_backlog and t.backlog_depth_days is not None:
            backlog_diff = abs(current_backlog - t.backlog_depth_days) / max(1, current_backlog)
            similarity *= max(0.1, 1.0 - backlog_diff)

        if has_util and t.utilization_rate is not None:
            util_diff = abs(current_utilization - t.utilization_rate)
            similarity *= max(0.1, 1.0 - util_diff * 2.0)

        weighted_sum += t.october_jump_days * similarity
        weight_total += similarity

    if weight_total > 0:
        conditional_pred = int(weighted_sum / weight_total)
    else:
        conditional_pred = unconditional_median

    return conditional_pred, {
        "method": "conditional_weighted",
        "n_samples": len(train),
        "unconditional_median": unconditional_median,
        "conditional_pred": conditional_pred,
        "current_backlog": current_backlog,
        "current_utilization": current_utilization,
    }


def predict_september_retrogression_conditional(
    transitions: list[FYTransition],
    target_year: int,
    current_backlog: int | None = None,
    current_utilization: float | None = None,
) -> tuple[int, dict]:
    """Predict September retrogression magnitude using conditional features.

    Same approach as October but targets September move (typically negative).
    """
    train = [t for t in transitions if t.fiscal_year != target_year and t.september_move_days is not None]

    if not train:
        return 0, {"method": "no_data"}

    moves = [t.september_move_days for t in train]
    unconditional_median = int(median(moves))

    has_backlog = current_backlog is not None and any(t.backlog_depth_days is not None for t in train)
    has_util = current_utilization is not None and any(t.utilization_rate is not None for t in train)

    if not has_backlog and not has_util:
        return unconditional_median, {
            "method": "unconditional_median",
            "n_samples": len(train),
            "median": unconditional_median,
        }

    weighted_sum = 0.0
    weight_total = 0.0

    for t in train:
        similarity = 1.0

        if has_backlog and t.backlog_depth_days is not None:
            backlog_diff = abs(current_backlog - t.backlog_depth_days) / max(1, current_backlog)
            similarity *= max(0.1, 1.0 - backlog_diff)

        if has_util and t.utilization_rate is not None:
            util_diff = abs(current_utilization - t.utilization_rate)
            similarity *= max(0.1, 1.0 - util_diff * 2.0)

        weighted_sum += t.september_move_days * similarity
        weight_total += similarity

    conditional_pred = int(weighted_sum / weight_total) if weight_total > 0 else unconditional_median

    return conditional_pred, {
        "method": "conditional_weighted",
        "n_samples": len(train),
        "unconditional_median": unconditional_median,
        "conditional_pred": conditional_pred,
    }
