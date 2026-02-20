# tests/test_refresh_orchestrate.py
"""Unit tests for scripts/cron/refresh orchestrate: run_orchestrate with --no-traffic-switch (mocked)."""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

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
            patch(
                "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
            ) as m_resolve,
            patch(
                "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
            ) as m_is_active,
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
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch(
            "scripts.cron.refresh.orchestrate.instance.wait_instance_healthy"
        ) as m_healthy,
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
    m_switch.switch_traffic_static_ip.assert_not_called()


def test_run_orchestrate_missing_env_returns_1() -> None:
    """When REFRESH_ACTIVE_* or REFRESH_INACTIVE_* are missing, return 1."""
    config = load_config(Path("."))
    with patch(
        "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
    ) as m_resolve:
        m_resolve.return_value = (None, None)
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 1


def test_run_orchestrate_ssh_db_not_ready_returns_1() -> None:
    """When SSH/DB readiness check fails, return 1 without running pipeline."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch(
            "scripts.cron.refresh.orchestrate.services.wait_ssh_and_db_ready"
        ) as m_ssh_ready,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "running"
        m_ssh_ready.return_value = False
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 1
    m_pipeline.assert_not_called()


def test_run_orchestrate_instance_start_failure_returns_1() -> None:
    """When inactive instance fails to start, return 1."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="stopped")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch("scripts.cron.refresh.orchestrate.instance.start_instance") as m_start,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "stopped"
        m_start.return_value = False
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 1
    m_pipeline.assert_not_called()


def test_run_orchestrate_instance_not_running_after_start_returns_1() -> None:
    """When instance starts but never reaches running state, return 1."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="stopped")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch("scripts.cron.refresh.orchestrate.instance.start_instance") as m_start,
        patch(
            "scripts.cron.refresh.orchestrate.instance.wait_instance_running"
        ) as m_running,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "stopped"
        m_start.return_value = True
        m_running.return_value = False
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 1
    m_pipeline.assert_not_called()


def test_run_orchestrate_health_check_failure_is_nonfatal(tmp_path: Path) -> None:
    """Health check failure after starting services is non-fatal; pipeline still succeeds."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch(
            "scripts.cron.refresh.orchestrate.instance.wait_instance_healthy"
        ) as m_healthy,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
        patch("scripts.cron.refresh.orchestrate.services") as m_services,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "running"
        m_services.wait_ssh_and_db_ready.return_value = True
        m_healthy.return_value = False
        result = run_orchestrate(config, no_traffic_switch=True)
    assert result == 0
    m_pipeline.assert_called_once()


def test_run_orchestrate_from_step_traffic_switch_ssh_fail() -> None:
    """--from-step traffic_switch with SSH failure returns 1."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.services.wait_ssh_and_db_ready"
        ) as m_ssh,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_ssh.return_value = False
        result = run_orchestrate(config, from_step="traffic_switch")
    assert result == 1


def test_run_orchestrate_pipeline_failure_returns_nonzero() -> None:
    """When run_pipeline raises, orchestrate propagates the exception (no traffic switch)."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch(
            "scripts.cron.refresh.orchestrate.instance.wait_instance_healthy"
        ) as m_healthy,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
        patch("scripts.cron.refresh.orchestrate.traffic_switch") as m_switch,
        patch("scripts.cron.refresh.orchestrate.services") as m_services,
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "running"
        m_services.wait_ssh_and_db_ready.return_value = True
        m_healthy.return_value = True
        m_pipeline.side_effect = RuntimeError("Cluster job titles failed: OOM killed")

        with pytest.raises(RuntimeError, match="OOM killed"):
            run_orchestrate(config, no_traffic_switch=False)

        m_switch.switch_traffic_static_ip.assert_not_called()


def test_run_orchestrate_health_check_failure_still_allows_traffic_switch() -> None:
    """Health check failure is non-fatal even when traffic switch is enabled."""
    config = load_config(Path("."))
    active = InstanceInfo(name="Prod", ip="44.209.204.255", state="running")
    inactive = InstanceInfo(name="Staging", ip="54.196.241.197", state="running")

    with (
        patch(
            "scripts.cron.refresh.orchestrate.instance.resolve_active_inactive_from_env"
        ) as m_resolve,
        patch(
            "scripts.cron.refresh.orchestrate.instance.is_this_host_active"
        ) as m_is_active,
        patch(
            "scripts.cron.refresh.orchestrate.instance.get_instance_state"
        ) as m_state,
        patch(
            "scripts.cron.refresh.orchestrate.instance.wait_instance_healthy"
        ) as m_healthy,
        patch("scripts.cron.refresh.orchestrate.run_pipeline") as m_pipeline,
        patch("scripts.cron.refresh.orchestrate.traffic_switch") as m_switch,
        patch("scripts.cron.refresh.orchestrate.services") as m_services,
        patch("scripts.cron.refresh.orchestrate.RemoteRunner") as m_runner_cls,
        patch("scripts.cron.refresh.orchestrate.instance.stop_instance") as m_stop,
        patch.dict(
            os.environ,
            {
                "REFRESH_STATIC_IP_NAME": "VisaBulletin-ip",
                "REFRESH_SKIP_STAGING_IP_REASSIGN": "1",
            },
        ),
    ):
        m_resolve.return_value = (active, inactive)
        m_is_active.return_value = True
        m_state.return_value = "running"
        m_services.wait_ssh_and_db_ready.return_value = True
        m_healthy.return_value = False
        m_pipeline.return_value = 0
        m_switch.switch_traffic_static_ip.return_value = True
        m_stop.return_value = True

        result = run_orchestrate(config, no_traffic_switch=False, safety_interval_sec=0)

    assert result == 0
    m_pipeline.assert_called_once()
    m_switch.switch_traffic_static_ip.assert_called_once()
