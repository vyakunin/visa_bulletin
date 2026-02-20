"""Tests for ingest versioning and rollback"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import pytest

from lib.ingest.versioning import activate_version, create_version, rollback_version
from models.enums.visa_program import VisaProgram
from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, IngestStatus, SourceType
from models.ingest.ingest_run import IngestRun
from models.salary import Employer, SalaryRecord

# Note: VisaCutoffDate import removed - not needed for these tests


@pytest.mark.django_db
class TestVersioning:
    """Tests for version creation and activation"""

    def test_create_version(self):
        """Test creating a new version"""
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version = create_version(run, "dol_lca_2024q4_v1")

        assert version.run == run
        assert version.version_tag == "dol_lca_2024q4_v1"
        assert version.is_active is False  # Starts inactive
        assert version.supersedes is None

    def test_create_version_with_supersedes(self):
        """Test creating version that supersedes another"""
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run1 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)
        run2 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version1 = create_version(run1, "v1")
        version2 = create_version(run2, "v2", supersedes=version1)

        assert version2.supersedes == version1
        assert version1.superseded_by.first() == version2

    def test_activate_version(self):
        """Test activating a version"""
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run1 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)
        run2 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version1 = create_version(run1, "v1")
        version2 = create_version(run2, "v2")

        # Activate first version
        activate_version(version1)
        version1.refresh_from_db()
        assert version1.is_active is True

        # Activate second version (should deactivate first)
        activate_version(version2)
        version1.refresh_from_db()
        version2.refresh_from_db()
        assert version1.is_active is False
        assert version2.is_active is True

    def test_rollback_version(self):
        """Test rolling back a version"""
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run1 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)
        run2 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version1 = create_version(run1, "v1")
        version2 = create_version(run2, "v2", supersedes=version1)

        # Create test employer and records
        employer = Employer.objects.create(
            name="Test Employer",
            name_normalized="TEST_EMPLOYER",
            city="Test City",
            state="CA",
        )

        record1 = SalaryRecord.objects.create(
            case_number="CASE1",
            visa_program=VisaProgram.H1B,
            employer=employer,
            employer_name="Test Employer",
            job_title="Engineer",
            wage_annual=100000,
            source_file="test.xlsx",
            ingest_version=version1,
        )

        record2 = SalaryRecord.objects.create(
            case_number="CASE2",
            visa_program=VisaProgram.H1B,
            employer=employer,
            employer_name="Test Employer",
            job_title="Manager",
            wage_annual=150000,
            source_file="test.xlsx",
            ingest_version=version2,
        )

        # Activate version2
        activate_version(version2)

        # Rollback version2
        result = rollback_version("v2")

        # Check results
        assert result["version_tag"] == "v2"
        assert result["salary_records_deleted"] == 1
        assert result["previous_version_activated"] == "v1"

        # Verify record2 deleted, record1 still exists
        assert SalaryRecord.objects.filter(case_number="CASE1").exists()
        assert not SalaryRecord.objects.filter(case_number="CASE2").exists()

        # Verify version1 reactivated
        version1.refresh_from_db()
        assert version1.is_active is True

        version2.refresh_from_db()
        assert version2.is_active is False

    def test_rollback_nonexistent_version(self):
        """Test rolling back non-existent version raises error"""
        with pytest.raises(ValueError, match="Version not found"):
            rollback_version("nonexistent")
