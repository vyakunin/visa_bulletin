# Wage Thresholds Configuration

## Overview

Wage thresholds used for validation and correction are **data-driven** and stored in `lib/parsing/salary/wage_thresholds_config.yaml`. This prevents thresholds from becoming outdated as salaries increase with inflation.

## How It Works

1. **Config File**: Thresholds are stored in JSON format with metadata
2. **Auto-Loading**: `wage_unit_correction.py` automatically loads thresholds from config at import time
3. **Fallback**: If config file is missing or invalid, falls back to hardcoded defaults
4. **Periodic Updates**: Run `update_wage_thresholds.py` periodically (e.g., annually) to recalculate from recent data

## Updating Thresholds

### Automatic Update (Recommended)

```bash
# Update using last 2 years of data (default)
bazel run //scripts/salary:update_wage_thresholds

# Update using last 3 years
bazel run //scripts/salary:update_wage_thresholds -- --years 3

# Use 99.5th percentile instead of 99th
bazel run //scripts/salary:update_wage_thresholds -- --percentile 99.5

# Dry-run to see what would be calculated
bazel run //scripts/salary:update_wage_thresholds -- --dry-run
```

### Manual Update

Edit `lib/parsing/salary/wage_thresholds_config.yaml` directly if needed, but prefer using the script.

## Threshold Types

### Wage Unit Thresholds
- **hour**: Maximum reasonable hourly rate (e.g., $500/hr)
- **month**: Maximum reasonable monthly rate (e.g., $50K/month)
- **week**: Maximum reasonable weekly rate (e.g., $20K/week)
- **bi_weekly**: Maximum reasonable bi-weekly rate (e.g., $20K/bi-weekly)

### Reasonable Annual Range
- **min**: Minimum reasonable annual salary (e.g., $30K)
- **max**: Maximum reasonable annual salary (e.g., $1M)

### Validation Thresholds
- **min_valid_annual**: Absolute minimum to accept (e.g., $10K)
- **max_valid_annual**: Absolute maximum to accept (e.g., $10M)

### Implied Hourly Threshold
- Maximum reasonable implied hourly rate when calculating from annual (e.g., $500/hr)

## Calculation Method

The update script calculates thresholds using **percentiles** from recent data:

- **Min reasonable**: 5th percentile of annual wages
- **Max reasonable**: 99th percentile of annual wages (configurable)
- **Hourly threshold**: 99th percentile of implied hourly rates

This ensures thresholds stay aligned with actual salary distributions.

## When to Update

**Recommended schedule:**
- **Annually**: Update once per year to account for inflation and salary trends
- **After major data imports**: If importing large amounts of historical data
- **If validation flags too many records**: May indicate thresholds need adjustment

## Configuration File Structure

```yaml
# Wage thresholds calculated from recent data distributions
_last_updated: "2025-01-01"
_source: "Calculated from salary data distributions"

wage_unit_thresholds:
  hour: 500
  bi_weekly: 20000
  week: 20000
  month: 50000

reasonable_annual_range:
  min: 30000
  max: 1000000

validation_thresholds:
  min_valid_annual: 10000
  max_valid_annual: 10000000

implied_hourly_threshold: 500

percentiles:
  p1: 25000
  p5: 30000
  p95: 200000
  p99: 1000000
```

## Benefits

1. **Inflation-resistant**: Thresholds automatically adjust as salaries increase
2. **Data-driven**: Based on actual distributions, not arbitrary values
3. **Maintainable**: Single YAML config file (supports comments), easy to update
4. **Backward compatible**: Falls back to defaults if config missing
5. **Transparent**: Percentiles stored in config show calculation basis
6. **Human-readable**: YAML format is easier to read and edit than JSON

## Migration Notes

- Existing code continues to work (uses module-level constants)
- Config file is optional (falls back to defaults)
- No breaking changes to API
- Can be adopted gradually









