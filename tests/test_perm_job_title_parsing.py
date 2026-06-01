"""Test PERM job_title parsing bug"""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

import django

django.setup()

import unittest

from lib.parsing.salary.db_importer import PERM_COLUMN_MAPPINGS, get_column_value


class TestPermJobTitleParsing(unittest.TestCase):
    """Test that PERM job_title is parsed correctly from raw data"""

    def test_job_title_from_job_title_column(self):
        """Test that JOB_TITLE column is parsed correctly"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "JOB_TITLE": "PERSONAL AND HOME CARE AIDES",
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNotNone(job_title, "job_title should be found")
        self.assertEqual(job_title, "PERSONAL AND HOME CARE AIDES")

    def test_job_title_from_pw_job_title_9089(self):
        """Test that PW_JOB_TITLE_9089 column is parsed correctly"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "PW_JOB_TITLE_9089": "PERSONAL AND HOME CARE AIDES",
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNotNone(job_title, "job_title should be found")
        self.assertEqual(job_title, "PERSONAL AND HOME CARE AIDES")

    def test_job_title_fallback_to_unknown(self):
        """Test that missing job_title returns None (which becomes 'Unknown')"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
            # No job_title columns
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNone(job_title, "job_title should be None when missing")

    def test_job_title_with_whitespace(self):
        """Test that job_title with whitespace is handled correctly"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "JOB_TITLE": "  PERSONAL AND HOME CARE AIDES  ",
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNotNone(job_title)
        self.assertEqual(
            job_title, "PERSONAL AND HOME CARE AIDES"
        )  # Should be stripped

    def test_job_title_empty_string(self):
        """Test that empty job_title string is treated as missing"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "JOB_TITLE": "",
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNone(job_title, "Empty string should return None")

    def test_job_title_priority_order(self):
        """Test that PW_JOB_TITLE_9089 is preferred over empty JOB_TITLE"""
        row = {
            "CASE_NUMBER": "C-08065-30360",
            "JOB_TITLE": "",  # Empty
            "PW_JOB_TITLE_9089": "PERSONAL AND HOME CARE AIDES",  # Has value
            "EMPLOYER_NAME": "SALUS HEALTHCARE",
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS["job_title"])
        self.assertIsNotNone(
            job_title, "Should find PW_JOB_TITLE_9089 when JOB_TITLE is empty"
        )
        self.assertEqual(
            job_title,
            "PERSONAL AND HOME CARE AIDES",
            "Should use PW_JOB_TITLE_9089 value",
        )


class TestPermFy2026ColumnScheme(unittest.TestCase):
    """Regression: FY2026 revised PERM (ETA-9089) files renamed columns to the
    EMP_*/PWD_* scheme. The importer only knew EMPLOYER_*/PW_*, so every row
    failed the required 'employer_name' lookup and was skipped -> 0 records
    ingested from perm_disclosure_data_fy2026_q2.xlsx.
    """

    def _fy2026_row(self):
        # Header subset taken verbatim from perm_disclosure_data_fy2026_q2.xlsx.
        return {
            "CASE_NUMBER": "A-26042-633112",
            "CASE_STATUS": "CERTIFIED",
            "EMP_BUSINESS_NAME": "ACME ROBOTICS INC",
            "EMP_CITY": "MOUNTAIN VIEW",
            "EMP_STATE": "CA",
            "JOB_TITLE": "SOFTWARE DEVELOPER",
            "PWD_SOC_CODE": "15-1252",
            "PWD_SOC_TITLE": "Software Developers",
            "JOB_OPP_WAGE_FROM": "150000",
            "JOB_OPP_WAGE_PER": "Year",
        }

    def test_employer_name_resolves_from_emp_business_name(self):
        row = self._fy2026_row()
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["employer_name"]),
            "ACME ROBOTICS INC",
            "FY2026 EMP_BUSINESS_NAME must map to employer_name (else row skipped -> 0 records)",
        )

    def test_employer_city_state_resolve_from_emp_columns(self):
        row = self._fy2026_row()
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["employer_city"]), "MOUNTAIN VIEW"
        )
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["employer_state"]), "CA"
        )

    def test_soc_resolves_from_pwd_columns(self):
        row = self._fy2026_row()
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["soc_code"]), "15-1252"
        )
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["soc_title"]),
            "Software Developers",
        )

    def test_legacy_employer_name_still_resolves(self):
        # Backward-compat: pre-FY2026 files must keep working.
        row = {"EMPLOYER_NAME": "SALUS HEALTHCARE"}
        self.assertEqual(
            get_column_value(row, PERM_COLUMN_MAPPINGS["employer_name"]),
            "SALUS HEALTHCARE",
        )


if __name__ == "__main__":
    unittest.main()
