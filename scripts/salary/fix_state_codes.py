#!/usr/bin/env python3
"""
Fix records with invalid state codes.

This script identifies and fixes records where worksite_state contains invalid values.
Common issues:
- Typos (e.g., "Califonia" → "CA")
- Full state names (e.g., "California" → "CA")
- Abbreviations (e.g., "Calif" → "CA")
- Extra whitespace or case issues

Usage:
    bazel run //scripts/salary:fix_state_codes
    bazel run //scripts/salary:fix_state_codes -- --dry-run
    bazel run //scripts/salary:fix_state_codes -- --limit 1000
"""

import argparse
import logging
import os
from collections import defaultdict

# Setup Django
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import transaction

from django_config.logging_config import setup_logging
from lib.utils.location_utils import US_STATES, VALID_STATES
from lib.utils.logging_utils import ScriptLogger
from models.salary import SalaryRecord

script_logger = ScriptLogger(__file__)
setup_logging()
logger = logging.getLogger(__name__)

# Common typos and variations
STATE_FIXES = {
    # Common typos
    "Califonia": "CA",
    "Californa": "CA",
    "Calif": "CA",
    "Massachusets": "MA",
    "Massachussetts": "MA",
    "Mass": "MA",
    "New York": "NY",
    "New Jersey": "NJ",
    "New Mexico": "NM",
    "New Hampshire": "NH",
    "North Carolina": "NC",
    "North Dakota": "ND",
    "South Carolina": "SC",
    "South Dakota": "SD",
    "West Virginia": "WV",
    "Rhode Island": "RI",
    # Common abbreviations
    "Fla": "FL",
    "Tex": "TX",
    "Penn": "PA",
    "Ill": "IL",
    "Mich": "MI",
    "Wisc": "WI",
    "Minn": "MN",
    "Colo": "CO",
    "Ore": "OR",
    "Wash": "WA",
    "Conn": "CT",
    "Vt": "VT",
    "N.H.": "NH",
    "N.J.": "NJ",
    "N.Y.": "NY",
    "N.C.": "NC",
    "N.D.": "ND",
    "S.C.": "SC",
    "S.D.": "SD",
    "W.V.": "WV",
    "R.I.": "RI",
    # Case variations (normalize to uppercase)
    "ca": "CA",
    "ny": "NY",
    "tx": "TX",
    "fl": "FL",
    # Territories (may be valid but not in VALID_STATES - decide if needed)
    # 'PR': 'PR',  # Puerto Rico
    # 'VI': 'VI',  # US Virgin Islands
    # 'GU': 'GU',  # Guam
    # 'AS': 'AS',  # American Samoa
    # 'MP': 'MP',  # Northern Mariana Islands
}

# Build reverse mapping from state names to codes
STATE_NAME_TO_CODE = {name.upper(): code for code, name in US_STATES}
# Add to fixes
for name, code in STATE_NAME_TO_CODE.items():
    if name not in STATE_FIXES:
        STATE_FIXES[name] = code


def normalize_state_code(state: str | None) -> str | None:
    """Normalize state code - strip whitespace, uppercase."""
    if not state:
        return None
    return state.strip().upper()


def suggest_fix(state: str) -> str | None:
    """
    Suggest a fix for an invalid state code.

    Returns:
        Fixed state code if fix found, None otherwise
    """
    normalized = normalize_state_code(state)
    if not normalized:
        return None

    # Check if it's already valid after normalization
    if normalized in VALID_STATES:
        return normalized

    # Check direct fixes
    if normalized in STATE_FIXES:
        return STATE_FIXES[normalized]

    # Check if it's a state name (case-insensitive)
    if normalized in STATE_NAME_TO_CODE:
        return STATE_NAME_TO_CODE[normalized]

    # Check partial matches (e.g., "Calif" → "CA")
    for typo, code in STATE_FIXES.items():
        if typo.upper() in normalized or normalized in typo.upper():
            return code

    # Check if it's close to a state name (fuzzy matching)
    for state_name, code in STATE_NAME_TO_CODE.items():
        if normalized in state_name or state_name in normalized:
            return code

    return None


def analyze_invalid_states(limit: int | None = None) -> dict:
    """Analyze records with invalid state codes."""
    logger.info("Analyzing invalid state codes...")

    invalid_records = (
        SalaryRecord.objects.filter(worksite_state__isnull=False)
        .exclude(worksite_state__in=VALID_STATES)
        .exclude(worksite_state="")
    )

    if limit:
        invalid_records = invalid_records[:limit]

    total_invalid = (
        SalaryRecord.objects.filter(worksite_state__isnull=False)
        .exclude(worksite_state__in=VALID_STATES)
        .exclude(worksite_state="")
        .count()
    )

    logger.info(f"Found {total_invalid:,} records with invalid state codes")
    if limit:
        logger.info(f"Analyzing first {limit} records")
    logger.info("")

    # Group by invalid state value
    by_state = defaultdict(int)
    fixable = {}
    unfixable = []

    for record in invalid_records:
        state = record.worksite_state
        by_state[state] += 1

        suggested = suggest_fix(state)
        if suggested:
            fixable[state] = suggested
        else:
            if state not in unfixable:
                unfixable.append(state)

    logger.info("Breakdown by invalid state value (top 20):")
    for state, count in sorted(by_state.items(), key=lambda x: x[1], reverse=True)[:20]:
        fix = fixable.get(state, "❌ No fix found")
        logger.info(f"  '{state}': {count:,} records → {fix}")

    logger.info("")
    logger.info(f"Fixable: {len(fixable)} unique invalid states")
    logger.info(f"Unfixable: {len(unfixable)} unique invalid states")
    if unfixable:
        logger.info(f"  Examples: {', '.join(unfixable[:10])}")
    logger.info("")

    return {
        "total_invalid": total_invalid,
        "analyzed": invalid_records.count(),
        "fixable_count": sum(by_state[s] for s in fixable.keys()),
        "unfixable_count": sum(by_state[s] for s in unfixable),
        "by_state": dict(by_state),
        "fixable": fixable,
        "unfixable": unfixable[:20],
    }


def fix_state_codes(dry_run=False, limit=None):
    """Fix invalid state codes."""
    logger.info("=" * 80)
    logger.info("FIXING INVALID STATE CODES")
    logger.info("=" * 80)
    if dry_run:
        logger.info("DRY-RUN MODE - No changes will be made")
    logger.info("")

    analysis = analyze_invalid_states(limit=limit)

    if analysis["fixable_count"] == 0:
        logger.info("No fixable state codes found")
        return 0

    logger.info(
        f"Fixing {analysis['fixable_count']:,} records with fixable state codes..."
    )
    logger.info("")

    fixed_count = 0
    failed_count = 0

    # Get records with fixable states
    for invalid_state, correct_state in analysis["fixable"].items():
        records = SalaryRecord.objects.filter(worksite_state=invalid_state)

        if limit and fixed_count + records.count() > limit:
            records = records[: limit - fixed_count]

        count = records.count()
        logger.info(f"Fixing '{invalid_state}' → '{correct_state}': {count} records")

        if not dry_run:
            try:
                with transaction.atomic():
                    records.update(worksite_state=correct_state)
                fixed_count += count
                logger.info(f"  ✅ Fixed {count} records")
            except Exception as e:
                logger.error(f"  ❌ Failed to fix: {e}")
                failed_count += count
        else:
            fixed_count += count
            logger.info(f"  [DRY-RUN] Would fix {count} records")

    logger.info("")
    logger.info("=" * 80)
    logger.info("SUMMARY")
    logger.info("=" * 80)
    logger.info(f"Total invalid state codes: {analysis['total_invalid']:,}")
    logger.info(f"Fixable: {analysis['fixable_count']:,}")
    logger.info(f"Unfixable: {analysis['unfixable_count']:,}")
    logger.info(f"Fixed: {fixed_count:,}")
    if failed_count > 0:
        logger.info(f"Failed: {failed_count:,}")

    if dry_run:
        logger.info(
            "\nDRY-RUN: No changes were made. Run without --dry-run to apply fixes."
        )
    else:
        logger.info(f"\n✅ Fixed {fixed_count:,} records")

    return fixed_count


def main():
    parser = argparse.ArgumentParser(
        description="Fix records with invalid state codes",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry-run to see what would be fixed:
    bazel run //scripts/salary:fix_state_codes -- --dry-run

  Fix all fixable state codes:
    bazel run //scripts/salary:fix_state_codes

  Limit to first 1000 records:
    bazel run //scripts/salary:fix_state_codes -- --limit 1000
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be fixed without making changes",
    )

    parser.add_argument("--limit", type=int, help="Limit number of records to process")

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "dry_run": args.dry_run,
            "limit": args.limit,
        },
        context="Fixing invalid state codes",
    )

    fix_state_codes(dry_run=args.dry_run, limit=args.limit)


if __name__ == "__main__":
    main()
