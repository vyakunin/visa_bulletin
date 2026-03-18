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
  and I-140 receipt trends, which other experts do not combine simultaneously.

Features per (series, knowledge_date):
  - series_country: India=3, China=2
  - series_class: 1st=1, 2nd=2, 3rd=3
  - move_1m, move_2m, move_3m: recent monthly movements (days)
  - move_6m_avg, move_12m_avg: trailing average movements
  - month_of_year: 1-12 (seasonal)
  - is_fy_reset: 1 if October, 0 otherwise
  - is_end_of_fy: 1 if July/August/September
  - cutoff_age_days: days from current cutoff to knowledge_date (backlog proxy)
  - i140_ratio: recent 2 quarters I-140 vs historical baseline (demand signal)
  - i485_queue_size: pending I-485 applications within 3-year window
  - eb1_same_country_move_1m: last move of EB-1 for same country (cross-series)

Target: next-month cutoff movement in days (regression)
"""

import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Minimum training samples before GBM is used; below this, falls back to seasonal_median
_MIN_TRAINING_SAMPLES = 36

# Countries and classes eligible for GBM (same as physics-eligible series)
_GBM_ELIGIBLE = frozenset([
    (2, "2nd"), (2, "3rd"), (2, "1st"),  # China EB-1/2/3
    (3, "2nd"), (3, "3rd"), (3, "1st"),  # India EB-1/2/3
])

# Series class encoding for features
_CLASS_ENCODING = {"1st": 1, "2nd": 2, "3rd": 3}

# Cache: (year, month) -> trained LightGBM model
_model_cache: dict[tuple[int, int], object] = {}
_feature_matrix_cache: dict[tuple[int, int], tuple] = {}


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


def _get_i485_queue(visa_class: str, country: int, current_cutoff: date, knowledge_date: date, facts: list | None = None) -> float:
    """Total I-485 pending applications within 3 years ahead of current cutoff."""
    from datetime import datetime

    from models.raw_facts import RawFactsLedger

    if facts is None:
        rows = list(
            RawFactsLedger.objects.filter(
                metric="i485_pending_inventory",
                publication_date__lte=knowledge_date,
            ).order_by("-publication_date")
        )
    else:
        rows = sorted(
            [f for f in facts if f.metric == "i485_pending_inventory" and f.publication_date <= knowledge_date],
            key=lambda x: x.publication_date, reverse=True,
        )

    if not rows:
        return 0.0

    window_end = current_cutoff + timedelta(days=3 * 365)
    most_recent = rows[0].publication_date
    total = 0.0

    for r in rows:
        if r.publication_date < most_recent - timedelta(days=120):
            break
        dims = r.dimensions if isinstance(r.dimensions, dict) else {}
        if str(dims.get("country", "")) != str(country):
            continue
        if dims.get("visa_class") and dims["visa_class"] != visa_class:
            continue
        pd_str = dims.get("priority_date", "")
        if not pd_str:
            continue
        try:
            for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
                try:
                    f_pd = datetime.strptime(pd_str, fmt).date()
                    break
                except ValueError:
                    continue
            else:
                continue
        except Exception:
            continue

        if current_cutoff <= f_pd <= window_end:
            v = r.value
            if isinstance(v, (list, tuple)) and v:
                v = v[0]
            try:
                total += float(v)
            except (TypeError, ValueError):
                pass

    return total


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

    return [
        float(country),                        # series_country (India=3, China=2)
        float(_CLASS_ENCODING.get(visa_class, 0)),  # series_class
        move_1m,
        move_2m,
        move_3m,
        move_6m_avg,
        move_12m_avg,
        float(knowledge_date.month),           # month_of_year
        float(((knowledge_date.month) % 12) + 1 == 10),  # is_next_fy_reset
        float(((knowledge_date.month) % 12) + 1 in (7, 8, 9)),  # is_next_end_of_fy
        float(cutoff_age),
        i140_ratio,
        i485_queue,
        eb1_move_1m,                           # cross-series: EB-1 last month move
        eb1_move_3m,                           # cross-series: EB-1 3-month average
        eb1_regime_enc,                        # cross-series: EB-1 regime (1=adv..5=vol)
    ]


FEATURE_NAMES = [
    "series_country", "series_class",
    "move_1m", "move_2m", "move_3m", "move_6m_avg", "move_12m_avg",
    "month_of_year", "is_next_fy_reset", "is_next_end_of_fy",
    "cutoff_age_days", "i140_ratio", "i485_queue_size",
    "eb1_move_1m", "eb1_move_3m", "eb1_regime_state",
]


def _build_training_data(
    knowledge_date: date,
    action_type: str = "filing",
) -> tuple[list[list[float]], list[float]] | None:
    """Build training (X, y) for all series up to knowledge_date.

    y = next-month actual movement (days).
    Returns None if insufficient data.
    """
    from lib.business.vqs.data_cache import get_all_bulletins, get_cutoff_at_date
    from models.raw_facts import RawFactsLedger

    bulletins = [b for b in get_all_bulletins() if b.publication_date < knowledge_date]
    if len(bulletins) < _MIN_TRAINING_SAMPLES // 6:
        return None

    # Preload facts once
    facts = list(RawFactsLedger.objects.filter(publication_date__lte=knowledge_date))

    x: list[list[float]] = []
    y: list[float] = []

    for bulletin in bulletins:
        kd = bulletin.publication_date - timedelta(days=1)
        # Find the actual next-month cutoff (what happened next)
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


def _get_or_train_model(knowledge_date: date, action_type: str = "filing") -> object | None:
    """Get cached model or train a new one for this knowledge_date month."""
    cache_key = (knowledge_date.year, knowledge_date.month)
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

    # LightGBM with conservative settings to avoid overfitting on ~120-720 samples
    model = lgb.LGBMRegressor(
        n_estimators=100,
        max_depth=4,
        num_leaves=15,
        learning_rate=0.05,
        min_child_samples=5,
        subsample=0.8,
        colsample_bytree=0.8,
        reg_alpha=1.0,
        reg_lambda=1.0,
        random_state=42,
        verbose=-1,
    )
    model.fit(x_arr, y_arr)
    _model_cache[cache_key] = model
    logger.debug("Trained GBM model at %s on %d samples", knowledge_date, len(x))
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
    """GBM expert: gradient-boosted tree trained on historical tabular features.

    Combines I-140 demand, I-485 inventory, cross-series EB-1 signal,
    seasonal features, and recent momentum into a single non-linear model.
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

    # Sanity bounds: cap predicted move between -90 and +365 days
    predicted_move = max(-90.0, min(365.0, predicted_move))

    return current_cutoff + timedelta(days=int(predicted_move))
