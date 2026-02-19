# scripts/cron/refresh/checkpoint.py
"""Checkpoint for pipeline resume: STEPS_ORDER, read/write JSON, should_skip_step."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

# Map old step names (from existing checkpoints) to current names for backward compatibility
OLD_STEP_NAME_TO_NEW: dict[str, str] = {
    "backfill_links_done": "backfill_job_title_links",
    "backfill_dates_done": "backfill_source_file_date",
    "cluster_job_titles_done": "cluster_job_titles",
    "employer_stats_done": "update_employer_stats",
    "cluster_employers_done": "cluster_employers",
    "job_title_stats_done": "update_job_title_cluster_stats",
    "slugs_done": "populate_job_title_slugs",
    "vacuum_done": "vacuum_analyze",
    "warm_cache_done": "warm_cache",
    "smoke_done": "smoke_tests",
    "swap_done": "swap_db",
}

STEPS_ORDER: tuple[str, ...] = (
    "db_created",
    "index_snapshot_saved",
    "ingest_complete",
    "backfill_job_title_links",
    "backfill_source_file_date",
    "cluster_job_titles",
    "indexes_restored",
    "update_employer_stats",
    "cluster_employers",
    "update_job_title_cluster_stats",
    "populate_job_title_slugs",
    "vacuum_analyze",
    "start_services",
    "warm_cache",
    "smoke_tests",
    "swap_db",
)


@dataclass
class CheckpointData:
    """Checkpoint payload: last_step, timestamp, inactive_db/db_name, index_snapshot."""

    last_step: str
    timestamp: str
    inactive_db: str = ""
    index_snapshot: str = ""

    def to_dict(self) -> dict:
        d: dict = {"last_step": self.last_step, "timestamp": self.timestamp}
        if self.inactive_db:
            d["inactive_db"] = self.inactive_db
        if self.index_snapshot:
            d["index_snapshot"] = self.index_snapshot
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CheckpointData:
        return cls(
            last_step=str(d.get("last_step", "")),
            timestamp=str(d.get("timestamp", "")),
            inactive_db=str(d.get("inactive_db", "")),
            index_snapshot=str(d.get("index_snapshot", "")),
        )


def should_skip_step(resume_from: str | None, step: str) -> bool:
    """True if we are resuming and this step is already completed (order <= resume_from)."""
    if not resume_from:
        return False
    try:
        i = STEPS_ORDER.index(step)
        j = STEPS_ORDER.index(resume_from)
        return i <= j
    except ValueError:
        return False


def read_checkpoint(path: Path) -> CheckpointData | None:
    """Read checkpoint from JSON file. Returns None if missing or invalid."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return CheckpointData.from_dict(data)
    except (json.JSONDecodeError, OSError):
        return None


def write_checkpoint(path: Path, data: CheckpointData, merge_index_snapshot: bool = True) -> None:
    """Write checkpoint atomically (write to .tmp then rename). Optionally preserve index_snapshot from existing file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if merge_index_snapshot and path.exists():
        existing = read_checkpoint(path)
        if existing and existing.index_snapshot and not data.index_snapshot:
            data = CheckpointData(
                last_step=data.last_step,
                timestamp=data.timestamp,
                inactive_db=data.inactive_db or existing.inactive_db,
                index_snapshot=existing.index_snapshot,
            )
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data.to_dict(), indent=2))
    tmp.replace(path)
