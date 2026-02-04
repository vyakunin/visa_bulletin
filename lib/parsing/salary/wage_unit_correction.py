"""
Shared wage unit correction logic for salary data import and fixes.

This module provides functions to detect and correct incorrect wage units,
ensuring that both the import routine and fix scripts use the same logic.

Thresholds are loaded from wage_thresholds_config.json (data-driven, updated periodically)
with fallback to hardcoded defaults if config is missing.
"""

import logging
import time
from decimal import Decimal
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

from lib.utils.bazel_runfiles import get_data_file_path
from lib.utils.rate_limited_logger import RateLimitedLogger
from models.enums.visa_program import WageUnit

logger = logging.getLogger(__name__)

# Rate-limited logger for wage correction warnings
_wage_correction_rate_logger = RateLimitedLogger(
    initial_count=5,
    min_interval_seconds=5.0,
    logger=logger,
    log_level=logging.WARNING
)

# Path to config file (using Bazel runfiles for proper path resolution)
_CONFIG_PATH = get_data_file_path('lib/parsing/salary/wage_thresholds_config.yaml')
if _CONFIG_PATH is None:
    # Fallback for non-Bazel environments
    _CONFIG_PATH = Path(__file__).parent / 'wage_thresholds_config.yaml'

# Default thresholds (fallback if config file doesn't exist or is invalid)
# Single unified range for both correction and validation
_DEFAULT_MIN_ANNUAL = 5000      # Absolute minimum (filters obvious errors)
_DEFAULT_MAX_ANNUAL = 900000    # 4σ upper bound (filters outliers)


def _load_thresholds_from_config():
    """Load thresholds from config file, with fallback to defaults."""
    if _CONFIG_PATH is None or not _CONFIG_PATH.exists():
        logger.debug(f"Config file not found: {_CONFIG_PATH}, using defaults")
        return None
    
    if yaml is None:
        logger.warning("PyYAML not installed, cannot load config file. Install with: pip install pyyaml")
        return None
    
    try:
        with open(_CONFIG_PATH, 'r') as f:
            config = yaml.safe_load(f)
        
        # Extract single unified threshold range
        annual_range = config.get('annual_wage_range', {})
        thresholds = {
            'min_annual': annual_range.get('min'),
            'max_annual': annual_range.get('max'),
        }
        
        logger.debug(f"Loaded thresholds from config (last updated: {config.get('_last_updated', 'unknown')})")
        return thresholds
    except Exception as e:
        logger.warning(f"Failed to load thresholds from config: {e}, using defaults")
        return None


def _get_thresholds():
    """Get current thresholds (from config or defaults)."""
    config = _load_thresholds_from_config()
    
    if config is None:
        return {
            'min_annual': _DEFAULT_MIN_ANNUAL,
            'max_annual': _DEFAULT_MAX_ANNUAL,
        }
    
    return {
        'min_annual': config.get('min_annual') or _DEFAULT_MIN_ANNUAL,
        'max_annual': config.get('max_annual') or _DEFAULT_MAX_ANNUAL,
    }


# Load thresholds at module import time
_THRESHOLDS = _get_thresholds()

# Export thresholds as module-level constants
MIN_ANNUAL = _THRESHOLDS['min_annual']
MAX_ANNUAL = _THRESHOLDS['max_annual']

# Backward compatibility aliases (deprecated - use MIN_ANNUAL/MAX_ANNUAL instead)
MIN_REASONABLE_ANNUAL = MIN_ANNUAL
MAX_REASONABLE_ANNUAL = MAX_ANNUAL
MIN_REASONABLE_WAGE = Decimal(str(MIN_ANNUAL))
MAX_REASONABLE_WAGE = Decimal(str(MAX_ANNUAL))
MIN_VALID_ANNUAL = MIN_ANNUAL
MAX_VALID_ANNUAL = MAX_ANNUAL

# Hours per year for hourly wage calculations
HOURS_PER_YEAR = 2080

# When annual is too low (unit YEAR, wage_from < MIN_ANNUAL), try these units in order.
# First unit that yields annual in [MIN_ANNUAL, MAX_ANNUAL] is used (derived from yearly range).
_UNITS_TO_TRY_WHEN_ANNUAL_TOO_LOW = (WageUnit.HOUR, WageUnit.WEEK, WageUnit.BI_WEEKLY, WageUnit.MONTH)


def should_correct_wage_unit(
    wage_from: Decimal | None,
    wage_unit: str | WageUnit,
    wage_annual: Decimal | None = None,
) -> bool:
    """
    Determine if a wage unit should be corrected to YEAR.
    
    Strategy: Convert wage_from to implied annual using the stated unit,
    then check if it falls outside the valid range. If so, try treating
    wage_from as annual - if that's in range, correct the unit.
    
    Args:
        wage_from: The wage_from value
        wage_unit: Current wage unit (HOUR, WEEK, MONTH, BI_WEEKLY, YEAR)
        wage_annual: Optional wage_annual value (ignored - kept for backward compatibility)
    
    Returns:
        True if wage_unit should be corrected to YEAR, False otherwise
    """
    if not wage_from or wage_unit == WageUnit.YEAR:
        return False
    
    wage_from_float = float(wage_from)
    
    # Calculate implied annual wage using the stated unit
    implied_annual = float(calculate_annual_wage(wage_from, wage_unit))
    
    # If implied annual is outside valid range, check if wage_from itself is in range
    # (which would mean the unit is wrong and should be YEAR)
    if not (MIN_ANNUAL <= implied_annual <= MAX_ANNUAL):
        # Check if treating wage_from as annual would be in range
        if MIN_ANNUAL <= wage_from_float <= MAX_ANNUAL:
            return True  # wage_from is reasonable as annual, so correct unit to YEAR
    
    return False


def correct_wage_unit(
    wage_from: Decimal | None,
    wage_unit: str | WageUnit,
    row_num: int | None = None,
    wage_annual: Decimal | None = None,
) -> WageUnit:
    """
    Correct wage unit when implied annual is out of range (both directions).

    Two directions (both derived from [MIN_ANNUAL, MAX_ANNUAL]):

    1. Down (implied annual too high): Any unit → YEAR. If implied annual is above
       MAX_ANNUAL but wage_from as annual is in range, treat as YEAR. Handled for
       HOUR, WEEK, BI_WEEKLY, MONTH in should_correct_wage_unit.

    2. Up (implied annual too low): YEAR → sub-annual. If unit is YEAR and wage_from
       is below MIN_ANNUAL, try HOUR, WEEK, BI_WEEKLY, MONTH in order; use the first
       unit for which wage_from yields annual in [MIN_ANNUAL, MAX_ANNUAL].

    This is the main function used during import to prevent incorrect wage units
    from being saved. It uses the same logic as the fix script to ensure consistency.

    Args:
        wage_from: The wage_from value
        wage_unit: Current wage unit
        row_num: Optional row number for logging (used during import)
        wage_annual: Optional wage_annual value (ignored - kept for backward compatibility)

    Returns:
        Corrected wage_unit (YEAR or first matching sub-annual unit, or original)
    """
    if not wage_from:
        return wage_unit

    wage_from_float = float(wage_from)

    # Up: unit YEAR but wage_from tiny — try sub-annual units (HOUR, WEEK, BI_WEEKLY, MONTH)
    if wage_unit == WageUnit.YEAR and wage_from_float < MIN_ANNUAL:
        for candidate_unit in _UNITS_TO_TRY_WHEN_ANNUAL_TOO_LOW:
            annual_if_candidate = float(calculate_annual_wage(wage_from, candidate_unit))
            if MIN_ANNUAL <= annual_if_candidate <= MAX_ANNUAL:
                if row_num is not None:
                    unit_display = candidate_unit.value if hasattr(candidate_unit, "value") else candidate_unit
                    _wage_correction_rate_logger.log(
                        f"Row {row_num}: wage_from=${wage_from:,.0f} with unit=YEAR gives annual below ${MIN_ANNUAL:,} "
                        f"- treating as {unit_display} (annual=${annual_if_candidate:,.0f})"
                    )
                return candidate_unit

    # Down: implied annual too high — treat wage_from as annual (→ YEAR)
    if not should_correct_wage_unit(wage_from, wage_unit, wage_annual):
        return wage_unit

    # Generate appropriate log message with rate limiting
    if row_num is not None:
        implied_annual = float(calculate_annual_wage(wage_from, wage_unit))
        # Extract string value if wage_unit is enum
        unit_display = wage_unit.value if hasattr(wage_unit, 'value') else wage_unit
        message = (
            f"wage_from=${wage_from:,.0f} with unit={unit_display} "
            f"implies annual=${implied_annual:,.0f} (outside ${MIN_ANNUAL:,}-${MAX_ANNUAL:,} range) "
            f"- treating as YEAR instead"
        )

        # Log with rate limiting (automatically includes suppressed count if needed)
        _wage_correction_rate_logger.log(f"Row {row_num}: {message}")

    return WageUnit.YEAR  # Return enum (consistent with input type)


def calculate_annual_wage(wage_from: Decimal | None, wage_unit: str | WageUnit) -> Decimal | None:
    """
    Calculate annual wage from wage_from and wage_unit.
    
    This is a shared function to ensure consistent annual wage calculations
    across import and fix routines.
    
    Args:
        wage_from: The wage_from value
        wage_unit: Wage unit (YEAR, MONTH, BI_WEEKLY, WEEK, HOUR)
    
    Returns:
        Annual wage as Decimal, or None if wage_from is None
    """
    if not wage_from:
        return None
    
    multipliers = {
        WageUnit.YEAR: 1,
        WageUnit.MONTH: 12,
        WageUnit.BI_WEEKLY: 26,
        WageUnit.WEEK: 52,
        WageUnit.HOUR: HOURS_PER_YEAR,
    }
    
    multiplier = multipliers.get(wage_unit, 1)
    return wage_from * multiplier


def validate_wage_annual(wage_annual: Decimal | None, row_num: int | None = None) -> tuple[bool, str | None]:
    """
    Validate that annual wage is within acceptable range.
    
    Args:
        wage_annual: Annual wage value to validate
        row_num: Optional row number for logging
    
    Returns:
        Tuple of (is_valid, error_message)
        - is_valid: True if wage is valid, False if should be rejected
        - error_message: Human-readable reason if invalid, None if valid
    """
    if wage_annual is None:
        return True, None  # Missing wage is handled separately
    
    wage_float = float(wage_annual)
    
    if wage_float < MIN_ANNUAL:
        message = f"Annual wage ${wage_float:,.0f} is below minimum threshold ${MIN_ANNUAL:,} - likely data error or incorrect unit"
        if row_num is not None:
            logger.warning(f"Row {row_num}: {message}")
        return False, message
    
    if wage_float > MAX_ANNUAL:
        message = f"Annual wage ${wage_float:,.0f} exceeds maximum threshold ${MAX_ANNUAL:,} - likely data error or incorrect unit"
        if row_num is not None:
            logger.warning(f"Row {row_num}: {message}")
        return False, message
    
    return True, None


def should_flag_for_review(wage_annual: Decimal | None, wage_unit: str | None = None) -> tuple[bool, str | None]:
    """
    Determine if a wage should be flagged for manual review.
    
    This is less strict than validation - it flags suspicious values but doesn't reject them.
    Used for post-ingest validation and reporting.
    
    Args:
        wage_annual: Annual wage value
        wage_unit: Optional wage unit (ignored - kept for backward compatibility)
    
    Returns:
        Tuple of (should_flag, reason)
        - should_flag: True if should be flagged for review
        - reason: Human-readable reason if flagged, None if not flagged
    """
    if wage_annual is None:
        return False, None
    
    wage_float = float(wage_annual)
    
    # Flag wages outside valid range
    if wage_float > MAX_ANNUAL:
        return True, f"Wage ${wage_float:,.0f} exceeds maximum ${MAX_ANNUAL:,} - likely parsing error or data entry error"
    
    if wage_float < MIN_ANNUAL and wage_float > 0:
        return True, f"Wage ${wage_float:,.0f} below minimum ${MIN_ANNUAL:,} - likely incorrect unit or data error"
    
    return False, None

