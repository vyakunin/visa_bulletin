#!/usr/bin/env python3
"""Check how many job title clusters are eligible for sitemap"""

import os

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.job_title import JobTitleCluster


def main():
    total = JobTitleCluster.objects.count()
    with_slugs = JobTitleCluster.objects.filter(slug__isnull=False).count()
    with_filings = JobTitleCluster.objects.filter(total_filings__gte=10).count()
    eligible = JobTitleCluster.objects.filter(
        slug__isnull=False,
        total_filings__gte=10
    ).count()

    print("Job Title Cluster Sitemap Eligibility")
    print("=" * 80)
    print(f"Total clusters: {total:,}")
    print(f"With slugs: {with_slugs:,}")
    print(f"With total_filings >= 10: {with_filings:,}")
    print(f"Eligible for sitemap (both): {eligible:,}")
    print("=" * 80)

    if eligible == 0:
        print("\n⚠️  No clusters eligible for sitemap!")
        print("The total_filings field on JobTitleCluster may need to be updated.")
        print("This field should be populated during clustering or via aggregation.")
    else:
        print(f"\n✅ {eligible:,} job title clusters will appear in sitemap")


if __name__ == '__main__':
    main()
