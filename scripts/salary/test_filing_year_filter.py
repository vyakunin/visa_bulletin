import os
import sys

import django

# Setup Django
sys.path.append(os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
django.setup()


from lib.utils.filter_utils import apply_filing_year_filter
from models.salary import SalaryRecord


def test_filing_year_filter():
    print("Testing apply_filing_year_filter...")

    # Get a year that has data (using case_submitted__year)
    years_with_data = SalaryRecord.objects.exclude(case_submitted__isnull=True).dates(
        "case_submitted", "year"
    )
    if not years_with_data:
        print("No data with case_submitted found yet. Script might still be running.")
        return

    test_year = years_with_data[0].year
    print(f"Testing with year: {test_year}")

    qs = SalaryRecord.objects.all()
    filtered_qs = apply_filing_year_filter(qs, test_year)

    count = filtered_qs.count()
    print(f"Found {count} records for year {test_year}")

    # Verify
    invalid_records = filtered_qs.exclude(case_submitted__year=test_year)
    if invalid_records.exists():
        print("FAILED: Found records with wrong year!")
    else:
        print("SUCCESS: All records have correct year.")

    # Test invalid input
    print("Testing invalid input...")
    qs = apply_filing_year_filter(qs, "invalid")
    if qs.count() == SalaryRecord.objects.count():
        print("SUCCESS: Invalid input returned full queryset.")
    else:
        print("FAILED: Invalid input affected queryset.")


if __name__ == "__main__":
    test_filing_year_filter()
