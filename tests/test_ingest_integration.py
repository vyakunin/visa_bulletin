"""Integration tests for ingest pipeline"""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from unittest.mock import MagicMock, Mock, patch

import pytest
from django.db import connection
from openpyxl import Workbook

from lib.ingest.base import ValidationResult
from lib.ingest.orchestrator import PipelineOrchestrator
from lib.ingest.plugins.dol_lca import H1BSalaryDataSourcePlugin
from lib.ingest.plugins.dol_perm import PERMSalaryDataSourcePlugin
from lib.ingest.plugins.visa_bulletin import VisaBulletinPlugin
from lib.ingest.registry import PluginRegistry
from models.bulletin import Bulletin
from models.ingest.data_source import DataSource
from models.ingest.enums import (
    DataDomain,
    FormatVersion,
    IngestStage,
    IngestStatus,
    SourceType,
)
from models.salary import SalaryRecord
from models.visa_cutoff_date import VisaCutoffDate


@pytest.mark.django_db
class TestIngestPipelineIntegration:
    """Integration tests for full pipeline"""

    def test_pipeline_handles_missing_record_estimate(self, tmp_path):
        """Pipeline should not crash if row count cannot be estimated."""
        source = DataSource.objects.create(
            url="file://missing.html",
            domain=DataDomain.VISA_BULLETIN,
            source_type=SourceType.BULLETIN,
            format_version=FormatVersion.MODERN,
        )

        plugin = MagicMock()
        plugin.set_rejection_tracker = Mock()

        orchestrator = PipelineOrchestrator()
        orchestrator.update_mode = True  # Skip versioning logic for unit-style test

        dummy_file = tmp_path / "dummy.html"
        dummy_file.write_text("test")

        with patch("lib.ingest.orchestrator.PluginRegistry.get_plugin", return_value=plugin), \
             patch("lib.ingest.orchestrator.get_data_source_filepath", return_value=None), \
             patch("lib.ingest.orchestrator.RejectionTracker") as rejection_tracker, \
             patch.object(orchestrator, "_download_stage", return_value=dummy_file), \
             patch.object(orchestrator, "_parse_stage", return_value=[]), \
             patch.object(orchestrator, "_transform_stage", return_value=[]), \
             patch.object(orchestrator, "_load_to_db_stage", return_value=None), \
             patch.object(orchestrator, "_validate_post_ingest", return_value=ValidationResult(passed=True)):
            rejection_tracker.return_value.save_to_db = Mock()
            run = orchestrator.run(source, resume=False)

        assert run.status == IngestStatus.COMPLETED

    def test_full_pipeline_with_excel(self, tmp_path):
        """Test full pipeline: discover -> download -> parse -> transform -> load"""
        # Register plugins
        PluginRegistry.register(H1BSalaryDataSourcePlugin())
        PluginRegistry.register(PERMSalaryDataSourcePlugin())
        PluginRegistry.register(VisaBulletinPlugin())

        # Create test Excel file
        wb = Workbook()
        ws = wb.active
        ws.append(['CASE_NUMBER', 'EMPLOYER_NAME', 'JOB_TITLE', 'WAGE_RATE_OF_PAY_FROM', 'WAGE_UNIT_OF_PAY'])
        ws.append(['CASE001', 'Test Company', 'Software Engineer', '150000', 'Year'])
        ws.append(['CASE002', 'Test Company', 'Data Scientist', '140000', 'Year'])

        test_file = tmp_path / "test_lca.xlsx"
        wb.save(test_file)

        # Create data source
        source = DataSource.objects.create(
            url=f"file://{test_file}",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA,
            format_version=FormatVersion.MODERN
        )

        # Mock download to return test file
        plugin = PluginRegistry.get_plugin(DataDomain.DOL, SourceType.LCA)
        original_download = plugin.download

        def mock_download(s, r):
            return test_file

        plugin.download = mock_download

        # Run pipeline
        orchestrator = PipelineOrchestrator(
            batch_size=10,
            adaptive_batch=False,
            prefilter_existing=False
        )

        run = orchestrator.run(source, resume=False)

        # Verify run completed
        assert run.status == IngestStatus.COMPLETED
        assert run.stage == IngestStage.COMPLETED
        assert run.records_created == 2

        # Verify records in database
        records = SalaryRecord.objects.filter(source_file=test_file.name)
        assert records.count() == 2

        # Verify data
        record1 = records.get(case_number='CASE001')
        assert record1.employer_name == 'Test Company'
        assert record1.job_title == 'Software Engineer'
        assert float(record1.wage_annual) == 150000.0

        # Restore original method
        plugin.download = original_download

    def test_resume_from_checkpoint(self, tmp_path):
        """Test resuming pipeline from checkpoint"""
        # Register plugins
        PluginRegistry.register(H1BSalaryDataSourcePlugin())
        PluginRegistry.register(PERMSalaryDataSourcePlugin())
        PluginRegistry.register(VisaBulletinPlugin())

        # Create test Excel file with many rows
        wb = Workbook()
        ws = wb.active
        ws.append(['CASE_NUMBER', 'EMPLOYER_NAME', 'JOB_TITLE', 'WAGE_RATE_OF_PAY_FROM', 'WAGE_UNIT_OF_PAY'])
        for i in range(50):
            ws.append([f'CASE{i:03d}', 'Test Company', 'Engineer', '100000', 'Year'])

        test_file = tmp_path / "test_lca_large.xlsx"
        wb.save(test_file)

        source = DataSource.objects.create(
            url=f"file://{test_file}",
            domain=DataDomain.DOL,
            source_type=SourceType.LCA
        )

        plugin = PluginRegistry.get_plugin(DataDomain.DOL, SourceType.LCA)
        original_download = plugin.download

        def mock_download(s, r):
            return test_file

        plugin.download = mock_download

        orchestrator = PipelineOrchestrator(batch_size=10, adaptive_batch=False)

        # Start pipeline
        run = orchestrator.run(source, resume=False)

        # Simulate interruption at row 25
        run.checkpoint = {'last_row': 25, 'filepath': str(test_file)}
        run.stage = IngestStage.PARSING
        run.status = IngestStatus.RUNNING
        run.save()

        # Resume pipeline
        run_resumed = orchestrator.run(source, resume=True)

        # Should complete all records
        assert run_resumed.status == IngestStatus.COMPLETED
        assert run_resumed.records_created == 50

        plugin.download = original_download

    def test_plugin_registration(self):
        """Test that plugins are registered correctly"""
        PluginRegistry.clear()
        # Register plugins
        PluginRegistry.register(H1BSalaryDataSourcePlugin())
        PluginRegistry.register(PERMSalaryDataSourcePlugin())
        PluginRegistry.register(VisaBulletinPlugin())

        # Check DOL LCA plugin
        lca_plugin = PluginRegistry.get_plugin(DataDomain.DOL, SourceType.LCA)
        assert lca_plugin is not None
        assert lca_plugin.domain == DataDomain.DOL
        assert lca_plugin.source_type == SourceType.LCA

        # Check DOL PERM plugin
        perm_plugin = PluginRegistry.get_plugin(DataDomain.DOL, SourceType.PERM)
        assert perm_plugin is not None

        # Check list
        plugins = PluginRegistry.list_plugins()
        assert len(plugins) >= 2

    def test_db_error_retry(self, tmp_path):
        """
        Test that records failing to save due to database errors are saved on rerun.
        
        This test simulates the scenario where:
        1. Pipeline runs but table doesn't exist (database error)
        2. Run is marked as FAILED with records_failed > 0
        3. Table is created (fixing the issue)
        4. Pipeline is rerun
        5. Records are successfully saved on rerun
        """
        # Register plugins
        PluginRegistry.register(H1BSalaryDataSourcePlugin())
        PluginRegistry.register(PERMSalaryDataSourcePlugin())
        PluginRegistry.register(VisaBulletinPlugin())

        # Create test visa bulletin HTML file
        test_html = """
        <html>
        <body>
        <h1>Visa Bulletin for January 2025</h1>
        <table>
        <tr><th>Family-Sponsored</th><th>All Chargeability Areas Except Those Listed</th></tr>
        <tr><td>F1</td><td>01JAN20</td></tr>
        <tr><td>F2A</td><td>C</td></tr>
        <tr><td>F2B</td><td>15MAR15</td></tr>
        </table>
        </body>
        </html>
        """

        test_file = tmp_path / "visa-bulletin-for-january-2025.html"
        test_file.write_text(test_html)

        # Create data source
        source = DataSource.objects.create(
            url=f"file://{test_file}",
            domain=DataDomain.VISA_BULLETIN,
            source_type=SourceType.BULLETIN,
            format_version=FormatVersion.MODERN
        )

        # Mock download to return test file
        plugin = PluginRegistry.get_plugin(DataDomain.VISA_BULLETIN, SourceType.BULLETIN)
        original_download = plugin.download

        def mock_download(s, r):
            return test_file

        plugin.download = mock_download

        # Temporarily rename bulletin table to simulate missing table error
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bulletin'"
            )
            table_exists = cursor.fetchone()
            if table_exists:
                cursor.execute("ALTER TABLE bulletin RENAME TO bulletin_backup")

        orchestrator = PipelineOrchestrator(
            batch_size=10,
            adaptive_batch=False,
            prefilter_existing=False
        )

        # First run - should fail with database error
        try:
            run = orchestrator.run(source, resume=False)
            # Should not reach here, but if it does, verify it failed
            assert run.status == IngestStatus.FAILED, "Expected run to fail with missing table"
        except Exception as e:
            # Expected - database error (SQLite: "no such table"; PostgreSQL: "does not exist" / "relation")
            err = str(e).lower()
            assert (
                "no such table" in err
                or "does not exist" in err
                or "relation" in err
                or "bulletin" in err
            ), f"Expected DB error, got: {e}"
            # Get the run that was created
            run = source.runs.order_by('-started_at').first()
            assert run is not None
            assert run.status == IngestStatus.FAILED
            assert run.records_failed > 0, "Should have records_failed > 0 when save fails"

        # Verify no records were saved
        assert Bulletin.objects.count() == 0, "No bulletins should be saved on failed run"
        assert VisaCutoffDate.objects.count() == 0, "No cutoff dates should be saved on failed run"

        # Restore table (fix the database issue)
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT 1 FROM information_schema.tables WHERE table_schema = 'public' AND table_name = 'bulletin_backup'"
            )
            if cursor.fetchone():
                cursor.execute("ALTER TABLE bulletin_backup RENAME TO bulletin")

        # Rerun pipeline - should succeed now
        run_retry = orchestrator.run(source, resume=True)

        # Verify run completed successfully
        assert run_retry.status == IngestStatus.COMPLETED, f"Run should complete on retry, got status: {run_retry.status}"
        assert run_retry.stage == IngestStage.COMPLETED
        assert run_retry.records_created > 0, "Should have created records on successful retry"
        assert run_retry.records_failed == 0, "Should have no failed records on successful retry"

        # Verify records were actually saved to database
        assert Bulletin.objects.count() > 0, "Bulletins should be saved on retry"
        assert VisaCutoffDate.objects.count() > 0, "Cutoff dates should be saved on retry"

        # Verify data integrity
        bulletin = Bulletin.objects.first()
        assert bulletin is not None
        cutoff_dates = VisaCutoffDate.objects.filter(bulletin=bulletin)
        assert cutoff_dates.count() > 0, "Should have cutoff dates linked to bulletin"

        # Restore original method
        plugin.download = original_download










