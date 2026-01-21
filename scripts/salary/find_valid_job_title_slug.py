#!/usr/bin/env python3
"""Find valid job title slugs for testing"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.job_title import JobTitleCluster, JobTitle
from models.salary import SalaryRecord


def main():
    # Find clusters that have actual salary records
    clusters_with_data = []
    
    for cluster in JobTitleCluster.objects.filter(slug__isnull=False).order_by('-total_filings')[:50]:
        # Check if this cluster has salary records
        job_titles = JobTitle.objects.filter(canonical_cluster=cluster)
        record_count = SalaryRecord.objects.filter(
            job_title_entity__in=job_titles,
            wage_annual__isnull=False
        ).count()
        
        if record_count > 0:
            clusters_with_data.append((cluster.slug, cluster.canonical_title, record_count))
            if len(clusters_with_data) >= 10:
                break
    
    print("Top 10 job title clusters with salary data:")
    print("=" * 80)
    for slug, title, count in clusters_with_data:
        print(f"{slug:40} {title:30} ({count:,} records)")
    
    if clusters_with_data:
        print("\n" + "=" * 80)
        print(f"Test URL: http://localhost:8000/job-title/{clusters_with_data[0][0]}/")
        print("=" * 80)


if __name__ == '__main__':
    main()
