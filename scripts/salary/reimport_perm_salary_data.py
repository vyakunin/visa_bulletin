#!/usr/bin/env python3
"""
Re-import salary data for records with missing salary data.

This script:
1. Finds records with missing salary data (wage_annual is null/0)
2. Checks source files to see if salary data exists (in any column format)
3. Re-imports files if data exists using ingest pipeline
4. Drops records if data doesn't exist in source files

Supports both PERM and LCA files, and handles both SalaryRecord and WorksiteRecord.
WorksiteRecord requires salary data (not optional).

Uses PipelineOrchestrator with update_mode=True to:
1. Reuse existing parsing/transformation logic from ingest pipeline
2. Update existing records instead of creating new ones
3. Leverage checkpointing, resumption, and validation features

Usage:
    # Re-import PERM files
    bazel run //scripts/salary:reimport_perm_salary_data -- --file PERM_FY2019.xlsx --fix

    # Re-import all PERM files with missing data
    bazel run //scripts/salary:reimport_perm_salary_data -- --all-files --fix

    # Check source files first, then re-import or drop
    bazel run //scripts/salary:reimport_perm_salary_data -- --check-source-files --fix

    # Drop records without salary data (if source files don't have it)
    bazel run //scripts/salary:reimport_perm_salary_data -- --drop-unfixable --fix
"""

import argparse
import logging
import os
import sys
from pathlib import Path

# Setup Django early
if not os.environ.get("DJANGO_SETTINGS_MODULE"):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")

import django

django.setup()

from django.db import transaction
from django.db.models import Q

from django_config.logging_config import setup_logging
from lib.ingest.orchestrator import PipelineOrchestrator
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.ingest.registry import PluginRegistry
from lib.parsing.salary.db_importer import (
    LCA_COLUMN_MAPPINGS,
    PERM_COLUMN_MAPPINGS,
    _read_data_file,
    get_column_value,
)
from lib.utils.http_utils import get_workspace_dir
from lib.utils.logging_utils import ScriptLogger
from models.enums.visa_program import VisaProgram
from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, SourceType
from models.salary import SalaryRecord, WorksiteRecord

setup_logging()
logger = logging.getLogger(__name__)
script_logger = ScriptLogger(__file__)

# Register plugins (required for orchestrator)
# Plugins must be registered before orchestrator.run() is called
# Skip clustering during re-import for performance (employers should already be clustered)
_perm_plugin = PERMSalaryDataSourcePlugin(skip_clustering=True)
_lca_plugin = H1BSalaryDataSourcePlugin(skip_clustering=True)
PluginRegistry.register(_perm_plugin)
PluginRegistry.register(_lca_plugin)


def get_files_with_missing_data(
    visa_program: VisaProgram | None = None,
) -> list[tuple[str, int, str]]:
    """
    Get list of files with missing salary data, sorted by missing count.

    Returns:
        List of tuples: (source_file, missing_count, record_type)
        record_type is 'salary' or 'worksite'
    """
    from django.db.models import Count

    results = []

    # Get SalaryRecord files with missing data
    salary_files = SalaryRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
    )
    if visa_program:
        salary_files = salary_files.filter(visa_program=visa_program)

    salary_files = (
        salary_files.values("source_file")
        .annotate(missing_count=Count("id"))
        .order_by("-missing_count")
    )

    for item in salary_files:
        if item["source_file"]:
            results.append((item["source_file"], item["missing_count"], "salary"))

    # Get WorksiteRecord files with missing data (salary is REQUIRED for worksite)
    worksite_files = WorksiteRecord.objects.filter(
        Q(wage_annual__isnull=True) | Q(wage_annual=0)
    )
    if visa_program:
        worksite_files = worksite_files.filter(visa_program=visa_program)

    worksite_files = (
        worksite_files.values("source_file")
        .annotate(missing_count=Count("id"))
        .order_by("-missing_count")
    )

    for item in worksite_files:
        if item["source_file"]:
            results.append((item["source_file"], item["missing_count"], "worksite"))

    # Sort by missing count (descending)
    results.sort(key=lambda x: x[1], reverse=True)

    return results


def build_case_number_index(
    filepath: Path, column_mappings: dict, target_case_numbers: set[str] | None = None
) -> dict[str, dict]:
    """
    Build an index of case numbers to records from the source file.
    This allows efficient lookup without re-reading the file for each case.

    Args:
        filepath: Path to source file
        column_mappings: Column mappings for the file type
        target_case_numbers: If provided, only index these case numbers (much faster for large files)

    Returns:
        Dict mapping case_number -> record dict
    """
    index = {}
    try:
        # Normalize target case numbers for faster lookup
        target_normalized = None
        if target_case_numbers:
            target_normalized = {str(cn).strip().upper() for cn in target_case_numbers}
            target_original = {str(cn).strip() for cn in target_case_numbers}
            logger.info(
                f"Building index for {len(target_case_numbers)} target case numbers (optimized mode)"
            )
        else:
            logger.info("Building full case number index (may be slow for large files)")

        # Read file (always streaming)
        file_data = _read_data_file(filepath)
        if isinstance(file_data, tuple):
            records = file_data[0]  # Extract generator from tuple
        else:
            records = file_data

        indexed_count = 0
        for record in records:
            case_num = get_column_value(record, column_mappings["case_number"])
            if case_num:
                case_num_str = str(case_num).strip()
                normalized = case_num_str.upper()

                # If we have target case numbers, only index those
                if target_normalized:
                    if (
                        normalized not in target_normalized
                        and case_num_str not in target_original
                    ):
                        continue  # Skip records we don't need

                # Store in index
                if normalized not in index:
                    index[normalized] = record
                    indexed_count += 1
                # Also store with original case for exact matching
                if case_num_str not in index:
                    index[case_num_str] = record

                # If we have targets and found all of them, we can stop early
                if target_normalized and indexed_count >= len(target_case_numbers):
                    logger.info(
                        f"Found all {len(target_case_numbers)} target case numbers, stopping early"
                    )
                    break

        logger.info(f"Indexed {indexed_count:,} case numbers from source file")
        return index
    except Exception as e:
        logger.error(
            f"Error building case number index from {filepath}: {e}", exc_info=True
        )
        return {}


def check_source_file_for_salary_data(
    case_index: dict[str, dict], case_number: str, column_mappings: dict
) -> dict | None:
    """
    Check source file index for salary data for a specific case number.

    Args:
        case_index: Pre-built index from build_case_number_index()
        case_number: Case number to look up
        column_mappings: Column mappings for the file type

    Returns:
        Dict with salary data if found, None on error
    """
    try:
        # Try exact match first
        record = case_index.get(case_number)
        if not record:
            # Try normalized (uppercase, stripped)
            normalized = str(case_number).strip().upper()
            record = case_index.get(normalized)

        if not record:
            return {"found": False, "reason": "case_not_found"}

        # Found the record - check for salary data
        wage_from = get_column_value(record, column_mappings["wage_from"])
        wage_to = get_column_value(record, column_mappings["wage_to"])
        wage_unit = get_column_value(record, column_mappings["wage_unit"])

        # Try alternative column names if primary ones are empty
        if (
            not wage_from
            or str(wage_from).strip() == ""
            or str(wage_from).strip() == "0"
        ):
            # Try WAGE_RATE_OF_PAY (singular) - may contain ranges like "20000 -"
            if "WAGE_RATE_OF_PAY" in record and record["WAGE_RATE_OF_PAY"]:
                wage_rate_str = str(record["WAGE_RATE_OF_PAY"]).strip()
                if wage_rate_str and wage_rate_str != "0" and wage_rate_str != "-":
                    # Parse range (e.g., "20000 -" or "20000 - 30000")
                    import re

                    range_match = re.match(r"^([\d,]+\.?\d*)", wage_rate_str)
                    if range_match:
                        wage_from = range_match.group(1)

            # Try other common column name variations if still not found
            if (
                not wage_from
                or str(wage_from).strip() == ""
                or str(wage_from).strip() == "0"
            ):
                for alt_col in ["WAGE", "SALARY", "PAY", "WAGE_RATE", "WAGE_AMOUNT"]:
                    if alt_col in record and record[alt_col]:
                        alt_value = str(record[alt_col]).strip()
                        if alt_value and alt_value != "0":
                            wage_from = alt_value
                            break

        if wage_from and str(wage_from).strip() and str(wage_from).strip() != "0":
            return {
                "wage_from": wage_from,
                "wage_to": wage_to,
                "wage_unit": wage_unit,
                "found": True,
            }
        else:
            # Found the record but no salary data
            return {"found": False, "reason": "no_salary_data"}

    except Exception as e:
        logger.error(
            f"Error checking case {case_number} in source file index: {e}",
            exc_info=True,
        )
        return None


def determine_file_type(filepath: Path) -> tuple[SourceType, dict]:
    """Determine file type (PERM or LCA) and return appropriate column mappings"""
    filename = filepath.name.upper()
    if "PERM" in filename:
        return SourceType.PERM, PERM_COLUMN_MAPPINGS
    else:
        return SourceType.LCA, LCA_COLUMN_MAPPINGS


def check_file_has_salary_data(
    filepath: Path,
    missing_case_numbers: list[str],
    sample_size: int = 10,
    target_case_numbers: set[str] | None = None,
) -> dict:
    """
    Check if source file has salary data for missing records.

    Args:
        filepath: Path to source file
        missing_case_numbers: List of case numbers to check
        sample_size: Number of cases to sample for checking
        target_case_numbers: If provided, only index these case numbers (optimization for large files)

    Returns:
        Dict with check results including detailed findings
    """
    source_type, column_mappings = determine_file_type(filepath)

    # Build case number index once (optimized to only index target case numbers if provided)
    logger.info(f"Building case number index from {filepath.name}...")
    case_index = build_case_number_index(
        filepath, column_mappings, target_case_numbers=target_case_numbers
    )

    # Sample records to check
    sample_cases = missing_case_numbers[:sample_size]

    found_count = 0
    not_found_count = 0
    case_not_found_count = 0
    no_salary_data_count = 0
    detailed_results = []

    for case_number in sample_cases:
        result = check_source_file_for_salary_data(
            case_index, case_number, column_mappings
        )
        if result:
            if result.get("found"):
                found_count += 1
                detailed_results.append(
                    {
                        "case_number": case_number,
                        "status": "found",
                        "wage_from": result.get("wage_from"),
                        "wage_unit": result.get("wage_unit"),
                    }
                )
            else:
                not_found_count += 1
                reason = result.get("reason", "unknown")
                if reason == "case_not_found":
                    case_not_found_count += 1
                elif reason == "no_salary_data":
                    no_salary_data_count += 1
                detailed_results.append(
                    {
                        "case_number": case_number,
                        "status": "not_found",
                        "reason": reason,
                    }
                )
        else:
            not_found_count += 1
            detailed_results.append(
                {
                    "case_number": case_number,
                    "status": "error",
                    "reason": "check_failed",
                }
            )

    return {
        "has_data": found_count > 0,
        "sample_checked": len(sample_cases),
        "found_in_source": found_count,
        "not_found_in_source": not_found_count,
        "case_not_found": case_not_found_count,
        "no_salary_data": no_salary_data_count,
        "detailed_results": detailed_results,
        "total_indexed": len(case_index),
    }


def update_records_from_file(
    filepath: Path,
    dry_run: bool = True,
    limit: int | None = None,
    check_source_first: bool = False,
) -> dict:
    """
    Use orchestrator with update_mode to re-import and update existing records.

    Returns:
        Dict with update statistics
    """
    logger.info(f"Processing file: {filepath.name}")

    # Determine file type
    source_type, _ = determine_file_type(filepath)

    # Get existing records for this file that need updating
    existing_salary_records = SalaryRecord.objects.filter(
        source_file=filepath.name, is_worksite=False
    ).filter(Q(wage_annual__isnull=True) | Q(wage_annual=0))

    existing_worksite_records = WorksiteRecord.objects.filter(
        source_file=filepath.name
    ).filter(Q(wage_annual__isnull=True) | Q(wage_annual=0))

    total_salary_to_update = existing_salary_records.count()
    total_worksite_to_update = existing_worksite_records.count()
    total_to_update = total_salary_to_update + total_worksite_to_update

    logger.info(
        f"Found {total_salary_to_update:,} SalaryRecord and {total_worksite_to_update:,} WorksiteRecord records to update in {filepath.name}"
    )

    if total_to_update == 0:
        return {
            "updated": 0,
            "errors": 0,
            "not_found": 0,
            "dropped": 0,
            "salary_updated": 0,
            "worksite_updated": 0,
        }

    # Check source file first if requested
    if check_source_first:
        logger.info("Checking source file for salary data...")
        # Check both salary and worksite records
        missing_salary_cases = list(
            existing_salary_records.values_list("case_number", flat=True)[:20]
        )
        missing_worksite_cases = (
            list(existing_worksite_records.values_list("case_number", flat=True)[:20])
            if total_worksite_to_update > 0
            else []
        )

        all_missing_cases = missing_salary_cases + missing_worksite_cases
        # Pass target case numbers to optimize index building (only index what we need)
        check_result = check_file_has_salary_data(
            filepath,
            all_missing_cases,
            sample_size=min(20, len(all_missing_cases)),
            target_case_numbers=set(all_missing_cases) if all_missing_cases else None,
        )

        logger.info("Source file check results:")
        logger.info(f"  Sample checked: {check_result['sample_checked']}")
        logger.info(f"  Found in source: {check_result['found_in_source']}")
        logger.info(f"  Case not found: {check_result['case_not_found']}")
        logger.info(f"  No salary data: {check_result['no_salary_data']}")

        # Show detailed results for first few
        if check_result["detailed_results"]:
            logger.info("  Sample detailed results:")
            for detail in check_result["detailed_results"][:5]:
                if detail["status"] == "found":
                    logger.info(
                        f"    {detail['case_number']}: FOUND - wage_from={detail.get('wage_from')}, unit={detail.get('wage_unit')}"
                    )
                else:
                    logger.info(
                        f"    {detail['case_number']}: NOT FOUND - reason={detail.get('reason', 'unknown')}"
                    )

        if not check_result["has_data"]:
            logger.warning(
                f"Source file does not appear to have salary data (checked {check_result['sample_checked']} samples)"
            )
            logger.warning("Skipping re-import - records should be dropped instead")
            return {
                "updated": 0,
                "errors": 0,
                "not_found": total_to_update,
                "dropped": 0,
                "source_has_data": False,
                "check_result": check_result,
            }
        else:
            logger.info(
                f"Source file has salary data (found in {check_result['found_in_source']}/{check_result['sample_checked']} samples)"
            )
            logger.info("Proceeding with re-import...")

    # Create or get DataSource for this file
    temp_url = f"reimport://{filepath}"
    source, created = DataSource.objects.get_or_create(
        url=temp_url,
        defaults={
            "domain": DataDomain.DOL.value,
            "source_type": source_type.value,
            "local_file_path": str(filepath),
        },
    )

    # Update local_file_path if it changed
    if not created and source.local_file_path != str(filepath):
        source.local_file_path = str(filepath)
        source.save(update_fields=["local_file_path"])

    # Create orchestrator with update mode
    # Note: WorksiteRecord updates are handled separately (orchestrator only handles SalaryRecord)
    orchestrator = PipelineOrchestrator(
        batch_size=1000,
        update_mode=True,
        update_fields=["wage_from", "wage_to", "wage_unit", "wage_annual"],
        update_filter={
            "source_file": filepath.name,
            "wage_annual__isnull": True,  # Only update records with missing salary
        },
    )

    # Ensure plugin is registered (in case registry was cleared)
    plugin = PluginRegistry.get_plugin(DataDomain.DOL, source_type)
    if not plugin:
        if source_type == SourceType.PERM:
            PluginRegistry.register(_perm_plugin)
        else:
            PluginRegistry.register(_lca_plugin)
        logger.debug(f"Registered {source_type.value} plugin")

    try:
        if dry_run:
            logger.info("[DRY RUN] Would run orchestrator to update records...")
            # In dry-run, we can't actually run the orchestrator, so just report
            return {
                "updated": 0,
                "errors": 0,
                "not_found": 0,
                "dropped": 0,
                "total": total_to_update,
                "salary_updated": 0,
                "worksite_updated": 0,
            }
        else:
            # Verify plugin is available before running
            plugin = PluginRegistry.get_plugin(source.domain, source.source_type)
            if not plugin:
                raise ValueError(
                    f"No plugin found for {source.domain}:{source.source_type}. "
                    f"Available plugins: {[p[0] + ':' + p[1] for p in PluginRegistry.list_plugins()]}"
                )

            # Run orchestrator with update mode (handles SalaryRecord)
            run = orchestrator.run(source, resume=False)

            # WorksiteRecord updates need to be handled separately
            # For now, we'll re-import worksite records by deleting and re-creating
            # (WorksiteRecord doesn't have update_mode support in orchestrator yet)
            worksite_updated = 0
            if total_worksite_to_update > 0:
                logger.info(
                    f"Re-importing {total_worksite_to_update:,} WorksiteRecord records..."
                )
                # Delete existing worksite records from this file
                deleted_count, _ = existing_worksite_records.delete()
                logger.info(f"Deleted {deleted_count:,} WorksiteRecord records")

                # Re-import using plugin (will create new WorksiteRecord records)
                plugin._current_run = run
                records = list(plugin.parse(filepath, run))
                for record in records:
                    transformed = plugin.transform(record)
                    if isinstance(transformed, WorksiteRecord):
                        try:
                            transformed.save()
                            worksite_updated += 1
                        except Exception as e:
                            logger.warning(f"Error saving WorksiteRecord: {e}")

            return {
                "updated": run.records_updated + worksite_updated,
                "errors": run.records_failed,
                "not_found": run.records_skipped,
                "total": total_to_update,
                "salary_updated": run.records_updated,
                "worksite_updated": worksite_updated,
            }
    finally:
        # Clean up temporary source if no other runs reference it
        if source.url.startswith("reimport://"):
            from models.ingest.ingest_run import IngestRun

            other_runs = IngestRun.objects.filter(source=source).exists()
            if not other_runs:
                source.delete()


def main():
    parser = argparse.ArgumentParser(
        description="Re-import salary data for records with missing salary data (PERM and LCA)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Dry-run on specific file:
    bazel run //scripts/salary:reimport_perm_salary_data -- --file PERM_FY2019.xlsx
  
  Actually update records:
    bazel run //scripts/salary:reimport_perm_salary_data -- --file PERM_FY2019.xlsx --fix
  
  Process all PERM files with missing data:
    bazel run //scripts/salary:reimport_perm_salary_data -- --all-files --fix
  
  Limit for testing:
    bazel run //scripts/salary:reimport_perm_salary_data -- --file PERM_FY2019.xlsx --limit 100
        """,
    )

    parser.add_argument(
        "--file", type=str, help="Specific PERM file to process (filename only)"
    )

    parser.add_argument(
        "--all-files",
        action="store_true",
        help="Process all PERM files with missing salary data",
    )

    parser.add_argument(
        "--fix",
        action="store_true",
        help="Actually update records (default is dry-run)",
    )

    parser.add_argument(
        "--limit",
        type=int,
        help="Limit number of records to process per file (for testing)",
    )

    parser.add_argument(
        "--check-source-files",
        action="store_true",
        help="Check source files first to verify salary data exists before re-importing",
    )

    parser.add_argument(
        "--drop-unfixable",
        action="store_true",
        help="Drop records that cannot be fixed (no salary data in source files)",
    )

    parser.add_argument(
        "--include-worksite",
        action="store_true",
        help="Also process WorksiteRecord records (salary is REQUIRED for worksite)",
    )

    args = parser.parse_args()

    script_logger.log_call(
        args={
            "file": args.file,
            "all_files": args.all_files,
            "fix": args.fix,
            "limit": args.limit,
            "check_source_files": args.check_source_files,
            "drop_unfixable": args.drop_unfixable,
            "include_worksite": args.include_worksite,
        },
        context="Re-importing salary data for records with missing salary data",
    )

    workspace_dir = get_workspace_dir()
    data_dir = workspace_dir / "data" / "salary" / "dol_data"

    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    mode_str = "[DRY RUN] " if not args.fix else ""
    logger.info("=" * 80)
    logger.info(f"{mode_str}RE-IMPORT SALARY DATA (Using Ingest Pipeline)")
    logger.info("=" * 80)
    logger.info("")
    logger.info("This script uses the ingest pipeline to:")
    logger.info("  1. Parse source files (reuses existing parsing logic)")
    logger.info("  2. Transform records (reuses existing transformation logic)")
    logger.info("  3. Update existing records with extracted salary data")
    if args.check_source_files:
        logger.info("  4. Check source files first to verify data exists")
    if args.drop_unfixable:
        logger.info("  5. Drop records that cannot be fixed")
    logger.info("")

    if args.all_files:
        # Get all files with missing data
        files_with_missing = get_files_with_missing_data()
        logger.info(f"Found {len(files_with_missing)} files with missing salary data")

        total_updated = 0
        total_errors = 0

        for source_file, missing_count, record_type in files_with_missing:
            # Skip worksite records unless explicitly requested
            if record_type == "worksite" and not args.include_worksite:
                continue

            filepath = data_dir / source_file
            if not filepath.exists():
                logger.warning(f"File not found: {source_file}")
                continue

            logger.info(
                f"\nProcessing {source_file} ({missing_count:,} {record_type} records with missing salary)..."
            )
            results = update_records_from_file(
                filepath,
                dry_run=not args.fix,
                limit=args.limit,
                check_source_first=args.check_source_files,
            )
            total_updated += results.get("updated", 0)
            total_errors += results.get("errors", 0)

        print(f"\n{'=' * 80}")
        print(f"{mode_str}SUMMARY")
        print(f"{'=' * 80}")
        print(f"Total records updated: {total_updated:,}")
        print(f"Total errors: {total_errors}")

    elif args.file:
        # Process specific file
        filepath = data_dir / args.file
        if not filepath.exists():
            # Try to find by partial name
            matching = list(data_dir.glob(f"*{args.file}*"))
            if matching:
                filepath = matching[0]
                logger.info(f"Found file: {filepath.name}")
            else:
                logger.error(f"File not found: {args.file}")
                sys.exit(1)

        results = update_records_from_file(
            filepath,
            dry_run=not args.fix,
            limit=args.limit,
            check_source_first=args.check_source_files,
        )

        print(f"\n{'=' * 80}")
        print(f"{mode_str}RESULTS")
        print(f"{'=' * 80}")
        print(f"Updated: {results['updated']:,}")
        print(f"Errors: {results['errors']}")
        print(f"Not found/still missing: {results['not_found']}")
        print(f"Total to update: {results['total']:,}")

        if not args.fix:
            print("\nTo actually update records, run with --fix flag")
    else:
        parser.print_help()
        sys.exit(1)

    # Drop unfixable records if requested
    if args.drop_unfixable:
        logger.info("\n" + "=" * 80)
        logger.info("DROPPING UNFIXABLE RECORDS")
        logger.info("=" * 80)

        # Drop SalaryRecord records without salary data
        unfixable_salary = SalaryRecord.objects.filter(
            Q(wage_annual__isnull=True) | Q(wage_annual=0), is_worksite=False
        ).filter(
            Q(wage_from__isnull=True)
            | Q(wage_from=0)
            | Q(wage_unit__isnull=True)
            | Q(wage_unit="")
        )
        salary_drop_count = unfixable_salary.count()

        # Drop WorksiteRecord records without salary data (salary is REQUIRED)
        unfixable_worksite = WorksiteRecord.objects.filter(
            Q(wage_annual__isnull=True) | Q(wage_annual=0)
        )
        worksite_drop_count = unfixable_worksite.count()

        if not args.fix:
            logger.info(
                f"[DRY RUN] Would drop {salary_drop_count:,} SalaryRecord and {worksite_drop_count:,} WorksiteRecord records"
            )
        else:
            with transaction.atomic():
                salary_deleted, _ = unfixable_salary.delete()
                worksite_deleted, _ = unfixable_worksite.delete()
                logger.info(
                    f"Dropped {salary_deleted:,} SalaryRecord and {worksite_deleted:,} WorksiteRecord records"
                )

    sys.exit(0)


if __name__ == "__main__":
    main()
