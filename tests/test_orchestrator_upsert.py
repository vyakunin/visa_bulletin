"""
Unit tests for orchestrator upsert logic.

Tests that verify:
1. _is_newer_than_existing() date comparison logic
2. _identify_new_and_existing() correctly identifies new and existing records
3. _upsert_batch_to_db() creates new records and updates existing ones correctly
"""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
import django

django.setup()

from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from lib.ingest.orchestrator import PipelineOrchestrator, _identify_new_and_existing
from models.ingest.data_source import DataSource
from models.ingest.enums import (
    DataDomain,
    FormatVersion,
    IngestStage,
    IngestStatus,
    SourceType,
)
from models.ingest.ingest_run import IngestRun
from models.salary import Employer, SalaryRecord


class TestOrchestratorUpsert(TestCase):
    """Test orchestrator upsert functionality"""

    def setUp(self):
        """Set up test fixtures"""
        # Create test employer
        self.employer = Employer.objects.create(
            name="Test Employer",
            name_normalized="test employer",
            city="Test City",
            state="CA",
        )

        # Create test data source
        self.data_source = DataSource.objects.create(
            url="file://test.xlsx",
            domain=DataDomain.DOL.value,
            source_type=SourceType.LCA.value,
            format_version=FormatVersion.MODERN.value,
        )

        # Create test ingest run
        self.ingest_run = IngestRun.objects.create(
            source=self.data_source,
            status=IngestStatus.PENDING,
            stage=IngestStage.PENDING,
        )

    def test_is_newer_than_existing_incoming_newer(self):
        """Test _is_newer_than_existing when incoming date is newer"""
        orchestrator = PipelineOrchestrator()

        incoming = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(incoming):
            incoming = timezone.make_aware(incoming)

        existing = datetime(2024, 5, 1, 12, 0, 0)
        if timezone.is_naive(existing):
            existing = timezone.make_aware(existing)

        result = orchestrator._is_newer_than_existing(incoming, existing)
        self.assertTrue(result)

    def test_is_newer_than_existing_existing_newer(self):
        """Test _is_newer_than_existing when existing date is newer"""
        orchestrator = PipelineOrchestrator()

        incoming = datetime(2024, 5, 1, 12, 0, 0)
        if timezone.is_naive(incoming):
            incoming = timezone.make_aware(incoming)

        existing = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(existing):
            existing = timezone.make_aware(existing)

        result = orchestrator._is_newer_than_existing(incoming, existing)
        self.assertFalse(result)

    def test_is_newer_than_existing_existing_none(self):
        """Test _is_newer_than_existing when existing date is None"""
        orchestrator = PipelineOrchestrator()

        incoming = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(incoming):
            incoming = timezone.make_aware(incoming)

        result = orchestrator._is_newer_than_existing(incoming, None)
        self.assertTrue(result)  # Should treat as newer when existing is None

    def test_is_newer_than_existing_incoming_none(self):
        """Test _is_newer_than_existing when incoming date is None"""
        orchestrator = PipelineOrchestrator()

        existing = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(existing):
            existing = timezone.make_aware(existing)

        result = orchestrator._is_newer_than_existing(None, existing)
        self.assertFalse(result)  # Should keep existing when incoming is None

    def test_identify_new_and_existing(self):
        """Test _identify_new_and_existing correctly separates new and existing records"""
        # Create existing record
        existing_record = SalaryRecord.objects.create(
            case_number="CASE-001",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Software Engineer",
            fiscal_year=2024,
            source_file="test.xlsx",
            source_file_date=datetime(2024, 1, 1, 12, 0, 0),
        )
        if timezone.is_naive(existing_record.source_file_date):
            existing_record.source_file_date = timezone.make_aware(
                existing_record.source_file_date
            )
        existing_record.save()

        # Create new record (not in DB)
        new_record = SalaryRecord(
            case_number="CASE-002",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Data Scientist",
            fiscal_year=2024,
            source_file="test.xlsx",
        )

        # Create incoming record with same case_number as existing
        incoming_existing = SalaryRecord(
            case_number="CASE-001",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Test Employer Updated",
            job_title="Senior Software Engineer",
            fiscal_year=2024,
            source_file="test.xlsx",
        )

        records = [new_record, incoming_existing]
        new_records, existing_dict = _identify_new_and_existing(records)

        # Should identify new record
        self.assertEqual(len(new_records), 1)
        self.assertEqual(new_records[0].case_number, "CASE-002")

        # Should identify existing record
        self.assertEqual(len(existing_dict), 1)
        self.assertIn("CASE-001", existing_dict)
        self.assertEqual(existing_dict["CASE-001"].case_number, "CASE-001")

    def test_upsert_creates_new_records(self):
        """Test _upsert_batch_to_db creates new records that don't exist"""
        orchestrator = PipelineOrchestrator()

        # Set source_file_date in checkpoint
        source_file_date = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(source_file_date):
            source_file_date = timezone.make_aware(source_file_date)
        self.ingest_run.checkpoint["source_file_date"] = source_file_date.isoformat()
        self.ingest_run.save()

        # Create new record
        new_record = SalaryRecord(
            case_number="CASE-NEW",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Test Employer",
            job_title="Software Engineer",
            fiscal_year=2024,
            source_file="test.xlsx",
        )

        batch = [new_record]
        orchestrator._upsert_batch_to_db(batch, self.ingest_run)

        # Should create the record
        self.assertEqual(self.ingest_run.records_created, 1)
        self.assertEqual(self.ingest_run.records_updated, 0)
        self.assertEqual(self.ingest_run.records_skipped, 0)

        # Verify record was created in DB
        created = SalaryRecord.objects.get(case_number="CASE-NEW")
        self.assertIsNotNone(created)
        self.assertEqual(created.source_file_date, source_file_date)

    def test_upsert_updates_existing_when_incoming_newer(self):
        """Test _upsert_batch_to_db updates existing record when incoming is newer"""
        orchestrator = PipelineOrchestrator()

        # Create existing record with older date
        existing_date = datetime(2024, 5, 1, 12, 0, 0)
        if timezone.is_naive(existing_date):
            existing_date = timezone.make_aware(existing_date)

        existing_record = SalaryRecord.objects.create(
            case_number="CASE-EXISTING",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Old Employer Name",
            job_title="Old Job Title",
            fiscal_year=2024,
            source_file="old.xlsx",
            source_file_date=existing_date,
        )

        # Set source_file_date in checkpoint (newer than existing)
        incoming_date = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(incoming_date):
            incoming_date = timezone.make_aware(incoming_date)
        self.ingest_run.checkpoint["source_file_date"] = incoming_date.isoformat()
        self.ingest_run.save()

        # Create incoming record with newer data
        incoming_record = SalaryRecord(
            case_number="CASE-EXISTING",
            visa_program="H1B",
            employer=self.employer,
            employer_name="New Employer Name",
            job_title="New Job Title",
            fiscal_year=2024,
            source_file="new.xlsx",
        )

        batch = [incoming_record]
        orchestrator._upsert_batch_to_db(batch, self.ingest_run)

        # Should update the record
        self.assertEqual(self.ingest_run.records_created, 0)
        self.assertEqual(self.ingest_run.records_updated, 1)
        self.assertEqual(self.ingest_run.records_skipped, 0)

        # Verify record was updated
        existing_record.refresh_from_db()
        self.assertEqual(existing_record.employer_name, "New Employer Name")
        self.assertEqual(existing_record.job_title, "New Job Title")
        self.assertEqual(existing_record.source_file_date, incoming_date)

    def test_upsert_skips_when_existing_newer(self):
        """Test _upsert_batch_to_db skips update when existing is newer"""
        orchestrator = PipelineOrchestrator()

        # Create existing record with newer date
        existing_date = datetime(2024, 6, 1, 12, 0, 0)
        if timezone.is_naive(existing_date):
            existing_date = timezone.make_aware(existing_date)

        existing_record = SalaryRecord.objects.create(
            case_number="CASE-EXISTING",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Current Employer Name",
            job_title="Current Job Title",
            fiscal_year=2024,
            source_file="current.xlsx",
            source_file_date=existing_date,
        )

        # Set source_file_date in checkpoint (older than existing)
        incoming_date = datetime(2024, 5, 1, 12, 0, 0)
        if timezone.is_naive(incoming_date):
            incoming_date = timezone.make_aware(incoming_date)
        self.ingest_run.checkpoint["source_file_date"] = incoming_date.isoformat()
        self.ingest_run.save()

        # Create incoming record with older data
        incoming_record = SalaryRecord(
            case_number="CASE-EXISTING",
            visa_program="H1B",
            employer=self.employer,
            employer_name="Old Employer Name",
            job_title="Old Job Title",
            fiscal_year=2024,
            source_file="old.xlsx",
        )

        batch = [incoming_record]
        orchestrator._upsert_batch_to_db(batch, self.ingest_run)

        # Should skip the update
        self.assertEqual(self.ingest_run.records_created, 0)
        self.assertEqual(self.ingest_run.records_updated, 0)
        self.assertEqual(self.ingest_run.records_skipped, 1)

        # Verify record was NOT updated
        existing_record.refresh_from_db()
        self.assertEqual(existing_record.employer_name, "Current Employer Name")
        self.assertEqual(existing_record.job_title, "Current Job Title")
        self.assertEqual(existing_record.source_file_date, existing_date)
