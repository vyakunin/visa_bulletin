"""VQS Metric Configuration.

Configures horizon weights, period discounts, volatility discounting,
asymmetric loss, warmup decay, per-series weights, regime-conditioned
loss, and movement-magnitude weighting for composite multi-horizon
evaluation and Optuna optimization.
"""

from dataclasses import dataclass, field
from datetime import date
from statistics import stdev


FY_BOUNDARY_MONTHS = {8, 9, 10}

DEFAULT_SERIES_WEIGHTS: dict[tuple[str, int], float] = {
    ("2nd", 3): 1.5,  # India EB-2 (largest user base)
    ("3rd", 3): 1.5,  # India EB-3
    ("2nd", 2): 1.2,  # China EB-2
    ("3rd", 2): 1.0,  # China EB-3
    ("1st", 3): 0.8,  # India EB-1
    ("1st", 2): 0.8,  # China EB-1
}


@dataclass(frozen=True)
class PeriodDiscount:
    """A time window with reduced weight in metric computation."""

    start: date
    end: date
    weight: float


@dataclass(frozen=True)
class MetricConfig:
    """Configuration for multi-horizon composite metrics.

    Controls how prediction errors at different horizons and time periods
    are combined into a single optimization objective.
    """

    horizon_weights: dict[int, float] = field(
        default_factory=lambda: {
            1: 0.38,
            3: 0.104,
            6: 0.40,
            12: 0.255,
        }
    )

    period_discounts: list[PeriodDiscount] = field(
        default_factory=lambda: [
            PeriodDiscount(date(2023, 1, 1), date(2023, 12, 31), 0.2),
        ]
    )

    volatility_discount_k: float = 0.01

    use_huber_loss: bool = False
    huber_delta_days: float = 180.0

    trend_weight: float = 0.08

    optimistic_penalty: float = 1.3

    warmup_decay: float = 0.97

    # Per-series weights: (visa_class, country_int) -> multiplier.
    # Higher weight = series contributes more to composite loss.
    series_weights: dict[tuple[str, int], float] = field(
        default_factory=lambda: dict(DEFAULT_SERIES_WEIGHTS)
    )

    # Regime-conditioned loss: separate multipliers for FY boundary
    # months (Aug/Sep/Oct) vs steady-state. Prevents the optimizer
    # from "winning" only on FY boundary jumps and ignoring the rest.
    fy_boundary_weight: float = 1.202
    steady_state_weight: float = 1.973

    # Movement-magnitude weighting: scale loss by actual move size.
    # When > 0, months with large moves count proportionally more.
    # 0.0 = no magnitude weighting, 1.0 = fully proportional.
    move_magnitude_weight: float = 0.00373

    @classmethod
    def defaults(cls) -> "MetricConfig":
        return cls()

    def period_weight(self, d: date) -> float:
        """Weight for a given date based on period discounts."""
        w = 1.0
        for pd in self.period_discounts:
            if pd.start <= d <= pd.end:
                w = min(w, pd.weight)
        return w

    def series_weight(self, visa_class: str, country: int) -> float:
        """Weight multiplier for a (visa_class, country) series."""
        return self.series_weights.get((visa_class, country), 1.0)

    def regime_weight(self, target_month: int) -> float:
        """Weight multiplier based on whether the target is a FY boundary month."""
        if target_month in FY_BOUNDARY_MONTHS:
            return self.fy_boundary_weight
        return self.steady_state_weight

    def magnitude_weight(self, actual_move_days: int) -> float:
        """Weight multiplier based on actual movement magnitude.

        When move_magnitude_weight=0, all months are weighted equally.
        When move_magnitude_weight=1, a 300-day move gets 3x the weight
        of a 100-day move (linear in abs magnitude, floored at 30d).
        """
        if self.move_magnitude_weight <= 0:
            return 1.0
        floor = 30.0
        mag = max(floor, abs(actual_move_days))
        return 1.0 + self.move_magnitude_weight * (mag / floor - 1.0)

    def composite_weight(
        self,
        d: date,
        visa_class: str | None = None,
        country: int | None = None,
        target_month: int | None = None,
        actual_move_days: int | None = None,
    ) -> float:
        """Combined weight incorporating all dimensions."""
        w = self.period_weight(d)
        if visa_class is not None and country is not None:
            w *= self.series_weight(visa_class, country)
        if target_month is not None:
            w *= self.regime_weight(target_month)
        if actual_move_days is not None:
            w *= self.magnitude_weight(actual_move_days)
        return w

    def volatility_weight(self, recent_moves: list[float]) -> float:
        """Weight based on recent move volatility."""
        if len(recent_moves) < 3:
            return 1.0
        vol = stdev(recent_moves)
        return 1.0 / (1.0 + self.volatility_discount_k * vol)

    def huber_loss(self, error_days: float) -> float:
        """Huber loss: quadratic for small errors, linear for large ones."""
        delta = self.huber_delta_days
        abs_e = abs(error_days)
        if abs_e <= delta:
            return 0.5 * (error_days / 365.0) ** 2
        return (delta / 365.0) * (abs_e / 365.0 - 0.5 * delta / 365.0)

    def expert_loss(self, error_days: float) -> float:
        """Loss function for aggregator weight updates.

        Applies asymmetric penalty: optimistic errors (error_days > 0,
        meaning predicted cutoff is ahead of actual) get penalized more.
        """
        penalty = self.optimistic_penalty if error_days > 0 else 1.0
        if self.use_huber_loss:
            return self.huber_loss(error_days) * penalty
        return (error_days / 365.0) ** 2 * penalty

    def warmup_weight(self, months_ago: int) -> float:
        """Weight for a bulletin N months in the past during warmup."""
        return self.warmup_decay ** months_ago
