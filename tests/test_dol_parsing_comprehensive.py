#!/usr/bin/env python3
"""
Comprehensive smoke test for DoL file parsing - covers all format variations.

Tests parsing logic by validating transform() on representative sample rows from each
file format type (LCA, PERM, Worksites, Appendix A) across different fiscal years.

Unlike test_dol_parsing_smoke.py which tests actual files, this test uses hardcoded
sample data so it can run in CI without requiring the full data directory.
"""

import os
import unittest
from enum import Enum

# Setup Django
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')

import django
django.setup()

from lib.ingest.registry import PluginRegistry
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from models.ingest.data_source import DataSource
from models.ingest.ingest_run import IngestRun
from models.ingest.enums import IngestStatus, IngestStage, DataDomain, SourceType
from models.salary import SalaryRecord, WorksiteRecord


class ExpectedOutputType(Enum):
    """Expected output type from transform()"""
    SALARY_RECORD = 'salary_record'
    WORKSITE_RECORD = 'worksite_record'
    NONE = 'none'  # Supplemental data that returns None


class TestDolParsingComprehensive(unittest.TestCase):
    """Comprehensive smoke test covering all DoL file format variations"""

    @classmethod
    def setUpClass(cls):
        """Register plugins once for all tests"""
        PluginRegistry.register(H1BSalaryDataSourcePlugin(skip_clustering=True))
        PluginRegistry.register(PERMSalaryDataSourcePlugin(skip_clustering=True))

    def _test_transform(self, domain: DataDomain, source_type: SourceType, filename: str, 
                       sample_row: dict, expect_type: ExpectedOutputType):
        """
        Test transform() on a sample row.
        
        Args:
            domain: DataDomain enum value
            source_type: SourceType enum value
            filename: Source filename (for fiscal year extraction)
            sample_row: Sample row data
            expect_type: ExpectedOutputType enum value
        """
        plugin = PluginRegistry.get_plugin(domain, source_type)
        self.assertIsNotNone(plugin, f'No plugin found for {domain}:{source_type}')
        
        # Create mock source and run
        mock_source = DataSource(
            url=f'file://test/{filename}',
            domain=domain,
            source_type=source_type,
            local_file_path=f'/test/{filename}'
        )
        
        mock_run = IngestRun(
            source=mock_source,
            status=IngestStatus.RUNNING,
            stage=IngestStage.PARSING,
            checkpoint={'filepath': f'/test/{filename}'}
        )
        
        # Set run context
        plugin._current_run = mock_run
        
        # Transform the sample row
        result = None
        try:
            result = plugin.transform(sample_row)
        except Exception as e:
            self.fail(f"Transform failed for {filename}: {e}")
        
        # Validate based on expected type
        if expect_type == ExpectedOutputType.SALARY_RECORD:
            self.assertIsInstance(result, SalaryRecord, 
                                f"{filename} should return SalaryRecord")
            self.assertIsNotNone(result.case_number, 
                               f"{filename}: Missing case_number")
            self.assertIsNotNone(result.job_title, 
                               f"{filename}: Missing job_title")
        elif expect_type == ExpectedOutputType.WORKSITE_RECORD:
            self.assertIsInstance(result, WorksiteRecord, 
                                f"{filename} should return WorksiteRecord")
            self.assertIsNotNone(result.case_number, 
                               f"{filename}: Missing case_number")
        elif expect_type == ExpectedOutputType.NONE:
            self.assertIsNone(result,
                            f"{filename} should return None (supplemental data)")
        else:
            self.fail(f"Invalid expect_type: {expect_type}")

    # === LCA FORMATS ===
    
    def test_lca_fy2009_format(self):
        """Test very old LCA format (FY2009)"""
        sample_row = {
            'CASE_NUMBER': 'I-200-09001-123456',
            'CASE_STATUS': 'CERTIFIED',
            'EMPLOYER_NAME': 'ABC CORPORATION',
            'JOB_TITLE': 'SOFTWARE ENGINEER',
            'WAGE_RATE_OF_PAY': '85000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'H-1B_FY2009.xlsx', 
                            sample_row, ExpectedOutputType.WORKSITE_RECORD)  # I-200 = worksite

    def test_lca_fy2015_format(self):
        """Test old LCA format (FY2015)"""
        sample_row = {
            'CASE_NUMBER': 'I-200-15123-456789',
            'CASE_STATUS': 'CERTIFIED',
            'EMPLOYER_NAME': 'TEST COMPANY INC',
            'JOB_TITLE': 'BUSINESS ANALYST',
            'WAGE_RATE_OF_PAY_FROM': '75000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'H-1B_Disclosure_Data_FY15_Q4.xlsx',
                            sample_row, ExpectedOutputType.WORKSITE_RECORD)  # I-200 = worksite

    def test_lca_fy2020_format(self):
        """Test mid-era LCA format (FY2020)"""
        sample_row = {
            'CASE_NUMBER': 'I-203-20123-456789',
            'CASE_STATUS': 'CERTIFIED',
            'EMPLOYER_NAME': 'EXAMPLE LLC',
            'JOB_TITLE': 'DATA SCIENTIST',
            'WAGE_RATE_OF_PAY_FROM': '95000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'LCA_Disclosure_Data_FY2020.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)  # I-203 = regular LCA

    def test_lca_fy2024_q4_format(self):
        """Test recent LCA format (FY2024 Q4)"""
        sample_row = {
            'CASE_NUMBER': 'I-203-24456-789012',
            'CASE_STATUS': 'CERTIFIED',
            'EMPLOYER_NAME': 'MODERN TECH CORP',
            'JOB_TITLE': 'MACHINE LEARNING ENGINEER',
            'WAGE_RATE_OF_PAY_FROM': '125000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'LCA_Disclosure_Data_FY2024_Q4.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)

    # === PERM FORMATS ===
    
    def test_perm_fy2009_format(self):
        """Test old PERM format (FY2009)"""
        sample_row = {
            'CASE_NUMBER': 'A-12345-67890',
            'CASE_STATUS': 'Certified',
            'EMPLOYER_NAME': 'OLD COMPANY LLC',
            'JOB_TITLE': 'ACCOUNTANT',
            'BASIC_NUMBER_OF_WORKERS': '1',
            'WAGE_OFFER_FROM': '65000',
            'WAGE_OFFER_UNIT_OF_PAY': 'yr',
        }
        self._test_transform(DataDomain.DOL, SourceType.PERM, 'PERM_FY2009.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)

    def test_perm_fy2016_format(self):
        """Test mid-era PERM format (FY2016)"""
        sample_row = {
            'CASE_NUMBER': 'A-16789-01234',
            'CASE_STATUS': 'Certified',
            'EMPLOYER_NAME': 'MID ERA CONSULTING',
            'JOB_TITLE': 'PROJECT MANAGER',
            'BASIC_NUMBER_OF_WORKERS': '1',
            'WAGE_OFFER_FROM': '88000',
            'WAGE_OFFER_UNIT_OF_PAY': 'yr',
        }
        self._test_transform(DataDomain.DOL, SourceType.PERM, 'PERM_FY2016.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)

    def test_perm_fy2020_format(self):
        """Test recent PERM format (FY2020)"""
        sample_row = {
            'CASE_NUMBER': 'P-300-20123-456789',
            'CASE_STATUS': 'Certified',
            'EMPLOYER_NAME': 'MODERN ENTERPRISE INC',
            'JOB_TITLE': 'SENIOR SOFTWARE DEVELOPER',
            'BASIC_NUMBER_OF_WORKERS': '1',
            'WAGE_OFFER_FROM': '105000',
            'WAGE_OFFER_UNIT_OF_PAY': 'yr',
        }
        self._test_transform(DataDomain.DOL, SourceType.PERM, 'PERM_FY2020.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)

    def test_perm_fy2024_q4_format(self):
        """Test latest PERM format (FY2024 Q4)"""
        sample_row = {
            'CASE_NUMBER': 'P-300-24456-789012',
            'CASE_STATUS': 'Certified',
            'EMPLOYER_NAME': 'FUTURE TECH SOLUTIONS',
            'JOB_TITLE': 'CLOUD ARCHITECT',
            'BASIC_NUMBER_OF_WORKERS': '1',
            'WAGE_OFFER_FROM': '145000',
            'WAGE_OFFER_UNIT_OF_PAY': 'yr',
        }
        self._test_transform(DataDomain.DOL, SourceType.PERM, 'PERM_Disclosure_Data_FY2024_Q4.xlsx',
                            sample_row, ExpectedOutputType.SALARY_RECORD)

    # === WORKSITE FORMATS ===
    
    def test_worksite_fy2020_format(self):
        """Test worksite format (FY2020) - I-200 prefix
        
        Note: Worksite records still require job_title (inherited from LCA format)
        """
        sample_row = {
            'CASE_NUMBER': 'I-200-20123-456789',
            'CASE_STATUS': 'CERTIFIED',
            'JOB_TITLE': 'SOFTWARE ENGINEER',
            'WORKSITE_CITY': 'SAN FRANCISCO',
            'WORKSITE_STATE': 'CA',
            'WORKSITE_POSTAL_CODE': '94102',
            'WORKSITE_WORKERS': '5',
            'WAGE_RATE_OF_PAY_FROM': '95000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'LCA_Worksites_FY2020_Q4.xlsx',
                            sample_row, ExpectedOutputType.WORKSITE_RECORD)

    def test_worksite_fy2024_format(self):
        """Test worksite format (FY2024) - I-200 prefix
        
        Note: Worksite records still require job_title (inherited from LCA format)
        """
        sample_row = {
            'CASE_NUMBER': 'I-200-24456-789012',
            'CASE_STATUS': 'CERTIFIED',
            'JOB_TITLE': 'DATA ANALYST',
            'WORKSITE_CITY': 'NEW YORK',
            'WORKSITE_STATE': 'NY',
            'WORKSITE_POSTAL_CODE': '10001',
            'WORKSITE_WORKERS': '10',
            'WAGE_RATE_OF_PAY_FROM': '88000',
            'WAGE_UNIT_OF_PAY': 'Year',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'LCA_Worksites_FY2024_Q4.xlsx',
                            sample_row, ExpectedOutputType.WORKSITE_RECORD)

    # === APPENDIX A (Supplemental - expect None) ===
    
    def test_appendix_a_fy2024_format(self):
        """Test Appendix A format - supplemental data (expect None)"""
        sample_row = {
            'APPX_A_NAME_OF_INSTITUTION': 'UNIVERSITY OF EXAMPLE',
            'APPX_A_NO_OF_EXEMPT_WORKERS': '50',
        }
        self._test_transform(DataDomain.DOL, SourceType.LCA, 'LCA_Appendix_A_FY2024_Q4.xlsx',
                            sample_row, ExpectedOutputType.NONE)


if __name__ == '__main__':
    unittest.main()
