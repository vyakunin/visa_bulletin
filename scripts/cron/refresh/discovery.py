# scripts/cron/refresh/discovery.py
"""Check for new data sources (check-completeness). Uses runner."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .runner import Runner

logger = logging.getLogger(__name__)

# check-completeness prints: "  ✗ Not ingested (available): 123"
_NOT_INGESTED_RE = re.compile(r"Not ingested \(available\):\s*(\d+)")


def check_new_sources(
    runner: Runner, project_root: str | None = None
) -> tuple[int, str]:
    """Run check-completeness via runner; return (not_ingested_count, output)."""
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
        m = _NOT_INGESTED_RE.search(line)
        if m:
            count = int(m.group(1))
            break
    logger.info("Discovery: %s new data sources to ingest", count)
    return count, output
