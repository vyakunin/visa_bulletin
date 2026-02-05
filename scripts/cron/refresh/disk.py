# scripts/cron/refresh/disk.py
"""Disk space check for pipeline (optional guard)."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def check_disk_space(threshold_percent: float = 10.0, path: Path | str = "/") -> bool:
    """Return True if free disk space at path is above threshold_percent of total."""
    try:
        stat = shutil.disk_usage(Path(path))
        free_pct = 100.0 * stat.free / stat.total if stat.total else 0
        if free_pct < threshold_percent:
            logger.warning(
                "Low disk space: %.1f%% free at %s (threshold %.1f%%)",
                free_pct,
                path,
                threshold_percent,
            )
            return False
        return True
    except OSError as e:
        logger.warning("Could not check disk space at %s: %s", path, e)
        return True  # Proceed if check fails
