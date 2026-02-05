# tests/test_refresh_orchestrate.py
"""Unit tests for scripts/cron/refresh orchestrate: run_orchestrate with --no-traffic-switch (mocked)."""

import os
from pathlib import Path
from unittest.mock import patch

from scripts.cron.refresh.config import load_config
from scripts.cron.refresh.instance import InstanceInfo
from scripts.cron.refresh.orchestrate import run_orchestrate


def test_run_orchestrate_no_op_when_inactive() -> None:
    """When this host is inactive, run_orchestrate no-ops and returns 0."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")
    os.environ["REFRESH_MY_INSTANCE_NAME"] = "Staging"
    try:
        with (
            patch("scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env") as m_resolve,
            patch("scripts.cron.refresh.orchestrate.instance.is_this_host_active") as m_is_active,
        ):
            m_resolve.return_value = (active, inactive)
            m_is_active.return_value = False
            result = run_orchestrate(config, no_traffic_switch=True)
        assert result == 0
        m_resolve.assert_called_once()
    finally:
        os.environ.pop("REFRESH_MY_INSTANCE_NAME", None)


def test_run_orchestrate_no_traffic_switch_runs_pipeline_then_exits() -> None:
    """With no_traffic_switch=True: resolve, start/health, run pipeline, then return 0 without switching."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch("scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env") as m_resolve,
        patch("scripts.cron.refresh.orchestrate.instance.is_this_host_active") as m_is_active,
        patch("scripts.cron.refresh.orchestrate.instance.get_instance_state") as m_state,
        patch("scripts.cron.refresh.orchestrate.instance.wait_instance_healthy") as m_healthy,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
        patch("scripts.cron.refresh.orchestrate.traffic_switch") as m_switch,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "running"
        m_healthy.return_value = True
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 0
    m_pipeline.assert_called_once()
    m_switch.switch_traffic_dns.assert_not_called()
    m_switch.switch_traffic_static_ip.assert_not_called()


def test_run_orchestrate_missing_env_returns_1() -> None:
    """When REFRESH_ACTIVE_* or REFRESH_INACTIVE_* are missing, return 1."""
    config = load_config(Path("."))
    with patch("scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env") as m_resolve:
        m_resolve.return_value = (None, None)
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 1
