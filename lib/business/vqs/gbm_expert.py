"""GBM Expert for VQS prediction.

A LightGBM model trained on tabular features per (series, knowledge_date) to
predict next-month cutoff movement in days. Integrates as a new expert in the
pool alongside the existing rule-based experts.

Key design decisions:
- All 6 oversubscribed EB series are pooled together for training (more data).
  Series identity is encoded as integer features.
- Walk-forward training: at each knowledge_date, the model is trained on all
  historical (series, month) pairs up to that date. Model is cached per month
  to avoid retraining on every call.
- Incorporates independent signals: I-485 queue depth, cross-series EB-1 momentum,
  I-140 receipt trends, FY utilization, and demand velocity features which other
  experts do not combine simultaneously.

Base features per (series, knowledge_date) [indices 0-21]:
  - series_country: India=3, China=2
  - series_class: 1st=1, 2nd=2, 3rd=3
  - move_1m, move_2m, move_3m: recent monthly movements (days)
  - move_6m_avg, move_12m_avg: trailing average movements
  - month_of_year: 1-12 (seasonal)
  - is_fy_reset: 1 if October, 0 otherwise
  - is_end_of_fy: 1 if July/August/September
  - cutoff_age_days: days from current cutoff to knowledge_date (backlog proxy)
  - i140_ratio: recent 2 quarters I-140 vs historical baseline (country-level)
  - i485_queue_size: pending I-485 applications within 3-year window
  - eb1_move_1m, eb1_move_3m, eb1_regime_state: cross-series EB-1 signals
  - utilization_rate: current FY visa issuance / annual allocation
  - months_into_fy: 1=Oct, 2=Nov, ..., 12=Sep
  - demand_ratio_class: I-140 ratio filtered by (class, country) if data available
  - cutoff_velocity_6m: (cutoff_now - cutoff_6m_ago).days / 6 (trend over 6 months)
  - retro_distance_months: months until next October (FY reset proximity)
  - eb1_surplus_indicator: 1 if EB-1 same-country had Current status in last 3m

Demand-drop features (indices 22-25):
  - row_move_1m: ROW same-class cutoff move last month (leading indicator)
  - row_move_3m_avg: ROW same-class 3m average move
  - row_is_current: 1.0 if ROW cutoff is effectively Current (within 60d)
  - issuance_drop_ratio: recent 3m issuance / prior-year same 3m (< 0.7 = demand drop)

Queue density features (index 26):
  - i485_density_near_cutoff: fraction of pending I-485s with PD within 2 years
    ahead of cutoff. Low = fast advance possible; high = backlog, slow advance.
    Targets India EB-3 and similar series with dense near-cutoff queues.

Horizon-specific features (appended for multi-horizon models) [indices 27-29]:
  - horizon: prediction horizon in months
  - target_month_of_year: month of target date (1-12)
  - target_months_into_fy: FY position of target month (1=Oct)

Targets:
  - Regression: next-h-month cumulative cutoff movement in days
  - Classifier: 1 if |cumulative_move| > movement_threshold else 0
  - Quantile: same as regression but with quantile loss
"""

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_MIN_TRAINING_SAMPLES = 36

_GBM_ELIGIBLE = frozenset([
    (2, "2nd"), (2, "3rd"), (2, "1st"),
    (3, "2nd"), (3, "3rd"), (3, "1st"),
])

# Series for which demand-drop features (indices 22-25: ROW velocity + issuance drop) are
# zeroed at inference. Section 17 ablation: removing these saves ~60d MAE on India EB-3 at 6m;
# the ROW "Current" signal misleads the model on deeply-backlogged series.
_DEMAND_DROP_MASKED_SERIES: frozenset[tuple[int, str]] = frozenset([
    (3, "3rd"),  # India EB-3: ablation saves ~60d MAE at 6m (Section 17)
])

_CLASS_ENCODING = {"1st": 1, "2nd": 2, "3rd": 3}

# Caches keyed by (year, month) for 1m; (year, month, horizon) for multi-horizon
_model_cache: dict[tuple, object] = {}
_classifier_cache: dict[tuple, object] = {}
_quantile_cache: dict[tuple, object] = {}

# Default GBM hyperparameters — tuned with Optuna (Section 16, March 2026) using
# a direct GBM-only conditional objective (not VQS ensemble). Improvements vs defaults:
#   F1: 0.31 → 0.48, CondMAE: 144d → 129d, 6mMAE: 225d → 201d (quick-mode eval).
_GBM_N_ESTIMATORS: int = 258
_GBM_MAX_DEPTH: int = 8
_GBM_NUM_LEAVES: int = 255  # 2^8 - 1
_GBM_LEARNING_RATE: float = 0.103
_GBM_MIN_CHILD_SAMPLES: int = 15
_GBM_REG_ALPHA: float = 2.34
_GBM_REG_LAMBDA: float = 4.11
# Default gate / movement thresholds for expert_gbm_gated and expert_gbm_movement_prob
_GBM_DEFAULT_MOVEMENT_THRESHOLD: int = 50
_GBM_DEFAULT_GATE_THRESHOLD: float = 0.68


def _get_i140_ratio(country: int, knowledge_date: date, facts: list | None = None) -> float:
    """Ratio of recent I-140 receipts to historical average. 1.0 = no change."""
    from models.raw_facts import RawFactsLedger

    if facts is None:
        rows = list(
            RawFactsLedger.objects.filter(
                metric="i140_receipts",
                publication_date__lt=knowledge_date,
            ).order_by("reference_period_start")
        )
    else:
        rows = sorted(
            [f for f in facts if f.metric == "i140_receipts" and f.publication_date < knowledge_date],
            key=lambda x: x.reference_period_start,
        )

    country_rows = [r for r in rows if str(r.dimensions.get("country")) == str(country)]
    if len(country_rows) < 4:
        return 1.0

    def get_val(f) -> float:
        v = f.value
        if isinstance(v, (list, tuple)) and v:
            v = v[0]
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    recent = country_rows[-2:]
    hist = country_rows[:-2]
    recent_avg = sum(get_val(r) for r in recent) / 2
    hist_avg = sum(get_val(r) for r in hist) / len(hist)
    return (recent_avg / hist_avg) if hist_avg > 0 else 1.0


def _get_i140_ratio_class(
    visa_class: str, country: int, knowledge_date: date, facts: list | None = None
) -> float:
    """I-140 demand ratio filtered by (visa_class, country) if class dimension available.

    Falls back to country-level ratio when class dimension is absent in the data.
    """
    from models.raw_facts import RawFactsLedger

    if facts is None:
        rows = list(
            RawFactsLedger.objects.filter(
                metric="i140_receipts",
                publication_date__lt=knowledge_date,
            ).order_by("reference_period_start")
        )
    else:
        rows = sorted(
            [f for f in facts if f.metric == "i140_receipts" and f.publication_date < knowledge_date],
            key=lambda x: x.reference_period_start,
        )

    country_rows = [r for r in rows if str(r.dimensions.get("country")) == str(country)]
    class_rows = [
        r for r in country_rows
        if r.dimensions.get("visa_class") and str(r.dimensions.get("visa_class")) == str(visa_class)
    ]

    # Use class-filtered rows if sufficient, else fall back to country rows
    target_rows = class_rows if len(class_rows) >= 4 else country_rows
    if len(target_rows) < 4:
        return 1.0

    def get_val(f) -> float:
        v = f.value
        if isinstance(v, (list, tuple)) and v:
            v = v[0]
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    recent = target_rows[-2:]
    hist = target_rows[:-2]
    recent_avg = sum(get_val(r) for r in recent) / 2
    hist_avg = sum(get_val(r) for r in hist) / len(hist)
    return (recent_avg / hist_avg) if hist_avg > 0 else 1.0


def _get_i485_rows_most_recent(
    visa_class: str, country: int, knowledge_date: date, facts: list | None = None
) -> list:
    """Return the most-recent snapshot of I-485 inventory rows for (visa_class, country).

    The USCIS I-485 inventory stores each row as:
      dimensions = {"country": int, "visa_class": str}
      reference_period_start = date(year, month, 1)  ← priority date month
      value = count of pending I-485s with that PD

    We keep only the single most-recent publication snapshot (within 6 months
    of knowledge_date) to avoid double-counting when multiple snapshots coexist.
    Returns [] when no data is available.
    """
    from models.raw_facts import RawFactsLedger

    if facts is None:
        rows = list(
            RawFactsLedger.objects.filter(
                metric="i485_pending_inventory_monthly",
                publication_date__lte=knowledge_date,
                dimensions__contains={"country": country, "visa_class": visa_class},
            ).order_by("-publication_date")
        )
    else:
        rows = sorted(
            [
                f for f in facts
                if f.metric == "i485_pending_inventory_monthly"
                and f.publication_date <= knowledge_date
                and isinstance(f.dimensions, dict)
                and str(f.dimensions.get("country")) == str(country)
                and f.dimensions.get("visa_class") == visa_class
            ],
            key=lambda x: x.publication_date,
            reverse=True,
        )

    if not rows:
        return []

    most_recent_pub = rows[0].publication_date
    cutoff_pub = most_recent_pub - timedelta(days=180)
    return [r for r in rows if r.publication_date >= cutoff_pub and r.publication_date == most_recent_pub]


def _get_i485_queue(
    visa_class: str, country: int, current_cutoff: date, knowledge_date: date, facts: list | None = None
) -> float:
    """Total pending I-485 applications within 3 years ahead of current cutoff.

    Uses reference_period_start as the priority date (how USCIS data is stored).
    """
    rows = _get_i485_rows_most_recent(visa_class, country, knowledge_date, facts)
    if not rows:
        return 0.0

    window_end = current_cutoff + timedelta(days=3 * 365)
    total = 0.0
    for r in rows:
        pd = r.reference_period_start
        if pd is None:
            continue
        if current_cutoff <= pd <= window_end:
            v = r.value
            try:
                total += float(v)
            except (TypeError, ValueError):
                pass
    return total


def _get_i485_density_near_cutoff(
    visa_class: str,
    country: int,
    current_cutoff: date,
    knowledge_date: date,
    window_years: int = 2,
    facts: list | None = None,
) -> float:
    """Fraction of pending I-485s with priority date within `window_years` ahead of cutoff.

    Low density (< 0.3) means DOS can advance quickly — few applicants are
    immediately ahead.  High density (> 0.7) means a backlog of applicants is
    just ahead of the cutoff, predicting slow or stalled advancement.

    Returns 0.5 (neutral) when data are unavailable or the total queue is zero.
    """
    rows = _get_i485_rows_most_recent(visa_class, country, knowledge_date, facts)
    if not rows:
        return 0.5

    window_end = current_cutoff + timedelta(days=window_years * 365)

    near_count = 0.0
    total_count = 0.0
    for r in rows:
        pd = r.reference_period_start
        if pd is None:
            continue
        v = r.value
        try:
            count = float(v)
        except (TypeError, ValueError):
            continue
        if count <= 0:
            continue
        total_count += count
        if current_cutoff <= pd <= window_end:
            near_count += count

    if total_count <= 0:
        return 0.5
    return near_count / total_count


def _get_utilization_rate(
    visa_class: str, country: int, knowledge_date: date, facts: list | None = None
) -> float:
    """Current FY utilization rate: cumulative issuance / annual allocation.

    Returns a value in [0, 1+]; >1 means oversubscription (can happen due to
    spillover). Returns 0.0 if no issuance data is available.
    """
    from lib.business.vqs.estimators import (
        DEFAULT_ANNUAL_EB_LIMIT,
        PER_CLASS_SHARE,
        PER_COUNTRY_SHARE,
    )
    from models.raw_facts import RawFactsLedger

    if facts is None:
        issuance_facts = list(
            RawFactsLedger.objects.filter(
                metric="visa_issuance_monthly",
                publication_date__lt=knowledge_date,
            )
        )
    else:
        issuance_facts = [f for f in facts if f.metric == "visa_issuance_monthly" and f.publication_date < knowledge_date]

    # Determine current FY
    fy = knowledge_date.year if knowledge_date.month >= 10 else knowledge_date.year - 1

    cumulative = 0.0
    fy_month_order = [10, 11, 12, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    months_to_include = set()
    for m in fy_month_order:
        months_to_include.add(m)
        if m == knowledge_date.month:
            break

    for f in issuance_facts:
        dims = f.dimensions if isinstance(f.dimensions, dict) else {}
        if str(dims.get("country")) != str(country):
            continue
        if str(dims.get("visa_class", "")) != str(visa_class):
            continue
        if not f.reference_period_start:
            continue
        rps = f.reference_period_start
        fact_fy = rps.year if rps.month >= 10 else rps.year - 1
        if fact_fy != fy:
            continue
        if rps.month not in months_to_include:
            continue
        v = f.value
        if isinstance(v, (list, tuple)) and v:
            v = v[0]
        try:
            cumulative += float(v)
        except (TypeError, ValueError):
            pass

    class_share = PER_CLASS_SHARE.get(visa_class, 0.286)
    annual_allocation = DEFAULT_ANNUAL_EB_LIMIT * PER_COUNTRY_SHARE * class_share
    if annual_allocation <= 0:
        return 0.0

    return cumulative / annual_allocation


def _get_cutoff_velocity_6m(
    visa_class: str, country: int, action_type: str, knowledge_date: date
) -> float:
    """6-month linear trend of cutoff: (current - 6m_ago).days / 6 days/month."""
    from lib.business.vqs.data_cache import get_cutoff_at_date

    cutoff_now = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    cutoff_6m_ago = get_cutoff_at_date(
        visa_class, country, action_type, knowledge_date - timedelta(days=182)
    )
    if cutoff_now is None or cutoff_6m_ago is None:
        return 0.0
    return (cutoff_now - cutoff_6m_ago).days / 6.0


def _get_eb1_surplus_indicator(
    country: int, action_type: str, knowledge_date: date
) -> float:
    """1 if EB-1 same country had Current status (no cutoff) in last 3 months, else 0.

    EB-1 going Current means surplus visas may spill over into EB-2/3.
    "Current" is represented as cutoff_date = None in the DB.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    for months_back in range(1, 4):
        check_date = knowledge_date - timedelta(days=30 * months_back)
        cutoff = get_cutoff_at_date("1st", country, action_type, check_date)
        if cutoff is None:
            return 1.0
    return 0.0


def _get_row_velocity(
    visa_class: str, action_type: str, knowledge_date: date, n: int = 3
) -> tuple[float, float, float]:
    """ROW (All Chargeability) same-class cutoff velocity.

    Returns (move_1m, move_avg_nm, is_current) where is_current=1.0 if the
    ROW cutoff is effectively "Current" (within 60 days of knowledge_date or NULL).
    This is the strongest community-used leading indicator for India/China: when
    ROW advances rapidly or goes Current, oversubscribed countries follow.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.seasonal_predictor import get_last_N_moves
    from models.enums.country import Country

    row_country = Country.ALL.value
    moves = get_last_N_moves(visa_class, row_country, action_type, knowledge_date, n)
    move_1m = float(moves[0]) if moves else 0.0
    move_avg = sum(float(m) for m in moves) / len(moves) if moves else 0.0

    row_cutoff = get_cutoff_at_date(visa_class, row_country, action_type, knowledge_date)
    is_current = 1.0 if (row_cutoff is None or (knowledge_date - row_cutoff).days <= 60) else 0.0

    return move_1m, move_avg, is_current


def _get_issuance_drop_ratio(
    visa_class: str, country: int, knowledge_date: date, facts: list | None = None
) -> float:
    """Ratio of recent visa issuance to same period last year.

    < 1.0 means issuance dropped (travel ban, consular closures, policy changes).
    This is a proxy for demand-drop events that the community uses to predict
    acceleration in cutoff dates for oversubscribed countries.
    Returns 1.0 if insufficient data.
    """
    from models.raw_facts import RawFactsLedger

    if facts is None:
        issuance_facts = list(
            RawFactsLedger.objects.filter(
                metric="visa_issuance_monthly",
                publication_date__lt=knowledge_date,
            )
        )
    else:
        issuance_facts = [f for f in facts if f.metric == "visa_issuance_monthly" and f.publication_date < knowledge_date]

    def _sum_period(facts_list, start_month: int, start_year: int, num_months: int = 3) -> float:
        total = 0.0
        target_months = set()
        y, m = start_year, start_month
        for _ in range(num_months):
            target_months.add((y, m))
            m -= 1
            if m == 0:
                m = 12
                y -= 1

        for f in facts_list:
            dims = f.dimensions if isinstance(f.dimensions, dict) else {}
            if str(dims.get("country")) != str(country):
                continue
            if not f.reference_period_start:
                continue
            rps = f.reference_period_start
            if (rps.year, rps.month) in target_months:
                v = f.value
                if isinstance(v, (list, tuple)) and v:
                    v = v[0]
                try:
                    total += float(v)
                except (TypeError, ValueError):
                    pass
        return total

    recent = _sum_period(issuance_facts, knowledge_date.month, knowledge_date.year, 3)
    prior_year = _sum_period(issuance_facts, knowledge_date.month, knowledge_date.year - 1, 3)

    if prior_year <= 0:
        return 1.0
    return recent / prior_year


def _build_features_for_series(
    visa_class: str,
    country: int,
    action_type: str,
    knowledge_date: date,
    facts: list | None = None,
) -> list[float] | None:
    """Build feature vector for one (series, knowledge_date).

    Returns None if insufficient data.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.seasonal_predictor import get_last_N_moves

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    moves = get_last_N_moves(visa_class, country, action_type, knowledge_date, 12)
    if len(moves) < 3:
        return None

    move_1m = float(moves[0]) if len(moves) >= 1 else 0.0
    move_2m = float(moves[1]) if len(moves) >= 2 else 0.0
    move_3m = float(moves[2]) if len(moves) >= 3 else 0.0
    move_6m_avg = sum(float(m) for m in moves[:6]) / min(6, len(moves))
    move_12m_avg = sum(float(m) for m in moves[:12]) / min(12, len(moves))

    # Cross-series: EB-1 same country signals
    eb1_move_1m = 0.0
    eb1_move_3m = 0.0
    eb1_regime_enc = 2.0  # default: stalled
    if visa_class != "1st":
        from lib.business.vqs.regime import Regime as _Regime
        from lib.business.vqs.regime import classify_regime as _classify_regime
        regime_enc = {
            _Regime.ADVANCING: 1.0, _Regime.STALLED: 2.0,
            _Regime.RETROGRESSING: 3.0, _Regime.RECOVERING: 4.0, _Regime.VOLATILE: 5.0,
        }
        eb1_moves = get_last_N_moves("1st", country, action_type, knowledge_date, 3)
        if eb1_moves:
            eb1_move_1m = float(eb1_moves[0])
            eb1_move_3m = sum(float(m) for m in eb1_moves) / len(eb1_moves)
            eb1_regime_enc = regime_enc.get(_classify_regime(eb1_moves).regime, 2.0)

    cutoff_age = (knowledge_date - current_cutoff).days

    i140_ratio = _get_i140_ratio(country, knowledge_date, facts)
    i485_queue = _get_i485_queue(visa_class, country, current_cutoff, knowledge_date, facts)

    # FY / timing features
    utilization = _get_utilization_rate(visa_class, country, knowledge_date, facts)
    months_into_fy = (knowledge_date.month - 10) % 12 + 1  # Oct=1 ... Sep=12
    demand_ratio_class = _get_i140_ratio_class(visa_class, country, knowledge_date, facts)
    cutoff_velocity_6m = _get_cutoff_velocity_6m(visa_class, country, action_type, knowledge_date)
    retro_distance_months = (10 - knowledge_date.month) % 12  # 0 in Oct, 11 in Nov
    eb1_surplus = _get_eb1_surplus_indicator(country, action_type, knowledge_date)

    # Demand-drop features (ROW velocity + issuance drop)
    row_move_1m, row_move_3m_avg, row_is_current = _get_row_velocity(visa_class, action_type, knowledge_date)
    issuance_drop = _get_issuance_drop_ratio(visa_class, country, knowledge_date, facts)

    # Queue density feature: fraction of pending I-485s near current cutoff
    i485_density = _get_i485_density_near_cutoff(visa_class, country, current_cutoff, knowledge_date, facts=facts)

    feats = [
        float(country),                          # 0: series_country
        float(_CLASS_ENCODING.get(visa_class, 0)),  # 1: series_class
        move_1m,                                 # 2
        move_2m,                                 # 3
        move_3m,                                 # 4
        move_6m_avg,                             # 5
        move_12m_avg,                            # 6
        float(knowledge_date.month),             # 7: month_of_year
        float(((knowledge_date.month) % 12) + 1 == 10),  # 8: is_next_fy_reset
        float(((knowledge_date.month) % 12) + 1 in (7, 8, 9)),  # 9: is_next_end_of_fy
        float(cutoff_age),                       # 10
        i140_ratio,                              # 11
        i485_queue,                              # 12
        eb1_move_1m,                             # 13
        eb1_move_3m,                             # 14
        eb1_regime_enc,                          # 15
        utilization,                             # 16
        float(months_into_fy),                   # 17
        demand_ratio_class,                      # 18
        cutoff_velocity_6m,                      # 19
        float(retro_distance_months),            # 20
        eb1_surplus,                             # 21
        row_move_1m,                             # 22: demand-drop: ROW last-month move
        row_move_3m_avg,                         # 23: demand-drop: ROW 3m avg move
        row_is_current,                          # 24: demand-drop: ROW cutoff is Current
        issuance_drop,                           # 25: demand-drop: issuance ratio vs prior year
        i485_density,                            # 26: queue density near cutoff
    ]

    # Zero demand-drop features for series where ROW velocity signal hurts accuracy.
    # Inference-only masking: training retains all features so the model learns the general
    # pattern; we simply don't let those features mislead deeply-backlogged series.
    if (country, visa_class) in _DEMAND_DROP_MASKED_SERIES:
        feats[22] = 0.0
        feats[23] = 0.0
        feats[24] = 0.0
        feats[25] = 0.0

    return feats


def _append_horizon_features(feats: list[float], horizon: int, knowledge_date: date) -> list[float]:
    """Append horizon-specific features to the base feature vector (for multi-horizon models)."""
    from dateutil.relativedelta import relativedelta
    target_date = knowledge_date + relativedelta(months=horizon)
    target_month_of_year = float(target_date.month)
    target_months_into_fy = float((target_date.month - 10) % 12 + 1)
    return feats + [
        float(horizon),             # 27: prediction horizon
        target_month_of_year,       # 27
        target_months_into_fy,      # 28
    ]


FEATURE_NAMES = [
    "series_country", "series_class",
    "move_1m", "move_2m", "move_3m", "move_6m_avg", "move_12m_avg",
    "month_of_year", "is_next_fy_reset", "is_next_end_of_fy",
    "cutoff_age_days", "i140_ratio", "i485_queue_size",
    "eb1_move_1m", "eb1_move_3m", "eb1_regime_state",
    "utilization_rate", "months_into_fy", "demand_ratio_class",
    "cutoff_velocity_6m", "retro_distance_months", "eb1_surplus_indicator",
    # Demand-drop signals (ROW velocity + issuance drop) — features 22-25
    "row_move_1m", "row_move_3m_avg", "row_is_current", "issuance_drop_ratio",
    # Index 26
    "i485_density_near_cutoff",
]

FEATURE_NAMES_HORIZON = FEATURE_NAMES + ["horizon", "target_month_of_year", "target_months_into_fy"]


def _build_training_data(
    knowledge_date: date,
    action_type: str = "filing",
) -> tuple[list[list[float]], list[float]] | None:
    """Build training (X, y) for 1-month horizon, all series up to knowledge_date.

    y = next-month actual movement (days).
    """
    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from models.raw_facts import RawFactsLedger

    bulletins = [b for b in get_all_bulletins() if b.publication_date < knowledge_date]
    if len(bulletins) < _MIN_TRAINING_SAMPLES // 6:
        return None

    facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))

    x: list[list[float]] = []
    y: list[float] = []

    for bulletin in bulletins:
        kd = bulletin.publication_date - timedelta(days=1)
        next_bulletins = [b for b in get_all_bulletins() if b.publication_date > bulletin.publication_date]
        if not next_bulletins:
            continue
        next_b = next_bulletins[0]

        for country, vc in _GBM_ELIGIBLE:
            current = get_cutoff_at_date(vc, country, action_type, kd)
            next_cutoff = get_cutoff_at_date(vc, country, action_type, next_b.publication_date)
            if current is None or next_cutoff is None:
                continue

            actual_move = (next_cutoff - current).days
            kd_facts = [f for f in facts if f.publication_date <= kd]
            feats = _build_features_for_series(vc, country, action_type, kd, kd_facts)
            if feats is None:
                continue

            x.append(feats)
            y.append(float(actual_move))

    if len(x) < _MIN_TRAINING_SAMPLES:
        return None
    return x, y


def _build_training_data_horizon(
    knowledge_date: date,
    horizon: int,
    action_type: str = "filing",
) -> tuple[list[list[float]], list[float]] | None:
    """Build training (X, y) for direct h-month prediction.

    y = cumulative cutoff movement from kd to kd+h months (days).
    Features include horizon-specific columns appended to base features.
    """
    from dateutil.relativedelta import relativedelta

    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from models.raw_facts import RawFactsLedger

    bulletins = [b for b in get_all_bulletins() if b.publication_date < knowledge_date]
    if len(bulletins) < _MIN_TRAINING_SAMPLES // 6:
        return None

    facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))

    x: list[list[float]] = []
    y: list[float] = []

    for bulletin in bulletins:
        kd = bulletin.publication_date - timedelta(days=1)
        target_kd = kd + relativedelta(months=horizon)
        # Need bulletin at target time
        target_bulletins = [
            b for b in get_all_bulletins()
            if b.publication_date >= target_kd - timedelta(days=35)
            and b.publication_date <= target_kd + timedelta(days=35)
        ]
        if not target_bulletins:
            continue
        target_b = min(target_bulletins, key=lambda b: abs((b.publication_date - target_kd).days))

        for country, vc in _GBM_ELIGIBLE:
            current = get_cutoff_at_date(vc, country, action_type, kd)
            target_cutoff = get_cutoff_at_date(vc, country, action_type, target_b.publication_date)
            if current is None or target_cutoff is None:
                continue

            actual_move = (target_cutoff - current).days
            kd_facts = [f for f in facts if f.publication_date <= kd]
            feats = _build_features_for_series(vc, country, action_type, kd, kd_facts)
            if feats is None:
                continue

            feats_h = _append_horizon_features(feats, horizon, kd)
            x.append(feats_h)
            y.append(float(actual_move))

    if len(x) < _MIN_TRAINING_SAMPLES:
        return None
    return x, y


def _build_training_data_classifier(
    knowledge_date: date,
    horizon: int,
    movement_threshold: int = 30,
    action_type: str = "filing",
) -> tuple[list[list[float]], list[float]] | None:
    """Build classification training data: y = 1 if |cumulative_move| > threshold."""
    data = _build_training_data_horizon(knowledge_date, horizon, action_type)
    if data is None:
        return None
    x, y_reg = data
    y_cls = [1.0 if abs(move) > movement_threshold else 0.0 for move in y_reg]
    return x, y_cls


def _get_or_train_model(knowledge_date: date, action_type: str = "filing") -> object | None:
    """Get or train the 1-month regression model."""
    cache_key = ("reg1m", knowledge_date.year, knowledge_date.month)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    try:
        import lightgbm as lgb
    except ImportError:
        logger.warning("lightgbm not installed; GBM expert unavailable")
        return None

    data = _build_training_data(knowledge_date, action_type)
    if data is None:
        logger.debug("Insufficient training data for GBM at %s", knowledge_date)
        return None

    x, y = data
    import numpy as np

    x_arr = np.array(x, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    model = lgb.LGBMRegressor(
        n_estimators=_GBM_N_ESTIMATORS,
        max_depth=_GBM_MAX_DEPTH,
        num_leaves=_GBM_NUM_LEAVES,
        learning_rate=_GBM_LEARNING_RATE,
        min_child_samples=_GBM_MIN_CHILD_SAMPLES,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=_GBM_REG_ALPHA,
        reg_lambda=_GBM_REG_LAMBDA,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_arr, y_arr)
    _model_cache[cache_key] = model
    logger.debug("Trained GBM 1m model at %s on %d samples", knowledge_date, len(x))
    return model


def _get_or_train_model_horizon(
    knowledge_date: date, horizon: int, action_type: str = "filing"
) -> object | None:
    """Get or train a direct h-month regression model."""
    cache_key = ("direct", knowledge_date.year, knowledge_date.month, horizon)
    if cache_key in _model_cache:
        return _model_cache[cache_key]

    try:
        import lightgbm as lgb
    except ImportError:
        logger.warning("lightgbm not installed; GBM expert unavailable")
        return None

    data = _build_training_data_horizon(knowledge_date, horizon, action_type)
    if data is None:
        logger.debug("Insufficient training data for GBM %dm model at %s", horizon, knowledge_date)
        return None

    x, y = data
    import numpy as np

    x_arr = np.array(x, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    model = lgb.LGBMRegressor(
        n_estimators=_GBM_N_ESTIMATORS,
        max_depth=_GBM_MAX_DEPTH,
        num_leaves=_GBM_NUM_LEAVES,
        learning_rate=_GBM_LEARNING_RATE,
        min_child_samples=_GBM_MIN_CHILD_SAMPLES,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=_GBM_REG_ALPHA,
        reg_lambda=_GBM_REG_LAMBDA,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_arr, y_arr)
    _model_cache[cache_key] = model
    logger.debug("Trained GBM direct %dm model at %s on %d samples", horizon, knowledge_date, len(x))
    return model


def _get_or_train_classifier(
    knowledge_date: date, horizon: int, movement_threshold: int = 30, action_type: str = "filing"
) -> object | None:
    """Get or train a binary classifier for P(|move| > movement_threshold)."""
    cache_key = ("clf", knowledge_date.year, knowledge_date.month, horizon, movement_threshold)
    if cache_key in _classifier_cache:
        return _classifier_cache[cache_key]

    try:
        import lightgbm as lgb
    except ImportError:
        return None

    data = _build_training_data_classifier(knowledge_date, horizon, movement_threshold, action_type)
    if data is None:
        return None

    x, y = data
    import numpy as np

    x_arr = np.array(x, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    n_pos = int(sum(y_arr))
    n_neg = len(y_arr) - n_pos
    if n_pos < 5 or n_neg < 5:
        return None

    model = lgb.LGBMClassifier(
        n_estimators=_GBM_N_ESTIMATORS,
        max_depth=_GBM_MAX_DEPTH,
        num_leaves=_GBM_NUM_LEAVES,
        learning_rate=_GBM_LEARNING_RATE,
        min_child_samples=_GBM_MIN_CHILD_SAMPLES,
        subsample=0.8,
        colsample_bytree=0.8,
        is_unbalance=True,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_arr, y_arr)
    _classifier_cache[cache_key] = model
    logger.debug(
        "Trained GBM classifier %dm threshold=%dd at %s on %d samples (%d pos)",
        horizon, movement_threshold, knowledge_date, len(x), n_pos,
    )
    return model


def _get_or_train_quantile(
    knowledge_date: date, horizon: int, alpha: float, action_type: str = "filing"
) -> object | None:
    """Get or train a quantile regression GBM (alpha = 0.1 or 0.9)."""
    alpha_key = int(alpha * 100)
    cache_key = ("quantile", knowledge_date.year, knowledge_date.month, horizon, alpha_key)
    if cache_key in _quantile_cache:
        return _quantile_cache[cache_key]

    try:
        import lightgbm as lgb
    except ImportError:
        return None

    data = _build_training_data_horizon(knowledge_date, horizon, action_type) if horizon > 1 \
        else _build_training_data(knowledge_date, action_type)
    if data is None:
        return None

    x, y = data
    import numpy as np

    x_arr = np.array(x, dtype=np.float32)
    y_arr = np.array(y, dtype=np.float32)

    model = lgb.LGBMRegressor(
        objective="quantile",
        alpha=alpha,
        n_estimators=_GBM_N_ESTIMATORS,
        max_depth=_GBM_MAX_DEPTH,
        num_leaves=_GBM_NUM_LEAVES,
        learning_rate=_GBM_LEARNING_RATE,
        min_child_samples=_GBM_MIN_CHILD_SAMPLES,
        subsample=0.8,
        colsample_bytree=0.8,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_arr, y_arr)
    _quantile_cache[cache_key] = model
    logger.debug("Trained GBM quantile alpha=%.2f %dm at %s", alpha, horizon, knowledge_date)
    return model


def _seasonal_median_fallback(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """Standalone seasonal median prediction without importing from expert_pool."""
    from lib.business.vqs.data_cache import get_cutoff_at_date
    from lib.business.vqs.seasonal_predictor import get_seasonal_prediction

    current = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current:
        return None
    target_month = (knowledge_date.month % 12) + 1
    move = get_seasonal_prediction(
        visa_class, country, action_type,
        knowledge_date=knowledge_date, target_month=target_month, min_samples=3,
    )
    if move is None:
        return current
    return current + timedelta(days=move)


def expert_gbm(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, facts: list | None = None,
) -> date | None:
    """GBM expert: 1-month regression. Used as ensemble member in the solver.

    Falls back to seasonal_median when training data is insufficient.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    if (country, visa_class) not in _GBM_ELIGIBLE:
        return get_cutoff_at_date(visa_class, country, action_type, knowledge_date)

    feats = _build_features_for_series(visa_class, country, action_type, knowledge_date, facts)
    if feats is None:
        return _seasonal_median_fallback(visa_class, country, action_type, knowledge_date, facts)

    model = _get_or_train_model(knowledge_date, action_type)
    if model is None:
        return _seasonal_median_fallback(visa_class, country, action_type, knowledge_date, facts)

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    import numpy as np
    x = np.array([feats], dtype=np.float32)
    predicted_move = float(model.predict(x)[0])
    predicted_move = max(-90.0, min(365.0, predicted_move))
    return current_cutoff + timedelta(days=int(predicted_move))


def expert_gbm_direct(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, horizon: int, facts: list | None = None,
) -> date | None:
    """Direct multi-horizon GBM: trained separately per horizon.

    Unlike iterated 1-step approach, each horizon (1m/3m/6m/12m) has its own
    model trained to predict cumulative movement over that many months directly.
    Avoids error compounding from iterating a 1-month model.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    if (country, visa_class) not in _GBM_ELIGIBLE:
        return get_cutoff_at_date(visa_class, country, action_type, knowledge_date)

    feats = _build_features_for_series(visa_class, country, action_type, knowledge_date, facts)
    if feats is None:
        return _seasonal_median_fallback(visa_class, country, action_type, knowledge_date, facts)

    feats_h = _append_horizon_features(feats, horizon, knowledge_date)

    model = _get_or_train_model_horizon(knowledge_date, horizon, action_type)
    if model is None:
        # Fall back to iterated 1-step for the requested horizon
        return _iterated_gbm(visa_class, country, action_type, knowledge_date, horizon, feats, facts)

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    import numpy as np
    x = np.array([feats_h], dtype=np.float32)
    predicted_move = float(model.predict(x)[0])
    predicted_move = max(-180.0, min(horizon * 365.0, predicted_move))
    return current_cutoff + timedelta(days=int(predicted_move))


def _iterated_gbm(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, horizon: int,
    base_feats: list[float], facts: list | None = None,
) -> date | None:
    """Fallback: iterate the 1-month GBM model h times for h-month prediction."""
    from lib.business.vqs.data_cache import get_cutoff_at_date

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    model = _get_or_train_model(knowledge_date, action_type)
    if model is None:
        return None

    import numpy as np
    x = np.array([base_feats], dtype=np.float32)
    total_move = 0
    for _ in range(horizon):
        move = float(model.predict(x)[0])
        move = max(-90.0, min(365.0, move))
        total_move += int(move)

    return current_cutoff + timedelta(days=total_move)


def expert_gbm_movement_prob(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, horizon: int = 1,
    movement_threshold: int = _GBM_DEFAULT_MOVEMENT_THRESHOLD, facts: list | None = None,
) -> float:
    """Returns P(|cutoff_move| > movement_threshold) over horizon months.

    Used by expert_gbm_gated to gate the regression prediction.
    Returns 0.5 (uncertain) when classifier not available.
    """
    if (country, visa_class) not in _GBM_ELIGIBLE:
        return 0.5

    feats = _build_features_for_series(visa_class, country, action_type, knowledge_date, facts)
    if feats is None:
        return 0.5

    feats_h = _append_horizon_features(feats, horizon, knowledge_date)
    model = _get_or_train_classifier(knowledge_date, horizon, movement_threshold, action_type)
    if model is None:
        return 0.5

    import numpy as np
    x = np.array([feats_h], dtype=np.float32)
    probs = model.predict_proba(x)[0]
    # probs[1] = P(class=1) = P(|move| > threshold)
    return float(probs[1]) if len(probs) > 1 else 0.5


def expert_gbm_gated(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, horizon: int = 1,
    movement_threshold: int = _GBM_DEFAULT_MOVEMENT_THRESHOLD,
    gate_threshold: float = _GBM_DEFAULT_GATE_THRESHOLD,
    facts: list | None = None,
) -> date | None:
    """GBM Gated: uses movement classifier to decide when to predict non-persistence.

    When P(|move| > threshold) >= gate_threshold, returns direct GBM regression.
    Otherwise returns persistence (no change). Replaces hardcoded stickiness.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    prob = expert_gbm_movement_prob(
        visa_class, country, action_type, knowledge_date, horizon, movement_threshold, facts
    )

    if prob < gate_threshold:
        return current_cutoff  # persistence

    return expert_gbm_direct(
        visa_class, country, action_type, knowledge_date, horizon, facts
    )


def expert_gbm_quantile(
    visa_class: str, country: int, action_type: str,
    knowledge_date: date, horizon: int, alpha: float, facts: list | None = None,
) -> date | None:
    """Quantile regression GBM: returns alpha-th percentile prediction.

    Use alpha=0.10 for lower bound (10th pct), alpha=0.90 for upper bound (90th pct).
    These form model-native prediction intervals as alternatives to calibration.py.
    """
    from lib.business.vqs.data_cache import get_cutoff_at_date

    if (country, visa_class) not in _GBM_ELIGIBLE:
        return None

    feats = _build_features_for_series(visa_class, country, action_type, knowledge_date, facts)
    if feats is None:
        return None

    x_feats = _append_horizon_features(feats, horizon, knowledge_date) if horizon > 1 else feats

    model = _get_or_train_quantile(knowledge_date, horizon, alpha, action_type)
    if model is None:
        return None

    current_cutoff = get_cutoff_at_date(visa_class, country, action_type, knowledge_date)
    if not current_cutoff:
        return None

    import numpy as np
    x = np.array([x_feats], dtype=np.float32)
    predicted_move = float(model.predict(x)[0])
    return current_cutoff + timedelta(days=int(predicted_move))
