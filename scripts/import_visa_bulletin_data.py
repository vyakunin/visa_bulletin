#!/usr/bin/env python3
"""
Import visa bulletin data from CSV files to PostgreSQL database.

This script converts country string values to integer values and imports
bulletin and visa cutoff date data.

Usage:
    python3 import_visa_bulletin_data.py
"""

import csv
import os
import sys

import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
django.setup()

from django.db import transaction

from models.bulletin import Bulletin
from models.enums.country import Country
from models.visa_cutoff_date import VisaCutoffDate


def import_visa_bulletin_data(bulletin_csv: str, cutoff_csv: str):
    """Import visa bulletin data from CSV files"""

    print("Importing visa bulletin data...")
    print(f"Bulletin CSV: {bulletin_csv}")
    print(f"Cutoff CSV: {cutoff_csv}")

    with transaction.atomic():
        # Import bulletins
        print("\n1. Importing bulletins...")
        with open(bulletin_csv) as f:
            reader = csv.DictReader(f)
            bulletins_created = 0
            for row in reader:
                Bulletin.objects.get_or_create(
                    id=int(row['id']),
                    defaults={
                        'publication_date': row['publication_date'],
                        'fetched_at': row['fetched_at'],
                        'url': row['url'] if row['url'] else None,
                    }
                )
                bulletins_created += 1
        print(f"✅ Imported {bulletins_created} bulletins")

        # Import visa cutoff dates with country conversion
        print("\n2. Importing visa cutoff dates...")
        with open(cutoff_csv) as f:
            reader = csv.DictReader(f)
            cutoffs_created = 0
            for row in reader:
                # Convert country string to integer
                country_str = row['country']
                country_enum = Country.from_string(country_str)
                if country_enum is None:
                    print(f"WARNING: Unknown country '{country_str}', skipping row {row['id']}")
                    continue

                VisaCutoffDate.objects.get_or_create(
                    id=int(row['id']),
                    defaults={
                        'bulletin_id': int(row['bulletin_id']),
                        'visa_category': row['visa_category'],
                        'visa_class': row['visa_class'],
                        'action_type': row['action_type'],
                        'country': country_enum,
                        'cutoff_value': row['cutoff_value'],
                        'cutoff_date': row['cutoff_date'] if row['cutoff_date'] else None,
                        'is_current': row['is_current'] == '1',
                        'is_unavailable': row['is_unavailable'] == '1',
                    }
                )
                cutoffs_created += 1
        print(f"✅ Imported {cutoffs_created} visa cutoff dates")

    print("\n✅ Import completed successfully!")
    print("\nDatabase summary:")
    print(f"  Bulletins: {Bulletin.objects.count()}")
    print(f"  Visa Cutoff Dates: {VisaCutoffDate.objects.count()}")


if __name__ == '__main__':
    bulletin_csv = '/tmp/bulletin.csv'
    cutoff_csv = '/tmp/visa_cutoff_date.csv'

    if not os.path.exists(bulletin_csv):
        print(f"ERROR: Bulletin CSV not found: {bulletin_csv}")
        sys.exit(1)

    if not os.path.exists(cutoff_csv):
        print(f"ERROR: Cutoff CSV not found: {cutoff_csv}")
        sys.exit(1)

    import_visa_bulletin_data(bulletin_csv, cutoff_csv)
