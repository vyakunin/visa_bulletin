# tests/test_refresh_steps.py
"""Unit tests for individual pipeline step functions in scripts/cron/refresh/steps.py.

Tests use MockRunner with controlled return values to verify step behavior
on both success and failure paths.
"""

import subprocess
from pathlib import Path

import pytest

from scripts.cron.refresh.config import RefreshConfig
from scripts.cron.refresh.runner import MockRunner
from scripts.cron.refresh.steps import (
    PipelineContext,
    _parse_salary_relevant_count,
    _parse_sources_ingested_count,
    step_backfill_job_title_links,
    step_backfill_source_file_date,
    step_build_pipeline_binaries,
    step_cluster_job_titles,
    step_create_db,
    step_drop_indexes_save_snapshot,
    step_ensure_db,
    step_restore_indexes,
    step_run_ingest,
    step_start_services,
    step_update_employer_stats,
    step_vacuum_analyze,
    step_warm_cache,
)


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


def _ok(stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=stderr
    )


def _fail(
    rc: int = 1, stdout: str = "", stderr: str = "error"
) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[], returncode=rc, stdout=stdout, stderr=stderr
    )


# ---------------------------------------------------------------------------
# step_build_pipeline_binaries
# ---------------------------------------------------------------------------


def test_build_pipeline_binaries_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    ctx = PipelineContext()
    step_build_pipeline_binaries(config, runner, ctx)
    shell_calls = [c for c in runner.calls if c[0] == "run_shell"]
    assert len(shell_calls) == 1
    assert "build_all.sh" in shell_calls[0][1][0]


def test_build_pipeline_binaries_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_shell = lambda cmd, **kw: (
        runner.calls.append(("run_shell", (cmd,), kw)) or _fail()
    )
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Build pipeline binaries failed"):
        step_build_pipeline_binaries(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_run_ingest: parses source counts from output
# ---------------------------------------------------------------------------


def test_parse_sources_ingested_count() -> None:
    assert _parse_sources_ingested_count("Starting pipeline for 5 sources") == 5
    assert _parse_sources_ingested_count("Starting pipeline for 0 sources") == 0
    assert _parse_sources_ingested_count("No matching line") == 0


def test_parse_salary_relevant_count() -> None:
    assert _parse_salary_relevant_count("(salary_relevant: 3)") == 3
    assert _parse_salary_relevant_count("(salary_relevant:  12)") == 12
    assert _parse_salary_relevant_count("no match") is None


def test_step_run_ingest_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _ok(
        stdout="Starting pipeline for 7 sources (salary_relevant: 4)"
    )
    ctx = PipelineContext()
    sources, salary = step_run_ingest(config, runner, ctx)
    assert sources == 7
    assert salary == 4


def test_step_run_ingest_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail(stderr="timeout")
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Ingest failed"):
        step_run_ingest(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_restore_indexes: handles missing snapshot gracefully
# ---------------------------------------------------------------------------


def test_step_restore_indexes_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _ok()
    runner.run_sudo_psql_return = _ok()
    ctx = PipelineContext(
        db_name="visa_bulletin",
        index_snapshot="/backups/snap.yaml",
    )
    step_restore_indexes(config, runner, ctx)
    bin_calls = [c for c in runner.calls if c[0] == "run_bin"]
    assert any("--recreate" in c[1] for c in bin_calls)


def test_step_restore_indexes_missing_snapshot_path(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    ctx = PipelineContext(db_name="visa_bulletin", index_snapshot="")
    with pytest.raises(RuntimeError, match="Index snapshot path not set"):
        step_restore_indexes(config, runner, ctx)


def test_step_restore_indexes_snapshot_file_not_found_fallback(tmp_path: Path) -> None:
    """When snapshot file doesn't exist on remote, falls back to --create-clustering-indexes."""
    config = _make_config(tmp_path)
    runner = MockRunner()

    call_count = [0]

    def side_effect(rel_path, *args, **kwargs):
        runner.calls.append(("run_bin", (rel_path, *args), kwargs))
        call_count[0] += 1
        if call_count[0] == 1:
            return _fail(stdout="Snapshot file not found")
        return _ok()

    runner.run_bin = side_effect
    runner.run_sudo_psql_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin", index_snapshot="/backups/snap.yaml")
    step_restore_indexes(config, runner, ctx)


def test_step_restore_indexes_both_fail(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()

    def always_fail(rel_path, *args, **kwargs):
        runner.calls.append(("run_bin", (rel_path, *args), kwargs))
        return _fail(stdout="Snapshot file not found")

    runner.run_bin = always_fail
    runner.run_sudo_psql_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin", index_snapshot="/backups/snap.yaml")
    with pytest.raises(RuntimeError, match="Recreate indexes failed"):
        step_restore_indexes(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_start_services: handles Docker failures
# ---------------------------------------------------------------------------


def test_step_start_services_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    ctx = PipelineContext()
    step_start_services(config, runner, ctx)
    shell_calls = [c for c in runner.calls if c[0] == "run_shell"]
    assert len(shell_calls) >= 1


def test_step_start_services_docker_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()

    def fail_shell(cmd, **kw):
        runner.calls.append(("run_shell", (cmd,), kw))
        if "docker-compose" in cmd and "up" in cmd:
            return _fail(stderr="Docker daemon not running")
        return _ok()

    runner.run_shell = fail_shell
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Failed to start remote services"):
        step_start_services(config, runner, ctx)


# ---------------------------------------------------------------------------
# Heavy step wrappers: verify failure propagation
# ---------------------------------------------------------------------------


def test_step_backfill_job_title_links_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail()
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Backfill job title links failed"):
        step_backfill_job_title_links(config, runner, ctx)


def test_step_backfill_source_file_date_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail()
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Backfill source file date failed"):
        step_backfill_source_file_date(config, runner, ctx)


def test_step_cluster_job_titles_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail()
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Cluster job titles failed"):
        step_cluster_job_titles(config, runner, ctx)


def test_step_update_employer_stats_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail()
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Update employer stats failed"):
        step_update_employer_stats(config, runner, ctx)


def test_step_warm_cache_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail()
    ctx = PipelineContext()
    with pytest.raises(RuntimeError, match="Warm cache failed"):
        step_warm_cache(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_ensure_db: creates DB only when missing
# ---------------------------------------------------------------------------


def test_step_ensure_db_creates_when_missing(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_sudo_psql_return = _ok(stdout="")
    runner.run_migrate_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin")
    step_ensure_db(config, runner, ctx)

    sudo_calls = [c for c in runner.calls if c[0] == "run_sudo_psql"]
    sql_strs = [c[1][0] for c in sudo_calls]
    assert any("CREATE DATABASE" in s for s in sql_strs)


def test_step_ensure_db_skips_create_when_exists(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_sudo_psql_return = _ok(stdout="1")
    runner.run_migrate_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin")
    step_ensure_db(config, runner, ctx)

    sudo_calls = [c for c in runner.calls if c[0] == "run_sudo_psql"]
    sql_strs = [c[1][0] for c in sudo_calls]
    assert not any("CREATE DATABASE" in s for s in sql_strs)


def test_step_ensure_db_migration_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_sudo_psql_return = _ok(stdout="1")
    runner.run_migrate_return = _fail(stderr="migration error")
    ctx = PipelineContext(db_name="visa_bulletin")
    with pytest.raises(RuntimeError, match="Migrations failed"):
        step_ensure_db(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_create_db
# ---------------------------------------------------------------------------


def test_step_create_db_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_sudo_psql_return = _ok()
    runner.run_migrate_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin")
    step_create_db(config, runner, ctx)

    sudo_calls = [c for c in runner.calls if c[0] == "run_sudo_psql"]
    sql_strs = [c[1][0] for c in sudo_calls]
    assert any("DROP DATABASE" in s for s in sql_strs)
    assert any("CREATE DATABASE" in s for s in sql_strs)


# ---------------------------------------------------------------------------
# step_drop_indexes_save_snapshot
# ---------------------------------------------------------------------------


def test_step_drop_indexes_success(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _ok()
    runner.run_sudo_psql_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin")
    snapshot = step_drop_indexes_save_snapshot(config, runner, ctx)
    assert snapshot
    assert "salary_indexes_" in snapshot


def test_step_drop_indexes_failure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    runner.run_bin_return = _fail(stderr="index error")
    runner.run_sudo_psql_return = _ok()
    ctx = PipelineContext(db_name="visa_bulletin")
    with pytest.raises(RuntimeError, match="Drop indexes failed"):
        step_drop_indexes_save_snapshot(config, runner, ctx)


# ---------------------------------------------------------------------------
# step_vacuum_analyze
# ---------------------------------------------------------------------------


def test_step_vacuum_analyze_calls_psql(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    runner = MockRunner()
    ctx = PipelineContext(db_name="visa_bulletin")
    step_vacuum_analyze(config, runner, ctx)
    psql_calls = [c for c in runner.calls if c[0] == "run_psql"]
    assert len(psql_calls) == 1
    assert "VACUUM ANALYZE" in psql_calls[0][1][1]
