# tests/test_refresh_pipeline.py
"""Unit tests for scripts/cron/refresh pipeline: run_pipeline with MockRunner.

Coverage:
- Full pipeline run (happy path)
- Step failure + checkpoint correctness (H1)
- Resume from checkpoint skips completed steps (H1)
- Self-heal logic: 0 ingested, varying cluster/record counts (H3)
- should_skip_step ordering
"""

import subprocess
from pathlib import Path

import pytest

from scripts.cron.refresh.checkpoint import CheckpointData, STEPS_ORDER, should_skip_step
from scripts.cron.refresh.config import RefreshConfig
from scripts.cron.refresh.pipeline import (
    MIN_RECORDS_FOR_CLUSTER_SELF_HEAL,
    STEPS_SKIP_WHEN_ZERO_INGESTED,
    run_pipeline,
)
from scripts.cron.refresh.runner import MockRunner


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr=stderr)


def _fail(rc: int = 1, stdout: str = "", stderr: str = "error") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def _make_config(tmp_path: Path) -> RefreshConfig:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=visa_bulletin\n")
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    return RefreshConfig(
        project_root=tmp_path,
        env_file=env_file,
        backup_dir=backup_dir,
        db_name="visa_bulletin",
    )


def _make_happy_mock() -> MockRunner:
    """MockRunner configured so all steps succeed (full pipeline completion)."""
    mock = MockRunner()
    mock.run_bin_return = _ok(stdout="Starting pipeline for 5 sources (salary_relevant: 3)")
    mock.run_psql_return = "100000"
    mock.run_sudo_psql_return = _ok()
    mock.run_migrate_return = _ok()
    return mock


# ---------------------------------------------------------------------------
# Happy-path: full pipeline completes
# ---------------------------------------------------------------------------


def test_run_pipeline_full_success(tmp_path: Path) -> None:
    """All steps succeed → pipeline returns 0 and checkpoint is at smoke_tests."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    result = run_pipeline(config, mock, resume=False)
    assert result == 0
    assert mock._checkpoint is not None
    assert mock._checkpoint.last_step == "smoke_tests"


def test_run_pipeline_mock_no_resume(tmp_path: Path) -> None:
    """Backward-compat: pipeline records calls and writes checkpoint."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    run_pipeline(config, mock, resume=False)
    call_names = [c[0] for c in mock.calls]
    assert "run_bin" in call_names or "run_psql" in call_names
    assert "read_checkpoint" in call_names
    assert "write_checkpoint" in call_names


# ---------------------------------------------------------------------------
# H1: Step failure + checkpoint correctness
# ---------------------------------------------------------------------------


def test_step_failure_checkpoints_last_successful_step(tmp_path: Path) -> None:
    """When a step fails, checkpoint records the last SUCCESSFUL step, not the failed one."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    mock.run_bin_side_effects["scripts/salary/cluster_job_titles"] = _fail(stderr="OOM killed")
    with pytest.raises(RuntimeError, match="Cluster job titles failed"):
        run_pipeline(config, mock, resume=False)

    assert mock._checkpoint is not None
    assert mock._checkpoint.last_step == "backfill_source_file_date"


def test_step_failure_at_ingest_checkpoints_index_snapshot(tmp_path: Path) -> None:
    """Failure at ingest preserves the index snapshot in checkpoint for later resume."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    mock.run_bin_side_effects["scripts/ingest/run_pipeline"] = (
        lambda rel, *a: _ok(stdout="Starting pipeline for 3 sources")
        if "check-completeness" in a
        else _fail(stderr="ingest crash")
    )
    with pytest.raises(RuntimeError, match="Ingest failed"):
        run_pipeline(config, mock, resume=False)

    assert mock._checkpoint is not None
    assert mock._checkpoint.last_step == "index_snapshot_saved"
    assert "salary_indexes_" in mock._checkpoint.index_snapshot


# ---------------------------------------------------------------------------
# H1: Resume from checkpoint skips completed steps
# ---------------------------------------------------------------------------


def test_resume_skips_completed_steps(tmp_path: Path) -> None:
    """Resume from checkpoint after cluster_job_titles failure: re-runs from cluster_job_titles onward."""
    config = _make_config(tmp_path)

    # First run: fail at cluster_job_titles
    mock1 = _make_happy_mock()
    mock1.run_bin_side_effects["scripts/salary/cluster_job_titles"] = _fail()
    with pytest.raises(RuntimeError):
        run_pipeline(config, mock1, resume=False)
    saved_checkpoint = mock1._checkpoint
    assert saved_checkpoint is not None
    assert saved_checkpoint.last_step == "backfill_source_file_date"

    # Second run: resume with the checkpoint; cluster_job_titles now succeeds
    mock2 = _make_happy_mock()
    mock2._checkpoint = saved_checkpoint

    result = run_pipeline(config, mock2, resume=True)
    assert result == 0
    assert mock2._checkpoint.last_step == "smoke_tests"

    # Verify skipped steps are not re-executed (no run_bin for steps before cluster_job_titles)
    run_bin_calls = [c[1][0] for c in mock2.calls if c[0] == "run_bin"]
    assert "scripts/salary/backfill_job_title_links" not in run_bin_calls
    assert "scripts/salary/backfill_source_file_date" not in run_bin_calls
    # Discovery (check-completeness) still runs, but early pipeline steps are skipped
    skipped_logged = [c for c in mock2.calls if c[0] == "write_checkpoint"]
    assert len(skipped_logged) > 0


def test_resume_with_missing_checkpoint_starts_fresh(tmp_path: Path) -> None:
    """resume=True but no checkpoint file → starts from beginning."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    result = run_pipeline(config, mock, resume=True)
    assert result == 0
    assert mock._checkpoint.last_step == "smoke_tests"


# ---------------------------------------------------------------------------
# H3: Self-heal logic (0 ingested, varying DB states)
# ---------------------------------------------------------------------------


def test_zero_ingested_skips_post_processing_when_clusters_exist(tmp_path: Path) -> None:
    """0 sources ingested + >0 clustered employers → skip post-processing steps."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    # Ingest returns 0 sources
    mock.run_bin_side_effects["scripts/ingest/run_pipeline"] = (
        lambda rel, *a: _ok(stdout="Starting pipeline for 0 sources (salary_relevant: 0)")
        if "discover-and-ingest" in a
        else _ok()
    )
    # DB has clustered employers
    mock.run_psql_side_effects["canonical_cluster_id IS NOT NULL"] = "50000"
    mock.run_psql_return = "200000"

    result = run_pipeline(config, mock, resume=False)
    assert result == 0

    # Post-processing steps should be skipped (no run_bin for them)
    run_bin_calls = [c[1][0] for c in mock.calls if c[0] == "run_bin"]
    for skipped_binary in [
        "scripts/salary/backfill_job_title_links",
        "scripts/salary/cluster_job_titles",
        "scripts/salary/cluster_existing_employers",
    ]:
        assert skipped_binary not in run_bin_calls, f"{skipped_binary} should be skipped"


def test_zero_ingested_self_heals_when_no_clusters_and_enough_records(tmp_path: Path) -> None:
    """0 ingested + 0 clustered employers + 100k+ records → re-run post-processing (self-heal)."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    mock.run_bin_side_effects["scripts/ingest/run_pipeline"] = (
        lambda rel, *a: _ok(stdout="Starting pipeline for 0 sources (salary_relevant: 0)")
        if "discover-and-ingest" in a
        else _ok()
    )
    # 0 clustered employers but enough records
    mock.run_psql_side_effects["canonical_cluster_id IS NOT NULL"] = "0"
    mock.run_psql_side_effects["FROM salary_record;"] = str(MIN_RECORDS_FOR_CLUSTER_SELF_HEAL + 1)
    # Other psql queries return a safe default
    mock.run_psql_return = "200000"

    result = run_pipeline(config, mock, resume=False)
    assert result == 0

    # Self-heal should cause post-processing to run
    run_bin_calls = [c[1][0] for c in mock.calls if c[0] == "run_bin"]
    assert "scripts/salary/backfill_job_title_links" in run_bin_calls
    assert "scripts/salary/cluster_job_titles" in run_bin_calls


def test_zero_ingested_no_self_heal_when_few_records(tmp_path: Path) -> None:
    """0 ingested + 0 clustered employers + <100k records → no self-heal, skip post-processing."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    mock.run_bin_side_effects["scripts/ingest/run_pipeline"] = (
        lambda rel, *a: _ok(stdout="Starting pipeline for 0 sources (salary_relevant: 0)")
        if "discover-and-ingest" in a
        else _ok()
    )
    mock.run_psql_side_effects["canonical_cluster_id IS NOT NULL"] = "0"
    mock.run_psql_side_effects["FROM salary_record;"] = "500"
    mock.run_psql_return = "500"

    result = run_pipeline(config, mock, resume=False)
    assert result == 0

    run_bin_calls = [c[1][0] for c in mock.calls if c[0] == "run_bin"]
    assert "scripts/salary/backfill_job_title_links" not in run_bin_calls


def test_self_heal_query_error_falls_through_to_skip(tmp_path: Path) -> None:
    """If self-heal DB query returns unparseable result, treat as skip (don't crash)."""
    config = _make_config(tmp_path)
    mock = _make_happy_mock()
    mock.run_bin_side_effects["scripts/ingest/run_pipeline"] = (
        lambda rel, *a: _ok(stdout="Starting pipeline for 0 sources (salary_relevant: 0)")
        if "discover-and-ingest" in a
        else _ok()
    )
    # Return non-numeric to trigger ValueError in self-heal check
    mock.run_psql_side_effects["canonical_cluster_id IS NOT NULL"] = "ERROR"
    mock.run_psql_return = "200000"

    result = run_pipeline(config, mock, resume=False)
    assert result == 0

    # ValueError handled gracefully; steps are skipped
    run_bin_calls = [c[1][0] for c in mock.calls if c[0] == "run_bin"]
    assert "scripts/salary/backfill_job_title_links" not in run_bin_calls


# ---------------------------------------------------------------------------
# should_skip_step ordering
# ---------------------------------------------------------------------------


def test_should_skip_step_order() -> None:
    assert should_skip_step("ensure_db", "ensure_db") is True
    assert should_skip_step("ensure_db", "index_snapshot_saved") is False
    assert should_skip_step("smoke_tests", "ensure_db") is True
    assert should_skip_step("smoke_tests", "smoke_tests") is True


def test_should_skip_step_none_resume() -> None:
    assert should_skip_step(None, "ensure_db") is False
    assert should_skip_step(None, "smoke_tests") is False


def test_should_skip_step_unknown_step() -> None:
    assert should_skip_step("ensure_db", "nonexistent_step") is False
