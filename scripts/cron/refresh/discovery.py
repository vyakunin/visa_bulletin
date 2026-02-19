# scripts/cron/refresh/discovery.py
"""Check for new data sources (check-completeness). Uses runner."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)


def check_new_sources(
    runner: Runner, project_root: str | None = None
) -> tuple[int, str]:
    """Run check-completeness via runner; return (new_sources_count, output)."""
    from pathlib import Path
    cwd = Path(project_root) if project_root else None
    result = runner.run_bin(
        "scripts/ingest/run_pipeline",
        "check-completeness",
        cwd=cwd,
    )
    out = getattr(result, "stdout", "") or ""
    err = getattr(result, "stderr", "") or ""
    output = out + err
    # RemoteRunner does not capture stdout/stderr (output goes to stage log only)
    if not output.strip() and hasattr(runner, "read_stage_log_tail"):
        output = runner.read_stage_log_tail(800) or ""
    count = 0
    for line in output.splitlines():
        if "Not ingested (available)" in line:
            count += 1
    logger.info("Discovery: %s new data sources to ingest", count)
    return count, output
