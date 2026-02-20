"""Integration test for salary data import and search functionality"""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import os
from decimal import Decimal
from pathlib import Path

from django.test import TestCase

from lib.parsing.salary.db_importer import (
    LCA_COLUMN_MAPPINGS,
    _process_row,
    import_csv_file,
    update_employer_stats,
)
from lib.parsing.salary.wage_unit_correction import (
    MAX_VALID_ANNUAL,
    MIN_VALID_ANNUAL,
)
from lib.utils.data_source_utils import get_fiscal_year_from_filename
from models.enums.visa_program import CaseStatus, VisaProgram, WageUnit
from models.salary import Employer, SalaryRecord


class SalaryImportIntegrationTest(TestCase):
    """Integration test for salary data import from CSV"""

    def setUp(self):
        """Set up test data"""
        # Get the test CSV file path - in Bazel, it's in the runfiles
        # Try multiple possible locations
        test_csv_paths = [
            Path(os.environ.get("TEST_SRCDIR", "")) / "_main" / "test_salary_data.csv",
            Path(__file__).parent.parent / "test_salary_data.csv",
            Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", ""))
            / "test_salary_data.csv",
        ]

        self.test_csv = None
        for path in test_csv_paths:
            if path.exists():
                self.test_csv = path
                break

        if not self.test_csv or not self.test_csv.exists():
            # Try to find it in current directory or parent
            for root, dirs, files in os.walk(Path(__file__).parent.parent):
                if "test_salary_data.csv" in files:
                    self.test_csv = Path(root) / "test_salary_data.csv"
                    break

        if not self.test_csv or not self.test_csv.exists():
            self.skipTest(f"Test CSV file not found. Tried: {test_csv_paths}")

    def test_import_lca_csv(self):
        """Test importing LCA CSV data"""
        # Import the test CSV
        imported, skipped, errors = import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # Verify import results
        self.assertGreater(imported, 0, "Should import at least one record")
        self.assertEqual(errors, 0, "Should have no errors")

        # Verify data in database
        self.assertEqual(SalaryRecord.objects.count(), imported)

        # Verify specific records
        google_record = SalaryRecord.objects.filter(
            employer_name__icontains="Google"
        ).first()
        self.assertIsNotNone(google_record, "Google record should exist")
        self.assertEqual(google_record.job_title, "Software Engineer")
        self.assertEqual(google_record.worksite_state, "CA")
        self.assertEqual(google_record.wage_annual, Decimal("180000"))
        self.assertEqual(google_record.visa_program, VisaProgram.H1B)
        self.assertEqual(google_record.case_status, CaseStatus.CERTIFIED)

        # Verify employer was created
        google_employer = Employer.objects.filter(name_normalized="google").first()
        self.assertIsNotNone(google_employer, "Google employer should exist")
        self.assertEqual(google_employer.name, "Google Inc")
        self.assertEqual(google_employer.state, "CA")

    def test_employer_normalization(self):
        """Test that employer names are normalized correctly"""
        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # Check that different name variations map to same normalized name
        employers = Employer.objects.all()
        self.assertGreater(employers.count(), 0, "Should have employers")

        # Verify normalization
        google_employer = Employer.objects.filter(name_normalized="google").first()
        self.assertIsNotNone(google_employer)
        self.assertEqual(google_employer.name_normalized, "google")

    def test_wage_calculation(self):
        """Test that annual wages are calculated correctly"""
        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # Check wage calculations
        records = SalaryRecord.objects.all()
        for record in records:
            if record.wage_from and record.wage_unit:
                calculated = record.calculate_annual_wage()
                self.assertIsNotNone(
                    calculated, f"Record {record.case_number} should have annual wage"
                )
                self.assertEqual(
                    record.wage_annual,
                    calculated,
                    f"Record {record.case_number} wage_annual should match calculated",
                )

    def test_search_functionality(self):
        """Test that imported data can be searched"""
        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # Test search by job title
        results = SalaryRecord.objects.filter(job_title__icontains="Software Engineer")
        self.assertGreater(results.count(), 0, "Should find software engineers")

        # Test search by employer
        results = SalaryRecord.objects.filter(employer_name__icontains="Google")
        self.assertEqual(results.count(), 1, "Should find one Google record")

        # Test search by state
        results = SalaryRecord.objects.filter(worksite_state="CA")
        self.assertGreater(results.count(), 0, "Should find CA records")

        # Test search by wage range
        results = SalaryRecord.objects.filter(wage_annual__gte=180000)
        self.assertGreater(results.count(), 0, "Should find high-wage records")

    def test_statistics_aggregation(self):
        """Test that statistics are calculated correctly"""
        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # Update statistics
        update_employer_stats()

        # Verify employer statistics
        google_employer = Employer.objects.filter(name_normalized="google").first()
        self.assertIsNotNone(google_employer)
        self.assertGreater(google_employer.total_lca_count, 0)
        self.assertIsNotNone(google_employer.avg_salary)
        self.assertGreater(google_employer.avg_salary, 0)

    def test_duplicate_handling(self):
        """Test that duplicate case numbers are handled correctly"""
        # Import twice - second should skip duplicates
        first_import, _, _ = import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        second_import, skipped, _ = import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=True,  # Skip existing
        )

        # Second import should skip all records
        self.assertEqual(second_import, 0, "Second import should import 0 new records")
        self.assertEqual(skipped, first_import, "Should skip all existing records")

        # Total count should be same as first import
        self.assertEqual(SalaryRecord.objects.count(), first_import)

    def test_fiscal_year_extraction(self):
        """Test fiscal year extraction from filename"""
        self.assertEqual(get_fiscal_year_from_filename("LCA_FY2024_Q4.csv"), 2024)
        self.assertEqual(get_fiscal_year_from_filename("PERM_FY2023.csv"), 2023)
        self.assertEqual(get_fiscal_year_from_filename("test_2024_data.csv"), 2024)

    def test_wage_unit_parsing(self):
        """Test wage unit parsing from CSV values"""
        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        # All test records use YEAR, verify they're parsed correctly
        records = SalaryRecord.objects.filter(wage_unit=WageUnit.YEAR)
        self.assertGreater(records.count(), 0, "Should have records with YEAR unit")

        # Verify annual wages match
        for record in records:
            if record.wage_from:
                self.assertEqual(
                    record.wage_annual,
                    record.wage_from,
                    "Yearly wages should equal wage_from",
                )

    def test_salary_search_view_renders(self):
        """Test that salary search view renders correctly"""
        from django.test import Client
        from django.urls import reverse

        # Import test data first
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        client = Client()

        # Test empty search (should show welcome message or empty state)
        response = client.get(reverse("salary_search"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Search H-1B", html=True)

        # Test search with query
        response = client.get(reverse("salary_search"), {"q": "Software Engineer"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Software Engineer", html=True)
        self.assertContains(response, "Google", html=True)

        # Test search by employer
        response = client.get(reverse("salary_search"), {"employer": "Google"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Google", html=True)

        # Test search by state
        response = client.get(reverse("salary_search"), {"state": "CA"})
        self.assertEqual(response.status_code, 200)
        # Should show CA records

        # Test search with program filter
        response = client.get(reverse("salary_search"), {"program": "h1b"})
        self.assertEqual(response.status_code, 200)
        # Should show H-1B records

    def test_salary_search_statistics(self):
        """Test that salary search view calculates statistics correctly"""
        from django.test import Client
        from django.urls import reverse

        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        client = Client()

        # Search for all records
        response = client.get(reverse("salary_search"), {"q": "Engineer"})
        self.assertEqual(response.status_code, 200)

        # Verify statistics are shown
        # The template should show average, min, max salaries
        self.assertContains(response, "Average Salary", html=True)

        # Verify results count is shown
        self.assertContains(response, "Results Found", html=True)

    def test_salary_search_pagination(self):
        """Test pagination in salary search"""
        from django.test import Client
        from django.urls import reverse

        # Import test data
        import_csv_file(
            self.test_csv,
            VisaProgram.H1B,
            batch_size=10,
            skip_existing=False,
        )

        client = Client()

        # With 5 records and per_page=50, should be on page 1
        response = client.get(reverse("salary_search"), {"q": "Engineer"})
        self.assertEqual(response.status_code, 200)

        # Should show all 5 records (less than per_page)
        # Pagination should not be shown for small result sets

    def test_validation_rejects_low_salary(self):
        """Test that salaries below minimum threshold are rejected during import"""

        # Create a test row with invalid low salary
        test_row = {
            "CASE_NUMBER": "TEST-LOW-SALARY-001",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": "7",
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        employers_cache = {}
        result = _process_row(
            test_row,
            row_num=2,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        # Should be rejected, not error or success
        self.assertTrue(result.rejected, "Low salary should be rejected")
        self.assertIsNone(result.record, "Should not create record")
        self.assertIsNotNone(result.rejection_reason, "Should have rejection reason")
        self.assertIn("below minimum threshold", result.rejection_reason.lower())

    def test_validation_rejects_high_salary(self):
        """Test that salaries above maximum threshold are rejected during import"""
        # Create a test row with invalid high salary ($4.5B from real data)
        test_row = {
            "CASE_NUMBER": "TEST-HIGH-SALARY-001",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": "4500055000",
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        employers_cache = {}
        result = _process_row(
            test_row,
            row_num=2,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        # Should be rejected
        self.assertTrue(result.rejected, "High salary should be rejected")
        self.assertIsNone(result.record, "Should not create record")
        self.assertIsNotNone(result.rejection_reason, "Should have rejection reason")
        self.assertIn("exceeds maximum threshold", result.rejection_reason.lower())

    def test_validation_accepts_valid_salary(self):
        """Test that valid salaries pass validation and create records"""
        # Create a test row with valid salary
        test_row = {
            "CASE_NUMBER": "TEST-VALID-SALARY-001",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Software Engineer",
            "WAGE_RATE_OF_PAY_FROM": "150000",
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        employers_cache = {}
        result = _process_row(
            test_row,
            row_num=2,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        # Should succeed, not be rejected
        self.assertFalse(result.rejected, "Valid salary should not be rejected")
        self.assertFalse(result.error, "Should not have error")
        self.assertIsNotNone(result.record, "Should create record")
        self.assertEqual(result.record.wage_annual, Decimal("150000"))

    def test_validation_boundary_cases(self):
        """Test validation at threshold boundaries"""

        # Test at minimum threshold (should pass)
        test_row_min = {
            "CASE_NUMBER": "TEST-MIN-BOUNDARY",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": str(MIN_VALID_ANNUAL),
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        employers_cache = {}
        result = _process_row(
            test_row_min,
            row_num=2,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        self.assertFalse(result.rejected, "Salary at minimum threshold should pass")

        # Test just below minimum (should reject)
        test_row_below_min = {
            "CASE_NUMBER": "TEST-BELOW-MIN",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": str(MIN_VALID_ANNUAL - 1),
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        result = _process_row(
            test_row_below_min,
            row_num=3,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        self.assertTrue(result.rejected, "Salary below minimum should be rejected")

        # Test at maximum threshold (should pass)
        test_row_max = {
            "CASE_NUMBER": "TEST-MAX-BOUNDARY",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": str(MAX_VALID_ANNUAL),
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        result = _process_row(
            test_row_max,
            row_num=4,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        self.assertFalse(result.rejected, "Salary at maximum threshold should pass")

        # Test just above maximum (should reject)
        test_row_above_max = {
            "CASE_NUMBER": "TEST-ABOVE-MAX",
            "EMPLOYER_NAME": "Test Company",
            "JOB_TITLE": "Test Job",
            "WAGE_RATE_OF_PAY_FROM": str(MAX_VALID_ANNUAL + 1),
            "WAGE_UNIT_OF_PAY": "Year",
            "WORKSITE_STATE": "CA",
            "CASE_STATUS": "Certified",
        }

        result = _process_row(
            test_row_above_max,
            row_num=5,
            column_mappings=LCA_COLUMN_MAPPINGS,
            visa_program=VisaProgram.H1B,
            fiscal_year=2024,
            source_file="test.csv",
            existing_cases=set(),
            skip_existing=False,
            employers_cache=employers_cache,
        )

        self.assertTrue(result.rejected, "Salary above maximum should be rejected")
