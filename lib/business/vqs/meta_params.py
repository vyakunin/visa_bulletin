"""VQS Meta-Parameters holder and logic.

Defines the VqsMetaParams dataclass which holds all tunable parameters for the VQS solver,
and implements the post-step prediction shaping logic (stickiness, caps, blend).
"""

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any


@dataclass(frozen=True)
class VqsMetaParams:
    """
    Tunable meta-parameters for VQS solver.

    Categories:
    1. Physical (Solver/Physics): confidence thresholds, lookback windows, supply scales.
       Tune these to match trends (historical signal).
    2. Control (Post-step): stickiness, caps, blends.
       Tune these to dampen volatility and noise.
    """

    # --- 1. Physical Params (Solver/Physics) ---

    # Minimum I-140 rows to consider confidence "high"
    confidence_high_i140_min: int = 10

    # Lookback window (months) for historical advancement rate
    lookback_months_default: int = 24
    # EB1 India uses longer lookback: its advancement rate is noisy due to premium
    # processing spikes. 36m gives a more stable estimate than 24m.
    lookback_months_eb1_india: int = 36

    # Recency weight for advancement rate: blend of recent (last 6 months) vs full lookback
    # 0.0 = use only full lookback average, 1.0 = use only recent 6 months
    # Higher values make the model more responsive to trend changes
    advancement_rate_recency_weight: float = 0.6

    # Minimum number of Sept->Oct transitions to compute retrogression
    min_retrogression_transitions: int = 3

    # Supply and Demand scaling (Phase 2 physical params)
    # Optimized in Phase 7A Stage 1 (0.8 was robust across 2021-2025)
    supply_scale_multiplier: float = 0.8
    demand_lag_scale: float = 1.0  # Application to demand lag not yet implemented
    # Mar 2026: increased from 0.15 to 0.20 to reduce early-FY under-prediction bias.
    # Mirror of SPILLOVER_BONUS_RATE in estimators.py; used in Optuna tuning.
    spillover_bonus_rate: float = 0.20

    # --- 2. Control Params (Post-step Shaping) ---

    # "Stickiness": If raw prediction moves <= this many days, force No Change.
    # Base stickiness (used when regime-based is disabled or rate unknown)
    stickiness_days: int = 1

    # Regime-based stickiness: adapt based on advancement rate
    # If advancement_rate > stickiness_fast_threshold: use stickiness_fast_days
    # If advancement_rate < stickiness_stall_threshold: use stickiness_stall_days
    # Otherwise: use stickiness_days
    use_regime_based_stickiness: bool = True
    stickiness_fast_threshold: float = 20.0  # days/month
    stickiness_stall_threshold: float = 5.0  # days/month
    stickiness_fast_days: int = 0  # No stickiness for fast-moving series
    # Phase 3: Increased from 90->120 for stalled series to prevent hallucinated moves
    # stickiness_stall_days: 90 (Tuned for 6-month horizon 2022-2024)
    stickiness_stall_days: int = 90

    # "Caps": Maximum days the cutoff can move forward/back in one month.
    cap_forward_days: int = 47
    cap_back_days: int = 60

    # Seasonal Adjustment: Map of {month: adjustment_days} to add to final prediction
    # e.g. {10: -30} means subtract 30 days for October predictions
    seasonal_adjustment_map: dict[int, int] = field(default_factory=dict)

    # "Blend": Interpolate towards current cutoff. 1.0 = use raw. 0.0 = use current.
    # formula: final = current + lambda * (raw - current)
    blend_lambda: float = 0.995

    # Ensemble Persistence Weight: Blend final prediction with pure persistence (current cutoff)
    # formula: ensemble = (1 - alpha) * vqs_prediction + alpha * current_cutoff
    ensemble_persistence_weight: float = 0.797

    # If confidence is "low", ignore raw prediction and return current cutoff.
    use_no_change_when_low_confidence: bool = True

    # Ensemble trajectory blending: weight of ensemble vs physics at each step.
    # At step i: blended = physics + decay^i * (ensemble - physics)
    # 1.0 = ensemble fully overrides physics at step 0, decays for later steps
    # 0.0 = ensemble is ignored (pure physics)
    ensemble_trajectory_blend: float = 0.789
    ensemble_trajectory_decay: float = 0.821

    # Relaxed post-step shaping for ensemble predictions.
    # None = use the same values as physics (stickiness_days, cap_forward_days).
    ensemble_stickiness_days: int | None = 45
    ensemble_cap_forward_days: int | None = 115

    @classmethod
    def defaults(cls) -> "VqsMetaParams":
        """Return default parameters matching legacy hardcoded behavior."""
        return cls()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "VqsMetaParams":
        """Build from dictionary, ignoring unknown keys."""
        valid_keys = cls.__dataclass_fields__.keys()
        kwargs = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**kwargs)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return asdict(self)

    def apply_post_step(
        self,
        current_cutoff: date,
        raw_next_cutoff: date | None,
        confidence: str,
        advancement_rate: float | None = None,
        prevent_stickiness: bool = False,
        ensemble_mode: bool = False,
    ) -> date | None:
        """
        Apply post-step shaping logic: low-conf fallback, stickiness, caps, blend.

        Args:
            current_cutoff: The cutoff date at the start of the step.
            raw_next_cutoff: The cutoff predicted by the solver's physical model.
            confidence: "high", "medium", or "low".
            advancement_rate: Optional advancement rate (days/month) for regime-based stickiness.
            prevent_stickiness: If True, bypass stickiness logic (useful for first prediction step).
            ensemble_mode: If True, use relaxed ensemble-specific thresholds.

        Returns:
            The final predicted cutoff date.
        """
        # 1. Low Confidence Fallback
        if self.use_no_change_when_low_confidence and confidence == "low":
            return current_cutoff

        if raw_next_cutoff is None:
            return None

        raw_move_days = (raw_next_cutoff - current_cutoff).days

        # Select thresholds: relaxed for ensemble, strict for physics
        stick_days = (self.ensemble_stickiness_days if ensemble_mode and self.ensemble_stickiness_days is not None
                      else self.stickiness_days)
        cap_fwd = (self.ensemble_cap_forward_days if ensemble_mode and self.ensemble_cap_forward_days is not None
                   else self.cap_forward_days)

        # 2. Regime-based Stickiness
        effective_stickiness = stick_days
        if not ensemble_mode and self.use_regime_based_stickiness and advancement_rate is not None:
            if float(advancement_rate) > self.stickiness_fast_threshold:
                effective_stickiness = self.stickiness_fast_days
            elif float(advancement_rate) < self.stickiness_stall_threshold:
                effective_stickiness = self.stickiness_stall_days

        if not prevent_stickiness and 0 < abs(raw_move_days) <= effective_stickiness:
            return current_cutoff

        # 3. Caps (Clamping)
        if raw_move_days > cap_fwd:
            raw_move_days = cap_fwd
        # Cap Backward (Retrogression)
        # raw_move_days is negative. limit is say 60. so raw_move >= -60.
        elif raw_move_days < -self.cap_back_days:
            raw_move_days = -self.cap_back_days

        # 3b. Seasonal Adjustment
        # If the target month has a mapped adjustment, apply it
        # raw_next_cutoff is the target date.
        if raw_next_cutoff:
            month = raw_next_cutoff.month
            adj = self.seasonal_adjustment_map.get(month, 0)
            if adj != 0:
                raw_move_days += adj

        # 4. Blend (Legacy VQS blending)
        # final_move = lambda * raw_clamped_move
        final_move_days = int(self.blend_lambda * raw_move_days)

        vqs_prediction = current_cutoff + timedelta(days=final_move_days)

        # 5. Ensemble Blending with Persistence
        # If enabled (weight > 0), blend VQS prediction with Current Cutoff
        if self.ensemble_persistence_weight > 0:
            # ensemble = (1 - w) * vqs + w * current
            # equivalent to: move = (1 - w) * vqs_move
            ensemble_move_days = int(
                (1.0 - self.ensemble_persistence_weight) * final_move_days
            )
            return current_cutoff + timedelta(days=ensemble_move_days)

        return vqs_prediction
