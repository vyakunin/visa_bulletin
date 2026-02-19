# tests/test_refresh_pipeline.py
"""Unit tests for scripts/cron/refresh pipeline: run_pipeline with MockRunner."""

from pathlib import Path

import pytest

from scripts.cron.refresh.config import RefreshConfig
from scripts.cron.refresh.pipeline import run_pipeline
from scripts.cron.refresh.runner import MockRunner


def test_run_pipeline_mock_no_resume(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=visa_bulletin_green\n")
    config = RefreshConfig(
        project_root=tmp_path,
        env_file=env_file,
        backup_dir=tmp_path / "backups",
        db_name="visa_bulletin_green",
        single_db_on_host=True,
    )
    config.backup_dir.mkdir(parents=True, exist_ok=True)
    mock = MockRunner()
    mock.run_bin_return = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    mock.run_psql_return = "100000"
    mock.run_sudo_psql_return = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    mock.run_migrate_return = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
    with pytest.raises(RuntimeError):
        run_pipeline(config, mock, resume=False)
    call_names = [c[0] for c in mock.calls]
    assert "run_bin" in call_names or "run_psql" in call_names
    assert "read_checkpoint" in call_names
    assert "write_checkpoint" in call_names


def test_should_skip_step_order() -> None:
    from scripts.cron.refresh.checkpoint import should_skip_step
    assert should_skip_step("db_created", "db_created") is True
    assert should_skip_step("db_created", "index_snapshot_saved") is False
    assert should_skip_step("smoke_tests", "db_created") is True
    assert should_skip_step("smoke_tests", "swap_db") is False
