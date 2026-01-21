#!/usr/bin/env python3
"""Debug job title data to see why charts are empty"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.job_title import JobTitleCluster
from models.salary import SalaryRecord
from datetime import datetime


def main():
    # Find a cluster with data
    cluster = JobTitleCluster.objects.filter(slug='server').first()
    if not cluster:
        print("Cluster 'server' not found")
        return
    
    print(f"Cluster: {cluster.canonical_title}")
    print("=" * 80)
    
    # Check year range
    current_year = datetime.now().year
    years = 5
    start_year = current_year - years
    
    print(f"Current year: {current_year}")
    print(f"Years to show: {years}")
    print(f"Start year: {start_year}")
    print()
    
    # Get all records for this cluster
    all_records = SalaryRecord.objects.filter(
        job_title_entity__canonical_cluster=cluster,
        wage_annual__isnull=False,
        wage_annual__gt=0,
    )
    
    print(f"Total records (all time): {all_records.count()}")
    
    # Check fiscal year distribution
    fiscal_years = all_records.values('fiscal_year').annotate(
        count=Count('id')
    ).order_by('fiscal_year')
    
    print("\nFiscal year distribution (all time):")
    for fy in fiscal_years[:20]:
        print(f"  FY {fy['fiscal_year']}: {fy['count']:,} records")
    
    # Check filtered records
    filtered_records = all_records.filter(fiscal_year__gte=start_year)
    print(f"\nFiltered records (FY >= {start_year}): {filtered_records.count()}")
    
    # Check yoy_trends data
    yoy_trends = list(
        filtered_records
        .values('fiscal_year')
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
        )
        .order_by('fiscal_year')
    )
    
    print(f"\nYear-over-year trends data: {len(yoy_trends)} years")
    for trend in yoy_trends:
        print(f"  FY {trend['fiscal_year']}: {trend['count']:,} filings, ${trend['median_salary']:,.0f} median")
    
    # Check geographic data
    geo_data = list(
        filtered_records
        .exclude(worksite_state='')
        .values('worksite_state')
        .annotate(
            count=Count('id'),
            median_salary=Avg('wage_annual'),
        )
        .order_by('-count')[:10]
    )
    
    print(f"\nGeographic data: {len(geo_data)} states")
    for geo in geo_data:
        print(f"  {geo['worksite_state']}: {geo['count']:,} filings, ${geo['median_salary']:,.0f} median")


if __name__ == '__main__':
    from django.db.models import Count, Avg
    main()
