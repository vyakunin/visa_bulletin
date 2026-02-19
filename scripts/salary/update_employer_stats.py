#!/usr/bin/env python3
"""
Update Employer aggregated statistics (total_lca_count, total_perm_count, avg_salary).

This script calculates statistics from SalaryRecords for each Employer.
These stats are then summed by cluster_existing_employers to populate EmployerCluster stats.

Usage:
    bazel run //scripts/salary:update_employer_stats
    bazel run //scripts/salary:update_employer_stats -- --dry-run
"""

import logging
import os
import time

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

import argparse

from django.db.models import Avg, Count

from lib.utils.logging_utils import ScriptLogger
from models.enums.visa_program import VisaProgram
from models.salary import Employer, SalaryRecord

script_logger = ScriptLogger(__file__)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description='Update Employer aggregated statistics')
    parser.add_argument('--dry-run', action='store_true', help='Show what would be done without making changes')
    args = parser.parse_args()

    script_logger.log_call(
        args={'dry_run': args.dry_run},
        context='Update Employer aggregated statistics from SalaryRecords'
    )

    logger.info("Updating Employer statistics...")
    logger.info("=" * 80)

    total_employers = Employer.objects.count()
    logger.info(f"Total employers in database: {total_employers:,}")

    if args.dry_run:
        logger.info("DRY RUN - Showing sample of what would be updated:")

        # Show LCA counts sample
        lca_counts = (
            SalaryRecord.objects
            .filter(visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3])
            .values('employer_id', 'employer__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        logger.info("Top 10 employers by LCA count:")
        for item in lca_counts:
            logger.info(f"  {item['employer__name']}: {item['count']} LCA filings")

        # Show PERM counts sample
        perm_counts = (
            SalaryRecord.objects
            .filter(visa_program=VisaProgram.PERM)
            .values('employer_id', 'employer__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:10]
        )
        logger.info("Top 10 employers by PERM count:")
        for item in perm_counts:
            logger.info(f"  {item['employer__name']}: {item['count']} PERM filings")

        return

    # Pre-load all employer IDs for O(1) lookup (avoids N+1 queries)
    logger.info("Pre-loading employer IDs...")
    start_time = time.time()
    employer_ids = set(Employer.objects.values_list('id', flat=True))
    logger.info(f"Loaded {len(employer_ids):,} employer IDs in {time.time() - start_time:.1f}s")

    # Update LCA counts
    logger.info("Updating LCA counts...")
    start_time = time.time()
    lca_counts = list(
        SalaryRecord.objects
        .filter(visa_program__in=[VisaProgram.H1B, VisaProgram.H1B1, VisaProgram.E3])
        .values('employer_id')
        .annotate(count=Count('id'))
    )
    logger.info(f"  Aggregated {len(lca_counts):,} employer LCA counts in {time.time() - start_time:.1f}s")

    start_time = time.time()
    lca_updates = []
    skipped = 0
    for item in lca_counts:
        emp_id = item['employer_id']
        if emp_id and emp_id in employer_ids:
            lca_updates.append((emp_id, item['count']))
        else:
            skipped += 1

    # Bulk update using raw SQL for speed
    if lca_updates:
        from django.db import connection
        with connection.cursor() as cursor:
            # Update in batches of 1000
            batch_size = 1000
            for i in range(0, len(lca_updates), batch_size):
                batch = lca_updates[i:i + batch_size]
                # Build CASE statement for batch update
                case_sql = " ".join(f"WHEN {emp_id} THEN {count}" for emp_id, count in batch)
                ids = ",".join(str(emp_id) for emp_id, _ in batch)
                cursor.execute(f"""
                    UPDATE salary_employer 
                    SET total_lca_count = CASE id {case_sql} END
                    WHERE id IN ({ids})
                """)
                if (i + batch_size) % 10000 == 0 or i + batch_size >= len(lca_updates):
                    logger.info(f"  Updated {min(i + batch_size, len(lca_updates)):,}/{len(lca_updates):,} LCA counts...")

    logger.info(f"Updated LCA counts for {len(lca_updates):,} employers in {time.time() - start_time:.1f}s (skipped {skipped})")

    # Update PERM counts
    logger.info("Updating PERM counts...")
    start_time = time.time()
    perm_counts = list(
        SalaryRecord.objects
        .filter(visa_program=VisaProgram.PERM)
        .values('employer_id')
        .annotate(count=Count('id'))
    )
    logger.info(f"  Aggregated {len(perm_counts):,} employer PERM counts in {time.time() - start_time:.1f}s")

    start_time = time.time()
    perm_updates = []
    skipped = 0
    for item in perm_counts:
        emp_id = item['employer_id']
        if emp_id and emp_id in employer_ids:
            perm_updates.append((emp_id, item['count']))
        else:
            skipped += 1

    # Bulk update using raw SQL for speed
    if perm_updates:
        from django.db import connection
        with connection.cursor() as cursor:
            batch_size = 1000
            for i in range(0, len(perm_updates), batch_size):
                batch = perm_updates[i:i + batch_size]
                case_sql = " ".join(f"WHEN {emp_id} THEN {count}" for emp_id, count in batch)
                ids = ",".join(str(emp_id) for emp_id, _ in batch)
                cursor.execute(f"""
                    UPDATE salary_employer 
                    SET total_perm_count = CASE id {case_sql} END
                    WHERE id IN ({ids})
                """)
                if (i + batch_size) % 10000 == 0 or i + batch_size >= len(perm_updates):
                    logger.info(f"  Updated {min(i + batch_size, len(perm_updates)):,}/{len(perm_updates):,} PERM counts...")

    logger.info(f"Updated PERM counts for {len(perm_updates):,} employers in {time.time() - start_time:.1f}s (skipped {skipped})")

    # Update average salary
    logger.info("Updating average salaries...")
    start_time = time.time()
    avg_salaries = list(
        SalaryRecord.objects
        .filter(wage_annual__isnull=False, wage_annual__gt=0)
        .values('employer_id')
        .annotate(avg=Avg('wage_annual'))
    )
    logger.info(f"  Aggregated {len(avg_salaries):,} employer avg salaries in {time.time() - start_time:.1f}s")

    start_time = time.time()
    salary_updates = []
    skipped = 0
    for item in avg_salaries:
        emp_id = item['employer_id']
        if emp_id and emp_id in employer_ids:
            salary_updates.append((emp_id, float(item['avg'])))
        else:
            skipped += 1

    # Bulk update using raw SQL for speed
    if salary_updates:
        from django.db import connection
        with connection.cursor() as cursor:
            batch_size = 1000
            for i in range(0, len(salary_updates), batch_size):
                batch = salary_updates[i:i + batch_size]
                case_sql = " ".join(f"WHEN {emp_id} THEN {avg:.2f}" for emp_id, avg in batch)
                ids = ",".join(str(emp_id) for emp_id, _ in batch)
                cursor.execute(f"""
                    UPDATE salary_employer 
                    SET avg_salary = CASE id {case_sql} END
                    WHERE id IN ({ids})
                """)
                if (i + batch_size) % 10000 == 0 or i + batch_size >= len(salary_updates):
                    logger.info(f"  Updated {min(i + batch_size, len(salary_updates)):,}/{len(salary_updates):,} avg salaries...")

    logger.info(f"Updated avg salaries for {len(salary_updates):,} employers in {time.time() - start_time:.1f}s (skipped {skipped})")

    logger.info("=" * 80)
    logger.info("Employer statistics updated successfully!")
    logger.info(f"  LCA counts: {len(lca_updates):,} employers")
    logger.info(f"  PERM counts: {len(perm_updates):,} employers")
    logger.info(f"  Avg salaries: {len(salary_updates):,} employers")


if __name__ == '__main__':
    main()
