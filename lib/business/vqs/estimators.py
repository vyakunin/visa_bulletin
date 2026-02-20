"""Model B (attrition) and Model C (supply) for VQS.

Supply model with per-class allocation, fiscal year seasonality,
and spillover modeling based on INA statutory provisions.
"""

from datetime import date

from models.enums.country import Country

# Default monthly retention (1 - attrition). No leakage = 1.0.
DEFAULT_ATTRITION_LAMBDA = 1.0

# Statutory minimum employment-based visas per FY; Model C can refine with spillover.
DEFAULT_ANNUAL_EB_LIMIT = 140_000

# Per-country cap is 7% of annual limit (INA §202(a)(2)).
PER_COUNTRY_SHARE = 0.07

# Countries that are consistently oversubscribed and hit the 7% cap.
OVERSUBSCRIBED_COUNTRIES = {
    Country.INDIA.value,
    Country.CHINA.value,
    Country.MEXICO.value,
    Country.PHILIPPINES.value,
    Country.EL_SALVADOR_GUATEMALA_HONDURAS.value,
}

# INA §203(b) allocates EB visas by preference:
#   EB1: 28.6%, EB2: 28.6%, EB3: 28.6%, EB4: 7.1%, EB5: 7.1%
# Unused higher-preference visas fall down (EB1→EB2→EB3) but that is
# captured separately via spillover, not in the base share.
PER_CLASS_SHARE = {
    "1st": 0.286,
    "2nd": 0.286,
    "3rd": 0.286,
    "4th": 0.071,
    "5th": 0.071,
}

# Fiscal year seasonality: DOS issues visas conservatively early in FY (Oct)
# and accelerates in Q3-Q4 (Apr-Sep) to use remaining numbers.
# Multipliers are relative to the uniform monthly allocation (sum ≈ 12.0).
FY_SEASONAL_MULTIPLIER = {
    10: 0.50,
    11: 0.60,
    12: 0.70,
    1: 0.80,
    2: 0.85,
    3: 0.90,
    4: 1.00,
    5: 1.10,
    6: 1.20,
    7: 1.30,
    8: 1.50,
    9: 1.55,
}

# Spillover: unused Family-Based visas spill to EB per INA §201(d).
# Typically ~30K-50K additional EB visas per year, concentrated in Q4 (Jul-Sep).
SPILLOVER_MONTHS = {7, 8, 9}
SPILLOVER_BONUS_RATE = 0.15


def get_monthly_retention_lambda(
    _month: date | None = None,
    _facts: list | None = None,
) -> float:
    """
    Model B: Return monthly retention rate λ (fraction of queue remaining each month).

    Phase 3 stub: constant. Future: survival model or ledger-backed.
    """
    return DEFAULT_ATTRITION_LAMBDA


def get_monthly_supply(
    month: date,
    _facts: list | None = None,
    country: int | None = None,
    visa_class: str | None = None,
    country_share: float | None = None,
) -> int:
    """
    Model C: Return monthly supply (visas) for the given month.

    Layers applied in order:
      1. Base: annual EB limit (140K) / 12
      2. Country share: 7% for oversubscribed, ~60% for ROW
      3. Per-class share: split country allocation across EB1-EB5
      4. Seasonality: DOS issuance pattern (low Oct, high Sep)
      5. Spillover: FB unused visas flowing to EB in Jul-Sep

    Args:
        month: The simulation month.
        _facts: Raw facts (unused; future: DOS spillover data).
        country: Country enum value. Determines per-country share.
        visa_class: Visa class (e.g. "2nd"). Determines per-class share.
        country_share: Explicit override for per-country share (0.0-1.0).

    Returns:
        Monthly visa supply (integer, at least 1).
    """
    # Layer 1+2: Country share
    if country_share is not None:
        share = country_share
    elif country is not None and country in OVERSUBSCRIBED_COUNTRIES:
        share = PER_COUNTRY_SHARE
    else:
        share = 0.60

    base_annual = DEFAULT_ANNUAL_EB_LIMIT * share

    # Layer 3: Per-class share
    class_share = PER_CLASS_SHARE.get(visa_class, 0.286) if visa_class else 1.0
    class_annual = base_annual * class_share

    monthly_base = class_annual / 12

    # Layer 4: Seasonality
    seasonal = FY_SEASONAL_MULTIPLIER.get(month.month, 1.0)
    monthly_adjusted = monthly_base * seasonal

    # Layer 5: Spillover (FB → EB in Q4 months)
    if month.month in SPILLOVER_MONTHS:
        monthly_adjusted *= 1.0 + SPILLOVER_BONUS_RATE

    # EB1 bonus: spillover from EB2/EB3 to EB1 often concentrates Apr–Sep (Q3–Q4).
    if visa_class == "1st" and month.month in (4, 5, 6, 7, 8, 9):
        monthly_adjusted *= 1.05

    return max(1, int(monthly_adjusted))
