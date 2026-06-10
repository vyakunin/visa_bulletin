"""Unit tests for ingest models"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()


import pytest

from models.ingest.data_source import DataSource
from models.ingest.enums import DataDomain, IngestStage, IngestStatus, SourceType
from models.ingest.ingest_run import IngestRun
from models.ingest.ingest_version import IngestVersion


@pytest.mark.django_db
class TestDataSource:
    """Tests for DataSource model"""

    def test_create_data_source(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
            format_version="2024q4",
        )

        assert source.url == "https://example.com/data.xlsx"
        assert source.domain == DataDomain.DOL
        assert source.source_type == SourceType.LCA
        assert source.format_version == "2024q4"
        assert source.discovered_at is not None

    def test_data_source_str(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        # __str__ spells out the agency (DataDomain.DOL → "Department of Labor")
        # per the project's spell-out-abbreviations convention.
        assert "Department of Labor" in str(source)
        assert "LCA" in str(source)
        assert "example.com" in str(source)


@pytest.mark.django_db
class TestIngestRun:
    """Tests for IngestRun model"""

    def test_create_ingest_run(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source, status=IngestStatus.PENDING, stage=IngestStage.PENDING
        )

        assert run.source == source
        assert run.status == IngestStatus.PENDING
        assert run.stage == IngestStage.PENDING
        assert run.records_processed == 0
        assert run.started_at is not None

    def test_mark_completed(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source, status=IngestStatus.RUNNING, stage=IngestStage.LOADING
        )

        run.mark_completed()

        assert run.status == IngestStatus.COMPLETED
        assert run.stage == IngestStage.COMPLETED
        assert run.completed_at is not None

    def test_mark_failed(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source, status=IngestStatus.RUNNING, stage=IngestStage.PARSING
        )

        error = ValueError("Test error")
        run.mark_failed(error)

        assert run.status == IngestStatus.FAILED
        assert "Test error" in run.error_message
        assert run.error_traceback
        assert run.completed_at is not None

    def test_checkpoint_storage(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(
            source=source,
            checkpoint={
                "last_row": 50000,
                "batch": 50,
                "filepath": "/path/to/file.xlsx",
            },
        )

        assert run.checkpoint["last_row"] == 50000
        assert run.checkpoint["batch"] == 50
        assert run.checkpoint["filepath"] == "/path/to/file.xlsx"


@pytest.mark.django_db
class TestIngestVersion:
    """Tests for IngestVersion model"""

    def test_create_version(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version = IngestVersion.objects.create(
            run=run, version_tag="dol_lca_2024q4_v1", is_active=True
        )

        assert version.run == run
        assert version.version_tag == "dol_lca_2024q4_v1"
        assert version.is_active is True
        assert version.created_at is not None

    def test_version_supersedes(self):
        source = DataSource.objects.create(
            url="https://example.com/data.xlsx",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
        )

        run1 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)
        run2 = IngestRun.objects.create(source=source, status=IngestStatus.COMPLETED)

        version1 = IngestVersion.objects.create(
            run=run1, version_tag="v1", is_active=False
        )

        version2 = IngestVersion.objects.create(
            run=run2, version_tag="v2", is_active=True, supersedes=version1
        )

        assert version2.supersedes == version1
        assert version1.superseded_by.first() == version2
