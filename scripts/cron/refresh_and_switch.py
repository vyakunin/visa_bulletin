#!/usr/bin/env python3
# scripts/cron/refresh_and_switch.py
"""Orchestrator entry point: resolve active/inactive, run pipeline on inactive, optional traffic switch."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.cron.refresh.config import load_config
from scripts.cron.refresh.orchestrate import run_orchestrate


def main() -> int:
    parser = argparse.ArgumentParser(description="Orchestrate data refresh on inactive instance (prod -> staging)")
    parser.add_argument("--no-traffic-switch", action="store_true", help="Skip traffic switch (first validation run)")
    parser.add_argument("--resume", action="store_true", help="Resume pipeline from checkpoint on inactive")
    parser.add_argument(
        "--from-step",
        type=str,
        default=None,
        choices=["traffic_switch"],
        help="Start from this step (skip pipeline). Use traffic_switch after validating with --no-traffic-switch.",
    )
    parser.add_argument("--safety-interval", type=int, default=1800, help="Seconds to wait after traffic switch (default 1800)")
    parser.add_argument("--skip-stop-old", action="store_true", help="Keep old instance running after switch (graduation mode)")
    parser.add_argument("--project-root", type=Path, default=None, help="Project root")
    args = parser.parse_args()
    root = args.project_root or Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", ".")).resolve()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    if os.geteuid() == 0:
        logger.error("refresh_and_switch.py must run as a non-root user")
        return 1
    config = load_config(root)
    return run_orchestrate(
        config,
        safety_interval_sec=args.safety_interval,
        no_traffic_switch=args.no_traffic_switch,
        resume=args.resume,
        from_step=args.from_step,
        skip_stop_old=args.skip_stop_old,
    )


if __name__ == "__main__":
    sys.exit(main())
