#!/usr/bin/env python3
"""
Check status of job title integration.

Usage:
    bazel run //scripts/salary:check_job_title_status
"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.job_title import JobTitle, JobTitleCluster
from models.salary import SalaryRecord


def main():
    total_records = SalaryRecord.objects.count()
    linked_records = SalaryRecord.objects.filter(job_title_entity__isnull=False).count()
    unlinked_records = SalaryRecord.objects.filter(job_title_entity__isnull=True).count()

    print("="*80)
    print("Job Title Integration Status")
    print("="*80)
    print(f"Total SalaryRecords: {total_records:,}")
    print(f"Linked to JobTitle: {linked_records:,} ({linked_records*100.0/total_records:.1f}%)")
    print(f"Not linked: {unlinked_records:,} ({unlinked_records*100.0/total_records:.1f}%)")
    print()

    job_title_count = JobTitle.objects.count()
    clustered_titles = JobTitle.objects.filter(canonical_cluster__isnull=False).count()
    unclustered_titles = JobTitle.objects.filter(canonical_cluster__isnull=True).count()

    print(f"Total JobTitle entities: {job_title_count:,}")
    print(f"Clustered: {clustered_titles:,} ({clustered_titles*100.0/job_title_count:.1f}%)")
    print(f"Not clustered: {unclustered_titles:,} ({unclustered_titles*100.0/job_title_count:.1f}%)")
    print()

    cluster_count = JobTitleCluster.objects.count()
    print(f"Total JobTitleClusters: {cluster_count:,}")

    print("\n" + "="*80)
    print("Tasks Status:")
    print("="*80)
    print(f"✅ Backfill SalaryRecords: {'DONE' if linked_records > 0 else 'NOT DONE'}")
    print(f"{'✅' if clustered_titles > 0 else '❌'} Clustering: {'DONE' if clustered_titles > 0 else 'NOT DONE'}")

    # Check if views are integrated by checking files directly
    # Use BUILD_WORKSPACE_DIRECTORY if available (Bazel), otherwise resolve relative to script
    workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY')
    if not workspace_dir:
        # Fallback: go up from scripts/salary/ to project root
        script_dir = os.path.dirname(os.path.abspath(__file__))
        workspace_dir = os.path.dirname(os.path.dirname(script_dir))

    views_file = os.path.join(workspace_dir, 'webapp', 'views.py')
    urls_file = os.path.join(workspace_dir, 'webapp', 'urls.py')
    template_file = os.path.join(workspace_dir, 'webapp', 'templates', 'webapp', 'job_title_profile.html')

    views_done = (
        os.path.exists(views_file) and
        'job_title_profile_view' in open(views_file).read() and
        os.path.exists(urls_file) and
        'job-title' in open(urls_file).read() and
        os.path.exists(template_file)
    )

    print(f"{'✅' if views_done else '❌'} Views integration: {'DONE' if views_done else 'NOT DONE'}")


if __name__ == '__main__':
    main()

