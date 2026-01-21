#!/usr/bin/env python3
"""Get sample job title URLs for testing"""

import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()

from models.job_title import JobTitle
from django.utils.text import slugify

# Get a few common job titles with high filing counts
titles = JobTitle.objects.filter(total_filings__gt=100).order_by('-total_filings')[:5]

print("Sample job title URLs to test:")
print("=" * 60)
for title in titles:
    slug = slugify(title.title)
    print(f"\nURL: http://localhost:8000/job-title/{slug}/")
    print(f"  Title: {title.title}")
    print(f"  Normalized: {title.title_normalized}")
    print(f"  Experience Level: {title.experience_level or 'None'}")
    print(f"  Total Filings: {title.total_filings:,}")
