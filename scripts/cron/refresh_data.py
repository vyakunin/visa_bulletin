#!/usr/bin/env python3
# scripts/cron/refresh_data.py
"""Local refresh entry point: run pipeline with LocalRunner. Supports --resume."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is on path when run via cron or direct
_script_dir = Path(__file__).resolve().parent
_project_root = _script_dir.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scripts.cron.refresh.config import load_config
from scripts.cron.refresh.pipeline import run_pipeline
from scripts.cron.refresh.runner import LocalRunner


def main() -> int:
    parser = argparse.ArgumentParser(description="Run data refresh pipeline (local)")
    parser.add_argument("--resume", action="store_true", help="Resume from last checkpoint")
    parser.add_argument("--project-root", type=Path, default=None, help="Project root (default: BUILD_WORKSPACE_DIRECTORY or .)")
    args = parser.parse_args()
    root = args.project_root or Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", ".")).resolve()
    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s] %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logger = logging.getLogger(__name__)
    if os.geteuid() == 0:
        logger.error("refresh_data.py must run as a non-root user")
        return 1
    config = load_config(root)
    if not config.db_name:
        logger.error("DB_NAME not found in .env")
        return 1
    from scripts.cron.refresh.config import get_env_value
    env = dict(os.environ)
    for key in ("DB_USER", "DB_PASSWORD", "DB_HOST", "DB_PORT", "DB_NAME"):
        v = get_env_value(config.env_file, key)
        if v is not None:
            env[key] = v
    if env.get("DB_HOST") == "host.docker.internal":
        env["DB_HOST"] = "localhost"
    if env.get("DB_PASSWORD"):
        env["PGPASSWORD"] = env["DB_PASSWORD"]
    runner = LocalRunner(config.project_root, config.env_file, env)
    return run_pipeline(config, runner, resume=args.resume)


if __name__ == "__main__":
    sys.exit(main())
