# tests/test_refresh_checkpoint.py
"""Unit tests for scripts/cron/refresh checkpoint: should_skip_step, read/write."""

import json
from pathlib import Path

from scripts.cron.refresh.checkpoint import (
    OLD_STEP_NAME_TO_NEW,
    CheckpointData,
    read_checkpoint,
    should_skip_step,
    write_checkpoint,
)


def test_should_skip_step_no_resume() -> None:
    assert should_skip_step(None, "ensure_db") is False
    assert should_skip_step(None, "smoke_tests") is False


def test_should_skip_step_resume_before() -> None:
    assert should_skip_step("ingest_complete", "ensure_db") is True
    assert should_skip_step("ingest_complete", "index_snapshot_saved") is True
    assert should_skip_step("ingest_complete", "ingest_complete") is True


def test_should_skip_step_resume_after() -> None:
    assert should_skip_step("ingest_complete", "backfill_job_title_links") is False
    assert should_skip_step("ingest_complete", "smoke_tests") is False


def test_checkpoint_data_roundtrip() -> None:
    data = CheckpointData(
        last_step="smoke_tests",
        timestamp="2025-01-01T12:00:00Z",
        inactive_db="visa_bulletin",
        index_snapshot="/backups/indexes.yaml",
    )
    d = data.to_dict()
    assert d["last_step"] == "smoke_tests"
    assert d["inactive_db"] == "visa_bulletin"
    restored = CheckpointData.from_dict(d)
    assert restored.last_step == data.last_step
    assert restored.inactive_db == data.inactive_db
    assert restored.index_snapshot == data.index_snapshot


def test_read_write_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "refresh_checkpoint.json"
    data = CheckpointData(
        last_step="index_snapshot_saved",
        timestamp="2025-01-01T12:00:00Z",
        inactive_db="visa_bulletin",
        index_snapshot="/backups/snapshot.yaml",
    )
    write_checkpoint(path, data, merge_index_snapshot=False)
    assert path.exists()
    read = read_checkpoint(path)
    assert read is not None
    assert read.last_step == data.last_step
    assert read.index_snapshot == data.index_snapshot


def test_old_step_name_mapping_resume() -> None:
    """Resume with old checkpoint last_step is equivalent to new name for skip logic."""
    assert OLD_STEP_NAME_TO_NEW["db_created"] == "ensure_db"
    assert OLD_STEP_NAME_TO_NEW["swap_done"] == "smoke_tests"
    assert OLD_STEP_NAME_TO_NEW["cluster_employers_done"] == "cluster_employers"
    assert OLD_STEP_NAME_TO_NEW["employer_stats_done"] == "update_employer_stats"
    # Resuming from old name (after normalization) should skip that step
    assert should_skip_step("cluster_employers", "cluster_employers") is True
    assert (
        should_skip_step("cluster_employers", "update_job_title_cluster_stats") is False
    )


def test_write_checkpoint_preserves_index_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "refresh_checkpoint.json"
    path.write_text(
        json.dumps(
            {
                "last_step": "index_snapshot_saved",
                "timestamp": "Z",
                "index_snapshot": "/keep.yaml",
            }
        )
    )
    data = CheckpointData(
        last_step="ingest_complete",
        timestamp="2025-01-02Z",
        inactive_db="visa_bulletin",
        index_snapshot="",
    )
    write_checkpoint(path, data, merge_index_snapshot=True)
    read = read_checkpoint(path)
    assert read is not None
    assert read.last_step == "ingest_complete"
    assert read.index_snapshot == "/keep.yaml"
