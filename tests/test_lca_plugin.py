"""Unit tests for combined LCA/Worksite ingest plugin"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from models.enums.visa_program import VisaProgram
from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, FormatVersion, IngestStatus, SourceType
from models.ingest.ingest_run import IngestRun
from models.salary import SalaryRecord, WorksiteRecord


class TestLCAPluginAttributes:
    """Tests for plugin attributes"""

    def test_plugin_attributes(self):
        """Test plugin has correct domain and source type"""
        plugin = H1BSalaryDataSourcePlugin()

        assert plugin.domain == DataDomain.DOL
        assert plugin.source_type == SourceType.LCA

    def test_get_format_version(self):
        """Test format version detection from filename"""
        plugin = H1BSalaryDataSourcePlugin()

        # Test with fiscal year (modern)
        filepath = Path("LCA_FY2024.xlsx")
        version = plugin.get_format_version(filepath)
        assert version == FormatVersion.MODERN

        # Test with legacy fiscal year
        filepath = Path("LCA_FY2010.xlsx")
        version = plugin.get_format_version(filepath)
        assert version == FormatVersion.LEGACY

        # Test with worksite filename
        filepath = Path("LCA_Worksites_FY2024.xlsx")
        version = plugin.get_format_version(filepath)
        assert version == FormatVersion.MODERN


class TestLCADiscovery:
    """Tests for source discovery"""

    @patch("lib.ingest.plugins.dol_lca.fetch_page")
    def test_discover_sources_finds_lca_files(self, mock_fetch):
        """Test source discovery finds LCA files"""
        plugin = H1BSalaryDataSourcePlugin()

        # Mock HTML response with LCA links
        mock_fetch.return_value = """
        <html>
        <a href="LCA_Disclosure_Data_FY2024.xlsx">Download</a>
        <a href="LCA_FY2013.xlsx">Download</a>
        <a href="PERM_Disclosure_Data_FY2024.xlsx">Download</a>
        </html>
        """

        sources = plugin.discover_sources()

        # Should find LCA files (not PERM files)
        lca_sources = [
            s for s in sources if "LCA" in s.url and "worksite" not in s.url.lower()
        ]
        assert len(lca_sources) == 2
        assert all(s.domain == DataDomain.DOL.value for s in lca_sources)
        assert all(s.source_type == SourceType.LCA.value for s in lca_sources)

    @patch("lib.ingest.plugins.dol_lca.fetch_page")
    def test_discover_sources_finds_worksite_files(self, mock_fetch):
        """Test source discovery finds worksite files"""
        plugin = H1BSalaryDataSourcePlugin()

        # Mock HTML response with worksite links
        mock_fetch.return_value = """
        <html>
        <a href="LCA_Worksites_FY2024.xlsx">Download</a>
        <a href="LCA_Worksites_FY2023_Q4.xlsx">Download</a>
        <a href="LCA_Disclosure_Data_FY2024.xlsx">Download</a>
        </html>
        """

        sources = plugin.discover_sources()

        # Should find both LCA and worksite files
        worksite_sources = [s for s in sources if "worksite" in s.url.lower()]
        assert len(worksite_sources) == 2
        assert all(s.domain == DataDomain.DOL.value for s in worksite_sources)
        assert all(
            s.source_type == SourceType.LCA.value for s in worksite_sources
        )  # Combined plugin uses LCA source_type


@pytest.mark.django_db
class TestLCATransformRouting:
    """Tests for transform method routing (SalaryRecord vs WorksiteRecord)"""

    def test_transform_routes_i200_to_worksite_record(self):
        """Test transform routes I-200 case numbers to WorksiteRecord"""
        plugin = H1BSalaryDataSourcePlugin()
        plugin._current_run = Mock()

        # Mock record with I-200 case number
        record = {
            "LCA_CASE_NUMBER": "I-200-11111-1111",
            "WORKSITE_CITY": "Austin",
            "WORKSITE_STATE": "TX",
            "JOB_TITLE": "Data Scientist",
            "SOC_CODE": "15-2051",
            "WAGE_RATE_OF_PAY_FROM": "120000",
            "WAGE_UNIT_OF_PAY": "Year",
            "_fiscal_year": 2024,
            "_source_file": "LCA_FY2024.xlsx",
        }

        result = plugin.transform(record)

        # Should create WorksiteRecord, not SalaryRecord
        assert result is not None
        assert isinstance(result, WorksiteRecord)
        assert result.case_number == "I-200-11111-1111"
        assert result.worksite_city == "Austin"
        assert result.worksite_state == "TX"
        assert result.job_title == "Data Scientist"
        assert result.wage_annual == 120000.0

    def test_transform_routes_non_i200_to_salary_record(self):
        """Test transform routes non-I-200 case numbers to SalaryRecord"""
        plugin = H1BSalaryDataSourcePlugin()
        plugin._current_run = Mock()

        # Mock record with G-200 case number (regular LCA)
        record = {
            "LCA_CASE_NUMBER": "G-200-22222-2222",
            "LCA_CASE_EMPLOYER_NAME": "Tech Corp",
            "EMPLOYER_CITY": "Seattle",
            "EMPLOYER_STATE": "WA",
            "JOB_TITLE": "Software Engineer",
            "SOC_CODE": "15-1132",
            "WAGE_RATE_OF_PAY_FROM": "150000",
            "WAGE_UNIT_OF_PAY": "Year",
            "_fiscal_year": 2024,
            "_source_file": "LCA_FY2024.xlsx",
        }

        result = plugin.transform(record)

        # Should create SalaryRecord, not WorksiteRecord
        assert result is not None
        assert isinstance(result, SalaryRecord)
        assert result.case_number == "G-200-22222-2222"
        assert result.employer_name == "Tech Corp"
        assert result.job_title == "Software Engineer"
        assert result.wage_annual == 150000.0

    def test_transform_filters_missing_case_number(self):
        """Test transform returns None for records without case_number"""
        plugin = H1BSalaryDataSourcePlugin()

        record = {
            "WORKSITE_CITY": "Seattle",
            "WORKSITE_STATE": "WA",
            # Missing CASE_NUMBER
        }

        result = plugin.transform(record)
        assert result is None

    def test_transform_skips_salary_record_without_employer_name(self):
        """Test transform skips salary records without employer_name"""
        plugin = H1BSalaryDataSourcePlugin()
        plugin._current_run = Mock()

        # Record with case number but no employer name
        record = {
            "LCA_CASE_NUMBER": "G-200-11111-1111",
            "JOB_TITLE": "Engineer",
            "WAGE_RATE_OF_PAY_FROM": "120000",
            "WAGE_UNIT_OF_PAY": "Year",
            "_fiscal_year": 2024,
            "_source_file": "LCA_FY2024.xlsx",
            # Missing EMPLOYER_NAME
        }

        result = plugin.transform(record)
        assert result is None

    def test_transform_skips_salary_record_without_salary_data(self):
        """Test transform skips salary records without salary data"""
        plugin = H1BSalaryDataSourcePlugin()
        plugin._current_run = Mock()

        # Record with employer but no salary data
        record = {
            "LCA_CASE_NUMBER": "G-200-11111-1111",
            "LCA_CASE_EMPLOYER_NAME": "Tech Corp",
            "EMPLOYER_CITY": "Seattle",
            "EMPLOYER_STATE": "WA",
            "JOB_TITLE": "Engineer",
            "_fiscal_year": 2024,
            "_source_file": "LCA_FY2024.xlsx",
            # Missing WAGE_RATE_OF_PAY_FROM and WAGE_UNIT_OF_PAY
        }

        result = plugin.transform(record)
        assert result is None

    def test_transform_creates_salary_record_with_all_required_fields(self):
        """Test transform creates salary record when all required fields are present"""
        plugin = H1BSalaryDataSourcePlugin()
        plugin._current_run = Mock()

        # Record with all required fields
        record = {
            "LCA_CASE_NUMBER": "G-200-11111-1111",
            "LCA_CASE_EMPLOYER_NAME": "Tech Corp",
            "EMPLOYER_CITY": "Seattle",
            "EMPLOYER_STATE": "WA",
            "JOB_TITLE": "Engineer",
            "WAGE_RATE_OF_PAY_FROM": "120000",
            "WAGE_UNIT_OF_PAY": "Year",
            "_fiscal_year": 2024,
            "_source_file": "LCA_FY2024.xlsx",
        }

        result = plugin.transform(record)
        assert result is not None
        assert isinstance(result, SalaryRecord)
        assert result.case_number == "G-200-11111-1111"
        assert result.employer_name == "Tech Corp"
        assert result.wage_annual == 120000.0


@pytest.mark.django_db
class TestLCAParse:
    """Tests for parse method"""

    def test_parse_excel_streaming(self, tmp_path):
        """Test Excel parsing with openpyxl streaming"""
        plugin = H1BSalaryDataSourcePlugin()

        # Create a simple Excel file
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.append(
            [
                "LCA_CASE_NUMBER",
                "LCA_CASE_EMPLOYER_NAME",
                "WORKSITE_CITY",
                "WORKSITE_STATE",
                "JOB_TITLE",
                "WAGE_RATE_OF_PAY_FROM",
                "WAGE_UNIT_OF_PAY",
            ]
        )
        ws.append(
            [
                "I-200-12345-6789",
                "Company A",
                "San Francisco",
                "CA",
                "Engineer",
                "150000",
                "Year",
            ]
        )
        ws.append(
            [
                "G-200-98765-4321",
                "Company B",
                "Seattle",
                "WA",
                "Developer",
                "100",
                "Hour",
            ]
        )

        # Filename carries the fiscal year (FY2024) so the plugin can extract it;
        # a year-less name like "test_lca.xlsx" yields _fiscal_year=None.
        test_file = tmp_path / "LCA_FY2024.xlsx"
        wb.save(test_file)

        source = DataSource.objects.create(
            url="https://example.com/LCA_FY2024.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source, status=IngestStatus.PENDING, checkpoint={}
        )

        records = list(plugin.parse(test_file, run))

        assert len(records) == 2
        assert records[0]["LCA_CASE_NUMBER"] == "I-200-12345-6789"
        assert records[0]["WORKSITE_CITY"] == "San Francisco"
        assert records[1]["LCA_CASE_NUMBER"] == "G-200-98765-4321"
        assert records[1]["WORKSITE_STATE"] == "WA"
        # Should have fiscal year (extracted from the FY2024 filename) and source file
        assert records[0].get("_fiscal_year") == 2024
        assert records[0].get("_source_file") == "LCA_FY2024.xlsx"


@pytest.mark.django_db
class TestLCAValidation:
    """Tests for post-ingest validation"""

    def test_validate_post_ingest_with_both_record_types(self):
        """Test validation handles both SalaryRecord and WorksiteRecord"""
        from models.ingest.enums import IngestStatus

        plugin = H1BSalaryDataSourcePlugin()

        source = DataSource.objects.create(
            url="https://example.com/test_mixed.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        # Create a run with checkpoint
        run = IngestRun.objects.create(
            source=source,
            status=IngestStatus.COMPLETED,
            records_created=2,
            checkpoint={"filepath": "/tmp/test_mixed.xlsx"},
        )

        # Create test records (both types)
        SalaryRecord.objects.create(
            case_number="G-200-11111-1111",
            visa_program=VisaProgram.H1B,
            employer_name="Company A",
            worksite_city="Austin",
            worksite_state="TX",
            job_title="Engineer",
            wage_annual=120000,
            fiscal_year=2024,
            source_file="test_mixed.xlsx",
        )

        WorksiteRecord.objects.create(
            case_number="I-200-22222-2222",
            visa_program=VisaProgram.H1B,
            worksite_city="Seattle",
            worksite_state="WA",
            job_title="Developer",
            wage_annual=100000,
            fiscal_year=2024,
            source_file="test_mixed.xlsx",
        )

        # Run validation
        result = plugin.validate_post_ingest(run)

        assert result.passed is True
        assert len(result.errors) == 0
        # Should have details for both record types
        assert "salary_records" in result.details
        assert "worksite_records" in result.details

    def test_validate_post_ingest_no_records(self):
        """Test validation when no records were created"""
        from models.ingest.enums import IngestStatus

        plugin = H1BSalaryDataSourcePlugin()

        source = DataSource.objects.create(
            url="https://example.com/empty.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source,
            status=IngestStatus.COMPLETED,
            records_created=0,
            checkpoint={"filepath": "/tmp/empty.xlsx"},
        )

        result = plugin.validate_post_ingest(run)

        assert result.passed is False
        assert len(result.errors) > 0
