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
            'CASE_NUMBER': 'C-08065-30360',
            'JOB_TITLE': 'PERSONAL AND HOME CARE AIDES',
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNotNone(job_title, "job_title should be found")
        self.assertEqual(job_title, 'PERSONAL AND HOME CARE AIDES')

    def test_job_title_from_pw_job_title_9089(self):
        """Test that PW_JOB_TITLE_9089 column is parsed correctly"""
        row = {
            'CASE_NUMBER': 'C-08065-30360',
            'PW_JOB_TITLE_9089': 'PERSONAL AND HOME CARE AIDES',
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNotNone(job_title, "job_title should be found")
        self.assertEqual(job_title, 'PERSONAL AND HOME CARE AIDES')

    def test_job_title_fallback_to_unknown(self):
        """Test that missing job_title returns None (which becomes 'Unknown')"""
        row = {
            'CASE_NUMBER': 'C-08065-30360',
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
            # No job_title columns
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNone(job_title, "job_title should be None when missing")

    def test_job_title_with_whitespace(self):
        """Test that job_title with whitespace is handled correctly"""
        row = {
            'CASE_NUMBER': 'C-08065-30360',
            'JOB_TITLE': '  PERSONAL AND HOME CARE AIDES  ',
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNotNone(job_title)
        self.assertEqual(job_title, 'PERSONAL AND HOME CARE AIDES')  # Should be stripped

    def test_job_title_empty_string(self):
        """Test that empty job_title string is treated as missing"""
        row = {
            'CASE_NUMBER': 'C-08065-30360',
            'JOB_TITLE': '',
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNone(job_title, "Empty string should return None")

    def test_job_title_priority_order(self):
        """Test that PW_JOB_TITLE_9089 is preferred over empty JOB_TITLE"""
        row = {
            'CASE_NUMBER': 'C-08065-30360',
            'JOB_TITLE': '',  # Empty
            'PW_JOB_TITLE_9089': 'PERSONAL AND HOME CARE AIDES',  # Has value
            'EMPLOYER_NAME': 'SALUS HEALTHCARE',
        }

        job_title = get_column_value(row, PERM_COLUMN_MAPPINGS['job_title'])
        self.assertIsNotNone(job_title, "Should find PW_JOB_TITLE_9089 when JOB_TITLE is empty")
        self.assertEqual(job_title, 'PERSONAL AND HOME CARE AIDES', "Should use PW_JOB_TITLE_9089 value")


if __name__ == '__main__':
    unittest.main()

