# tests/test_refresh_checkpoint.py
"""Unit tests for scripts/cron/refresh checkpoint: should_skip_step, read/write."""

import json
import tempfile
from pathlib import Path

import pytest

from scripts.cron.refresh.checkpoint import (
    CheckpointData,
    STEPS_ORDER,
    read_checkpoint,
    should_skip_step,
    write_checkpoint,
)


def test_should_skip_step_no_resume() -> None:
    assert should_skip_step(None, "db_created") is False
    assert should_skip_step(None, "swap_done") is False


def test_should_skip_step_resume_before() -> None:
    assert should_skip_step("ingest_complete", "db_created") is True
    assert should_skip_step("ingest_complete", "indexes_dropped") is True
    assert should_skip_step("ingest_complete", "ingest_complete") is True


def test_should_skip_step_resume_after() -> None:
    assert should_skip_step("ingest_complete", "backfill_links_done") is False
    assert should_skip_step("ingest_complete", "swap_done") is False


def test_checkpoint_data_roundtrip() -> None:
    data = CheckpointData(
        last_step="smoke_done",
        timestamp="2025-01-01T12:00:00Z",
        inactive_db="visa_bulletin_green",
        index_snapshot="/backups/indexes.yaml",
    )
    d = data.to_dict()
    assert d["last_step"] == "smoke_done"
    assert d["inactive_db"] == "visa_bulletin_green"
    restored = CheckpointData.from_dict(d)
    assert restored.last_step == data.last_step
    assert restored.inactive_db == data.inactive_db
    assert restored.index_snapshot == data.index_snapshot


def test_read_write_checkpoint(tmp_path: Path) -> None:
    path = tmp_path / "refresh_checkpoint.json"
    data = CheckpointData(
        last_step="indexes_dropped",
        timestamp="2025-01-01T12:00:00Z",
        inactive_db="visa_bulletin_green",
        index_snapshot="/backups/snapshot.yaml",
    )
    write_checkpoint(path, data, merge_index_snapshot=False)
    assert path.exists()
    read = read_checkpoint(path)
    assert read is not None
    assert read.last_step == data.last_step
    assert read.index_snapshot == data.index_snapshot


def test_write_checkpoint_preserves_index_snapshot(tmp_path: Path) -> None:
    path = tmp_path / "refresh_checkpoint.json"
    path.write_text(json.dumps({"last_step": "indexes_dropped", "timestamp": "Z", "index_snapshot": "/keep.yaml"}))
    data = CheckpointData(last_step="ingest_complete", timestamp="2025-01-02Z", inactive_db="green", index_snapshot="")
    write_checkpoint(path, data, merge_index_snapshot=True)
    read = read_checkpoint(path)
    assert read is not None
    assert read.last_step == "ingest_complete"
    assert read.index_snapshot == "/keep.yaml"
