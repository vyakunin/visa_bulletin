#!/usr/bin/env python3
"""
Master orchestrator for all data quality fixes.

This script runs all fix scripts in optimal order:
1. Fix missing fiscal years (from source URL)
2. Fix invalid wages (unit correction + data errors)
3. Fix missing salary data (recalculate wage_annual)
4. Fix invalid state codes
5. Fix missing employer links
6. Check import completeness (report only)
7. Run validation to verify fixes

Usage:
    # Dry-run (analyze only)
    bazel run //scripts/salary:fix_all_data_quality_issues

    # Actually fix all issues
    bazel run //scripts/salary:fix_all_data_quality_issues -- --fix

    # Skip specific fixes
    bazel run //scripts/salary:fix_all_data_quality_issues -- --fix --skip-wages --skip-fiscal-year
"""

import argparse
import logging
import os
import subprocess
import sys

# Setup Django early
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django_config.logging_config import setup_logging
from lib.utils.logging_utils import ScriptLogger

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)


def run_command(cmd: list[str], description: str) -> bool:
    """Run a command and return success status"""
    logger.info(f"\n{'=' * 80}")
    logger.info(f"Running: {description}")
    logger.info(f"Command: {' '.join(cmd)}")
    logger.info(f"{'=' * 80}\n")

    try:
        _result = subprocess.run(
            cmd,
            check=True,
            capture_output=False,  # Show output in real-time
            text=True,
        )
        logger.info(f"✅ {description} completed successfully")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"❌ {description} failed with exit code {e.returncode}")
        return False
    except Exception as e:
        logger.error(f"❌ {description} failed: {e}")
        return False


def fix_fiscal_years(fix: bool = False) -> bool:
    """Fix missing fiscal years from source URL"""
    cmd = ["bazel", "run", "//scripts/salary:fix_fiscal_year_from_url"]
    if fix:
        # No --dry-run flag needed, script fixes by default
        pass
    else:
        cmd.extend(["--", "--dry-run"])

    if not fix:
        logger.info("[DRY RUN] Would fix missing fiscal years from source URL")
        return True

    return run_command(cmd, "Fix missing fiscal years")


def fix_invalid_wages(fix: bool = False) -> bool:
    """Fix invalid wages (unit correction + data errors)"""
    cmd = ["bazel", "run", "//scripts/salary:fix_invalid_wages"]
    if not fix:
        cmd.extend(["--", "--dry-run"])

    if not fix:
        logger.info("[DRY RUN] Would fix invalid wages (both high and low)")
        return True

    return run_command(cmd, "Fix invalid wages")


def fix_missing_salary_data(fix: bool = False) -> bool:
    """Fix records with missing wage_annual (recalculate from wage_from/wage_unit)"""
    cmd = ["bazel", "run", "//scripts/salary:fix_missing_salary_data"]
    if fix:
        cmd.extend(["--", "--fix"])
    else:
        logger.info("[DRY RUN] Would fix missing salary data (recalculate wage_annual)")
        return True

    return run_command(cmd, "Fix missing salary data")


def fix_state_codes(fix: bool = False) -> bool:
    """Fix invalid state codes"""
    cmd = ["bazel", "run", "//scripts/salary:fix_state_codes"]
    if not fix:
        cmd.extend(["--", "--dry-run"])

    if not fix:
        logger.info("[DRY RUN] Would fix invalid state codes")
        return True

    return run_command(cmd, "Fix invalid state codes")


def fix_missing_employers(fix: bool = False) -> bool:
    """Fix missing employer links"""
    cmd = ["bazel", "run", "//scripts/salary:fix_missing_employers"]
    if fix:
        cmd.extend(["--", "--fix"])
    else:
        logger.info("[DRY RUN] Would fix missing employer links")
        return True

    return run_command(cmd, "Fix missing employer links")


def check_import_completeness() -> bool:
    """Check import completeness (report only) - uses master validation script"""
    cmd = [
        "bazel",
        "run",
        "//scripts/salary:validate_data",
        "--",
        "--check-import-completeness-by-file",
    ]
    return run_command(cmd, "Check import completeness")


def run_validation() -> bool:
    """Run comprehensive validation to verify fixes"""
    cmd = ["bazel", "run", "//scripts/salary:validate_data", "--"]
    return run_command(cmd, "Run data validation")


def main():
    parser = argparse.ArgumentParser(
        description="Master orchestrator for all data quality fixes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
This script runs all fix scripts in optimal order:
  1. Fix missing fiscal years (from source URL)
  2. Fix invalid wages (unit correction + data errors)
  3. Fix missing salary data (recalculate wage_annual)
  4. Fix invalid state codes
  5. Fix missing employer links
  6. Check import completeness (report only)
  7. Run validation to verify fixes

Examples:
  Dry-run (analyze only):
    bazel run //scripts/salary:fix_all_data_quality_issues

  Actually fix all issues:
    bazel run //scripts/salary:fix_all_data_quality_issues -- --fix

  Skip specific fixes:
    bazel run //scripts/salary:fix_all_data_quality_issues -- --fix --skip-wages --skip-state-codes
        """,
    )

    parser.add_argument(
        "--fix", action="store_true", help="Actually fix issues (default is dry-run)"
    )

    parser.add_argument(
        "--skip-fiscal-year", action="store_true", help="Skip fiscal year fix"
    )

    parser.add_argument(
        "--skip-wages", action="store_true", help="Skip invalid wages fix"
    )

    parser.add_argument(
        "--skip-salary", action="store_true", help="Skip missing salary data fix"
    )

    parser.add_argument(
        "--skip-state-codes", action="store_true", help="Skip invalid state codes fix"
    )

    parser.add_argument(
        "--skip-employers", action="store_true", help="Skip missing employer links fix"
    )

    parser.add_argument(
        "--skip-completeness",
        action="store_true",
        help="Skip import completeness check",
    )

    parser.add_argument(
        "--skip-validation", action="store_true", help="Skip validation after fixes"
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "fix": args.fix,
            "skip_fiscal_year": args.skip_fiscal_year,
            "skip_wages": args.skip_wages,
            "skip_salary": args.skip_salary,
            "skip_state_codes": args.skip_state_codes,
            "skip_employers": args.skip_employers,
            "skip_completeness": args.skip_completeness,
            "skip_validation": args.skip_validation,
        },
        context="Master orchestrator for all data quality fixes",
    )

    mode_str = "[DRY RUN] " if not args.fix else ""
    logger.info("=" * 80)
    logger.info(f"{mode_str}FIX ALL DATA QUALITY ISSUES")
    logger.info("=" * 80)
    logger.info("")

    results = {
        "fiscal_year": None,
        "wages": None,
        "salary": None,
        "state_codes": None,
        "employers": None,
        "completeness": None,
        "validation": None,
    }

    # 1. Fix missing fiscal years (from source URL)
    if not args.skip_fiscal_year:
        results["fiscal_year"] = fix_fiscal_years(fix=args.fix)
    else:
        logger.info("Skipping fiscal year fix")

    # 2. Fix invalid wages (unit correction + data errors)
    if not args.skip_wages:
        results["wages"] = fix_invalid_wages(fix=args.fix)
    else:
        logger.info("Skipping invalid wages fix")

    # 3. Fix missing salary data (recalculate wage_annual)
    if not args.skip_salary:
        results["salary"] = fix_missing_salary_data(fix=args.fix)
    else:
        logger.info("Skipping missing salary data fix")

    # 4. Fix invalid state codes
    if not args.skip_state_codes:
        results["state_codes"] = fix_state_codes(fix=args.fix)
    else:
        logger.info("Skipping invalid state codes fix")

    # 5. Fix missing employer links
    if not args.skip_employers:
        results["employers"] = fix_missing_employers(fix=args.fix)
    else:
        logger.info("Skipping missing employer links fix")

    # 6. Check import completeness (report only)
    if not args.skip_completeness:
        results["completeness"] = check_import_completeness()
    else:
        logger.info("Skipping import completeness check")

    # 7. Run validation
    if not args.skip_validation:
        results["validation"] = run_validation()
    else:
        logger.info("Skipping validation")

    # Summary
    print("\n" + "=" * 80)
    print(f"{mode_str}SUMMARY")
    print("=" * 80)

    for check_name, result in results.items():
        if result is None:
            status = "SKIPPED"
        elif result:
            status = "✅ PASSED"
        else:
            status = "❌ FAILED"
        print(f"{check_name.capitalize()}: {status}")

    # Exit with error if any fix failed
    failed = [name for name, result in results.items() if result is False]
    if failed:
        logger.error(f"\nFailed checks: {', '.join(failed)}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
