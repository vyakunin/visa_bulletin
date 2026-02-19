# tests/test_refresh_config.py
"""Unit tests for scripts/cron/refresh config: load_config, get_env_value, update_env_value."""

import os
from pathlib import Path

from scripts.cron.refresh.config import (
    get_env_value,
    load_config,
    update_env_value,
)


def test_get_env_value_missing_file() -> None:
    assert get_env_value(Path("/nonexistent"), "DB_NAME") is None


def test_get_env_value_present(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=visa_bulletin_blue\nDB_USER=u\n")
    assert get_env_value(env_file, "DB_NAME") == "visa_bulletin_blue"
    assert get_env_value(env_file, "DB_USER") == "u"
    assert get_env_value(env_file, "MISSING") is None


def test_update_env_value_new_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\n")
    update_env_value(env_file, "DB_NAME", "visa_bulletin")
    assert get_env_value(env_file, "DB_NAME") == "visa_bulletin"
    assert get_env_value(env_file, "A") == "1"


def test_update_env_value_existing_key(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("DB_NAME=old\nA=1\n")
    update_env_value(env_file, "DB_NAME", "new")
    assert get_env_value(env_file, "DB_NAME") == "new"
    assert get_env_value(env_file, "A") == "1"


def test_load_config_project_root(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DB_NAME=visa_bulletin\n")
    config = load_config(tmp_path)
    assert config.project_root == tmp_path.resolve()
    assert config.db_name == "visa_bulletin"
    assert config.env_file == tmp_path / ".env"


def test_load_config_single_db_from_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DB_NAME=visa_bulletin\n")
    os.environ["REFRESH_SINGLE_DB_ON_HOST"] = "1"
    try:
        config = load_config(tmp_path)
        assert config.single_db_on_host is True
    finally:
        os.environ.pop("REFRESH_SINGLE_DB_ON_HOST", None)
