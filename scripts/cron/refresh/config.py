# scripts/cron/refresh/config.py
"""Refresh pipeline configuration: paths, .env, DB name, single_db_on_host."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class RefreshConfig:
    """Configuration for the refresh pipeline (local or remote)."""

    project_root: Path
    env_file: Path
    backup_dir: Path
    db_name: str
    single_db_on_host: bool
    db_user: str = "visa_bulletin_user"
    db_host: str = "localhost"
    db_port: str = "5432"
    max_backups: int = 3
    # Required binary paths (relative to project_root / bazel-bin)
    required_binaries: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.required_binaries:
            self.required_binaries = [
                "scripts/ingest/run_pipeline",
                "scripts/salary/manage_salary_indexes",
                "scripts/salary/backfill_job_title_links",
                "scripts/salary/backfill_source_file_date",
                "scripts/salary/cluster_job_titles",
                "scripts/salary/update_employer_stats",
                "scripts/salary/cluster_existing_employers",
                "scripts/salary/update_job_title_cluster_stats",
                "scripts/salary/populate_job_title_slugs",
                "scripts/cache/warm_cache",
            ]

    @property
    def bazel_bin(self) -> Path:
        return self.project_root / "bazel-bin"

    @property
    def checkpoint_path(self) -> Path:
        return self.backup_dir / "refresh_checkpoint.json"


def load_config(project_root: Path | str | None = None) -> RefreshConfig:
    """Load config from project root. Uses REFRESH_BACKUP_DIR and REFRESH_SINGLE_DB_ON_HOST from env."""
    root = Path(project_root or os.environ.get("BUILD_WORKSPACE_DIRECTORY", ".")).resolve()
    env_file = root / ".env"
    if not env_file.exists():
        env_file = root / ".env.example"

    backup_dir = _resolve_backup_dir(root)
    db_name = get_env_value(env_file, "DB_NAME") or ""
    single_db = os.environ.get("REFRESH_SINGLE_DB_ON_HOST", "").strip().lower() in ("1", "true", "yes")
    db_user = get_env_value(env_file, "DB_USER") or "visa_bulletin_user"
    db_host = get_env_value(env_file, "DB_HOST") or "localhost"
    if db_host == "host.docker.internal":
        db_host = "localhost"
    db_port = get_env_value(env_file, "DB_PORT") or "5432"

    return RefreshConfig(
        project_root=root,
        env_file=root / ".env",
        backup_dir=backup_dir,
        db_name=db_name,
        single_db_on_host=single_db,
        db_user=db_user,
        db_host=db_host,
        db_port=db_port,
    )


def _resolve_backup_dir(project_root: Path) -> Path:
    if os.environ.get("REFRESH_BACKUP_DIR"):
        p = Path(os.environ["REFRESH_BACKUP_DIR"])
        p.mkdir(parents=True, exist_ok=True)
        return p.resolve()
    p = Path("/var/backups/visa-bulletin")
    try:
        p.mkdir(parents=True, exist_ok=True)
        if os.access(p, os.W_OK):
            return p
    except OSError:
        pass
    fallback = project_root / "backups"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def get_env_value(env_file: Path, key: str) -> str | None:
    """Read first key=value from env file; value is rest of line after first '='."""
    if not env_file.exists():
        return None
    for line in env_file.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return None


def update_env_value(env_file: Path, key: str, value: str) -> None:
    """Update or append key=value in env file."""
    path = Path(env_file)
    lines = path.read_text().splitlines() if path.exists() else []
    new_lines: list[str] = []
    found = False
    for line in lines:
        if line.startswith(f"{key}="):
            new_lines.append(f"{key}={value}")
            found = True
        else:
            new_lines.append(line)
    if not found:
        new_lines.append(f"{key}={value}")
    path.write_text("\n".join(new_lines) + "\n")
