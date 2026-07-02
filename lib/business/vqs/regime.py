"""Regime detection for VQS predictions.

Classifies the current state of a visa series (advancing, stalled,
retrogressing, recovering, volatile) from recent cutoff movements.
Also provides FY-phase-aware regime detection that overrides the
backward-looking regime at fiscal year boundaries.

All functions are pure (no DB access) for testability.
The caller fetches moves via get_last_N_moves() and passes them here.
"""

import enum
from dataclasses import dataclass
from datetime import date, timedelta


class Regime(enum.Enum):
    ADVANCING = "advancing"
    STALLED = "stalled"
    RETROGRESSING = "retrogressing"
    RECOVERING = "recovering"
    VOLATILE = "volatile"


class FYPhase(enum.Enum):
    """Fiscal year phase for FY-aware regime detection."""
    FY_RESET = "fy_reset"
    CONSERVATIVE = "conservative"
    ACCELERATION = "acceleration"
    END_OF_FY = "end_of_fy"
    NORMAL = "normal"


@dataclass(frozen=True)
class RegimeState:
    regime: Regime
    confidence: float
    avg_move: float
    volatility: float
    fy_phase: FYPhase = FYPhase.NORMAL


STALL_THRESHOLD = 5.0
RETRO_THRESHOLD = -5.0
VOLATILE_CV = 2.0


def classify_regime(moves: list[int], lookback: int = 6) -> RegimeState:
    """Classify regime from recent monthly moves (days).

    Args:
        moves: Recent monthly cutoff movements in days. Most recent first.
               Positive = forward, negative = retrogression.
        lookback: Number of months to consider.

    Returns:
        RegimeState with classification and confidence.
    """
    if not moves:
        return RegimeState(Regime.STALLED, 0.0, 0.0, 0.0)

    recent = moves[:lookback]
    n = len(recent)

    avg = sum(recent) / n
    variance = sum((m - avg) ** 2 for m in recent) / n if n > 1 else 0.0
    vol = variance ** 0.5

    # Check for recovery: older moves negative, recent moves positive
    if n >= 4:
        split = n // 2
        recent_half = recent[:split]
        older_half = recent[split:]
        recent_avg = sum(recent_half) / len(recent_half)
        older_avg = sum(older_half) / len(older_half)

        if older_avg < RETRO_THRESHOLD and recent_avg > STALL_THRESHOLD:
            confidence = min(1.0, recent_avg / 20.0)
            return RegimeState(Regime.RECOVERING, confidence, avg, vol)

    avg_abs = sum(abs(m) for m in recent) / n
    cv = vol / avg_abs if avg_abs > STALL_THRESHOLD else 0.0

    if cv > VOLATILE_CV and avg_abs > STALL_THRESHOLD:
        return RegimeState(Regime.VOLATILE, min(1.0, cv / 3.0), avg, vol)

    if avg < RETRO_THRESHOLD:
        confidence = min(1.0, abs(avg) / 30.0)
        return RegimeState(Regime.RETROGRESSING, confidence, avg, vol)

    if avg > STALL_THRESHOLD:
        confidence = min(1.0, avg / 30.0)
        return RegimeState(Regime.ADVANCING, confidence, avg, vol)

    return RegimeState(
        Regime.STALLED, max(0.0, 1.0 - avg_abs / STALL_THRESHOLD), avg, vol
    )


def detect_regime_shift(moves: list[int]) -> bool:
    """Detect if a regime shift occurred recently.

    Compares recent 3-month average to prior 3-month average.
    Shift detected if sign changed or magnitude changed >2x.
    """
    if len(moves) < 6:
        return False

    recent_3 = moves[:3]
    prior_3 = moves[3:6]

    recent_avg = sum(recent_3) / 3
    prior_avg = sum(prior_3) / 3

    if (recent_avg > STALL_THRESHOLD and prior_avg < RETRO_THRESHOLD) or (
        recent_avg < RETRO_THRESHOLD and prior_avg > STALL_THRESHOLD
    ):
        return True

    if abs(prior_avg) > STALL_THRESHOLD:
        ratio = abs(recent_avg) / abs(prior_avg)
        if ratio > 2.0 or ratio < 0.5:
            return True

    return False


def regime_persistence_weight(regime: RegimeState) -> float:
    """Persistence weight based on regime + volatility. Higher = more conservative.

    Base weights per regime, then scaled up by volatility.
    High-volatility series get pushed toward persistence regardless of regime.
    """
    base_weights = {
        Regime.ADVANCING: 0.35,
        Regime.STALLED: 0.80,
        Regime.RETROGRESSING: 0.85,
        Regime.RECOVERING: 0.35,
        Regime.VOLATILE: 0.90,
    }
    base = base_weights[regime.regime]

    # Scale toward persistence with volatility.
    # vol=0 → no adjustment. vol=30 → add ~0.2. vol=80 → add ~0.4.
    if regime.volatility > 0:
        vol_boost = min(0.5, regime.volatility / 100.0 * 0.5)
        return min(0.95, base + vol_boost)
    return base


def regime_stickiness_days(regime: RegimeState) -> int:
    """Stickiness threshold based on regime."""
    stickiness = {
        Regime.ADVANCING: 0,
        Regime.STALLED: 90,
        Regime.RETROGRESSING: 60,
        Regime.RECOVERING: 15,
        Regime.VOLATILE: 45,
    }
    return stickiness[regime.regime]


def shrink_prediction(delta_days: int, regime: RegimeState) -> int:
    """Non-linear shrinkage that preserves direction while dampening magnitude.

    Small moves pass through largely unchanged (direction signal).
    Large moves get aggressively dampened (overshooting prevention).

    The shrinkage is modulated by regime: volatile/stalled regimes
    shrink more, advancing regimes shrink less.
    """
    if delta_days == 0:
        return 0

    sign = 1 if delta_days > 0 else -1
    abs_delta = abs(delta_days)

    # Piecewise shrinkage: small (0-25d), medium (25-80d), large (>80d)
    shrink_factors = {
        Regime.ADVANCING: (0.85, 0.60, 0.30),
        Regime.STALLED: (0.30, 0.15, 0.05),
        Regime.RETROGRESSING: (0.40, 0.20, 0.08),
        Regime.RECOVERING: (0.80, 0.50, 0.25),
        Regime.VOLATILE: (0.20, 0.10, 0.03),
    }
    small_f, med_f, large_f = shrink_factors[regime.regime]

    if abs_delta <= 25:
        return sign * int(abs_delta * small_f)
    elif abs_delta <= 80:
        base = int(25 * small_f)
        extra = int((abs_delta - 25) * med_f)
        return sign * (base + extra)
    else:
        base = int(25 * small_f) + int(55 * med_f)
        extra = int((abs_delta - 80) * large_f)
        return sign * (base + extra)


DEMAND_GATE_MIN_MOVE = 25  # demand_signal must imply >= this to fire the gate


def apply_demand_gate(
    expert_name: str,
    predicted_cutoff: date | None,
    current_cutoff: date | None,
    demand_pred: date | None,
    regime: RegimeState,
    *,
    gate_min: int = DEMAND_GATE_MIN_MOVE,
) -> tuple[date | None, str, str]:
    """Two-stage direction gate on a persistence fallback (T3, shipped 2026-07).

    When the regime selector falls back to ``persistence`` (STALLED / RETRO /
    VOLATILE) it predicts "no move" and scores 0% direction. If the
    ``demand_signal`` expert implies a meaningful move (>= ``gate_min`` days),
    replace the flat persistence date with a DAMPENED directional move
    (``shrink_prediction``) so we gain direction without the overshoot that made
    a raw seasonal/demand swap regress MAE (the §8 / T2 failure mode). The gate
    only ever ADDS a move on top of persistence; it never suppresses one.

    Pure: the caller fetches ``demand_pred`` (DB-backed) and passes it in.

    Returns ``(predicted_cutoff, expert_name, traj_expert)``:
      * fired  -> (persistence-date + shrunk move, "demand_gate", "persistence")
      * no-op  -> (predicted_cutoff, expert_name, expert_name)  [unchanged]

    ``traj_expert`` is the expert whose multi-step trajectory the caller should
    use; when the gate fires it stays ``persistence`` (the gate is a one-step
    nudge on top of persistence), so multi-step / maturity callers don't get a
    truncated forecast from an expert with no registered trajectory.
    """
    if (
        expert_name != "persistence"
        or predicted_cutoff is None
        or current_cutoff is None
        or demand_pred is None
    ):
        return predicted_cutoff, expert_name, expert_name
    demand_move = (demand_pred - current_cutoff).days
    if abs(demand_move) < gate_min:
        return predicted_cutoff, expert_name, expert_name
    shrunk = shrink_prediction(demand_move, regime)
    return current_cutoff + timedelta(days=int(shrunk)), "demand_gate", "persistence"


def regime_learning_rate(regime: RegimeState, base_lr: float = 0.5) -> float:
    """Aggregator learning rate based on regime.

    Higher LR during transitions for faster adaptation.
    """
    multipliers = {
        Regime.ADVANCING: 0.8,
        Regime.STALLED: 0.5,
        Regime.RETROGRESSING: 1.2,
        Regime.RECOVERING: 1.5,
        Regime.VOLATILE: 1.0,
    }
    return base_lr * multipliers[regime.regime]


# --- FY-Phase-Aware Regime Detection ---


def get_fy_phase(target_month: int) -> FYPhase:
    """Determine fiscal year phase from the target bulletin month.

    Args:
        target_month: Month of the bulletin being predicted (1-12).
    """
    if target_month == 10:
        return FYPhase.FY_RESET
    elif target_month in (11, 12, 1, 2, 3):
        return FYPhase.CONSERVATIVE
    elif target_month in (4, 5, 6):
        return FYPhase.ACCELERATION
    elif target_month in (7, 8, 9):
        return FYPhase.END_OF_FY
    return FYPhase.NORMAL


def classify_regime_fy_aware(
    moves: list[int],
    target_month: int,
    lookback: int = 6,
) -> RegimeState:
    """Classify regime with FY phase awareness.

    Uses the standard backward-looking regime as a base, then overlays
    the FY phase to produce a state that is both retrospective and prospective.

    At FY boundaries (target_month 8, 9, 10), the FY phase takes priority
    over the backward-looking regime for determining persistence weight
    and stickiness.
    """
    base_state = classify_regime(moves, lookback)
    fy_phase = get_fy_phase(target_month)
    return RegimeState(
        regime=base_state.regime,
        confidence=base_state.confidence,
        avg_move=base_state.avg_move,
        volatility=base_state.volatility,
        fy_phase=fy_phase,
    )


def fy_aware_persistence_weight(regime: RegimeState) -> float:
    """Persistence weight that respects FY phase.

    At FY boundaries, big moves are structural (not noise), so persistence
    damping is reduced. During normal months, uses the standard regime-based
    persistence weight.
    """
    if regime.fy_phase == FYPhase.FY_RESET:
        return 0.05
    elif regime.fy_phase == FYPhase.END_OF_FY:
        return 0.15
    return regime_persistence_weight(regime)


def fy_aware_stickiness_days(regime: RegimeState) -> int:
    """Stickiness threshold that respects FY phase.

    At FY boundaries, no stickiness (allow the model to express big moves).
    """
    if regime.fy_phase in (FYPhase.FY_RESET, FYPhase.END_OF_FY):
        return 0
    return regime_stickiness_days(regime)


def fy_aware_cap_forward_days(regime: RegimeState, base_cap: int = 45) -> int:
    """Forward cap that respects FY phase.

    At FY reset (October), allow massive forward jumps.
    """
    if regime.fy_phase == FYPhase.FY_RESET:
        return 1500
    return base_cap


def fy_aware_cap_back_days(regime: RegimeState, base_cap: int = 60) -> int:
    """Backward cap that respects FY phase.

    At end of FY (Aug/Sep), allow significant retrogression.
    """
    if regime.fy_phase == FYPhase.END_OF_FY:
        return 500
    if regime.fy_phase == FYPhase.FY_RESET:
        return 1500
    return base_cap
