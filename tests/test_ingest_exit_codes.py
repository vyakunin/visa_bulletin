"""Guards that a FAILED ingest source can never report success via the exit code.

Both ingest entry points loop over sources and deliberately stay resilient — one bad
source must not abort the batch. That resilience is correct, and it is exactly what made
the failure invisible: the loop finishes, the function returns, the process exits 0.

Live on 2026-07-16: a driver looping over 39 sources read those exit codes and reported
"39/39 ok" while source 195 (october-2015) had FAILED and persisted ZERO rows. Nothing in
the pipeline said otherwise — it was caught only by an independent end-state row-count
query. An exit code that cannot distinguish 39/39 from 38/39 is not a usable gate, and a
driver has nothing else to read.

Two distinct entry points, two distinct bugs, both pinned here:

  * scripts/ingest/run_pipeline.py — swallowed the per-source exception and exited 0.
    It also logged "Pipeline completed: Run N" off a returned run WITHOUT checking the
    run's status, so a non-COMPLETED run was reported as a success.
  * scripts/cron/refresh_bulletin.py — the LIVE hourly path (via the minipc bridge).
    It exited 1 only when ZERO sources ingested, so 1-of-3 succeeding looked identical to
    3-of-3. The bridge alerts off this exit code, so the two failures would never surface.

What these CANNOT verify (only a live run can): that the bridge actually turns a non-zero
exit into an alert. That seam is pinned by tests/test_bulletin_sync_alerting.py.
"""

import sys

import pytest

import scripts.cron.refresh_bulletin as rb
import scripts.ingest.run_pipeline as rp
from models.ingest.data_source import DataSource
from models.ingest.enums import (
    DataDomain,
    FormatVersion,
    IngestStage,
    IngestStatus,
    SourceType,
)
from models.ingest.ingest_run import IngestRun


def _make_source(url: str = "file://exit-code-guard.html") -> DataSource:
    return DataSource.objects.create(
        url=url,
        domain=DataDomain.VISA_BULLETIN,
        source_type=SourceType.BULLETIN,
        format_version=FormatVersion.MODERN,
    )


@pytest.mark.django_db
class TestRunPipelineResult:
    """run_pipeline must REPORT per-source outcomes, not just finish."""

    def test_raising_source_is_recorded_as_failed(self, monkeypatch):
        source = _make_source()

        def _boom(self, source, **kwargs):
            raise RuntimeError("parser blew up")

        monkeypatch.setattr(rp.PipelineOrchestrator, "run", _boom)
        result = rp.run_pipeline(source_id=source.id)

        assert result.failed == [source.id]
        assert result.succeeded == []
        assert not result.ok

    def test_returned_run_that_is_not_completed_is_a_failure(self, monkeypatch):
        """A returned run is not proof of success.

        The old code logged "Pipeline completed: Run N" off whatever came back, so a run
        that ended FAILED without raising was reported as a success.
        """
        source = _make_source("file://not-completed.html")

        def _returns_failed_run(self, source, **kwargs):
            return IngestRun.objects.create(
                source=source, status=IngestStatus.FAILED, stage=IngestStage.PENDING
            )

        monkeypatch.setattr(rp.PipelineOrchestrator, "run", _returns_failed_run)
        result = rp.run_pipeline(source_id=source.id)

        assert result.failed == [source.id]
        assert not result.ok

    def test_completed_source_succeeds(self, monkeypatch):
        source = _make_source("file://happy.html")

        def _ok(self, source, **kwargs):
            return IngestRun.objects.create(
                source=source, status=IngestStatus.COMPLETED, stage=IngestStage.PENDING
            )

        monkeypatch.setattr(rp.PipelineOrchestrator, "run", _ok)
        result = rp.run_pipeline(source_id=source.id)

        assert result.succeeded == [source.id]
        assert result.failed == []
        assert result.ok


@pytest.mark.django_db
class TestRunPipelineExitCode:
    """The exit code is the ONLY thing a driver looping over sources can read."""

    def test_main_exits_nonzero_when_a_source_fails(self, monkeypatch):
        source = _make_source("file://exit-nonzero.html")

        def _boom(self, source, **kwargs):
            raise RuntimeError("parser blew up")

        monkeypatch.setattr(rp.PipelineOrchestrator, "run", _boom)
        monkeypatch.setattr(
            sys, "argv", ["run_pipeline.py", "run", "--source-id", str(source.id)]
        )

        with pytest.raises(SystemExit) as exc:
            rp.main()
        assert exc.value.code == 1, "a FAILED source must not exit 0 — this is the 07-16 bug"

    def test_main_exits_zero_when_the_source_completes(self, monkeypatch):
        source = _make_source("file://exit-zero.html")

        def _ok(self, source, **kwargs):
            return IngestRun.objects.create(
                source=source, status=IngestStatus.COMPLETED, stage=IngestStage.PENDING
            )

        monkeypatch.setattr(rp.PipelineOrchestrator, "run", _ok)
        monkeypatch.setattr(
            sys, "argv", ["run_pipeline.py", "run", "--source-id", str(source.id)]
        )

        # A clean run must NOT start failing — the guard has to discriminate, not just fail.
        rp.main()


@pytest.mark.django_db
class TestRefreshBulletinPartialFailure:
    """The LIVE hourly path: `ingested > 0` is not success when more than one was pending."""

    def _stub_side_effects(self, monkeypatch, ingested: int, pending: list[int]):
        monkeypatch.setattr(rb, "_ensure_methodology_blog_post", lambda: None)
        monkeypatch.setattr(rb, "discover_bulletin_sources", lambda: [])
        monkeypatch.setattr(rb, "get_pending_bulletin_source_ids", lambda: pending)
        monkeypatch.setattr(rb, "ingest_sources", lambda ids: ingested)
        monkeypatch.setattr(rb, "_publish_predictions_for_latest_bulletin", lambda n: None)
        monkeypatch.setattr(rb, "_generate_blog_posts_for_latest_bulletins", lambda n: None)
        monkeypatch.setattr(rb, "_purge_cloudflare_edge", lambda: None)
        monkeypatch.setattr(rb.cache, "clear", lambda: None)

    def test_partial_failure_exits_nonzero(self, monkeypatch):
        """1 of 3 ingested used to exit 0 — the bridge saw green while 2 sources failed."""
        self._stub_side_effects(monkeypatch, ingested=1, pending=[1, 2, 3])
        with pytest.raises(SystemExit) as exc:
            rb.main()
        assert exc.value.code == 1

    def test_total_failure_still_exits_nonzero(self, monkeypatch):
        """Pre-existing behaviour that must not regress."""
        self._stub_side_effects(monkeypatch, ingested=0, pending=[1, 2, 3])
        with pytest.raises(SystemExit) as exc:
            rb.main()
        assert exc.value.code == 1

    def test_all_ingested_exits_zero(self, monkeypatch):
        self._stub_side_effects(monkeypatch, ingested=3, pending=[1, 2, 3])
        rb.main()

    def test_nothing_pending_exits_zero(self, monkeypatch):
        """The common hourly case: no new bulletin. Must stay silent, not alert."""
        self._stub_side_effects(monkeypatch, ingested=0, pending=[])
        rb.main()
