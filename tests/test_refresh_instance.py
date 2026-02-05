# tests/test_refresh_instance.py
"""Unit tests for scripts/cron/refresh instance: resolve_active_inactive_from_env, is_this_host_active."""

import os

import pytest

from scripts.cron.refresh.instance import (
    InstanceInfo,
    is_this_host_active,
    resolve_active_inactive_from_env,
)


def test_resolve_active_inactive_from_env_empty() -> None:
    for key in (
        "REFRESH_ACTIVE_INSTANCE_NAME",
        "REFRESH_ACTIVE_INSTANCE_IP",
        "REFRESH_INACTIVE_INSTANCE_NAME",
        "REFRESH_INACTIVE_INSTANCE_IP",
    ):
        os.environ.pop(key, None)
    active, inactive = resolve_active_inactive_from_env()
    assert active is None
    assert inactive is None


def test_resolve_active_inactive_from_env_partial() -> None:
    os.environ["REFRESH_ACTIVE_INSTANCE_NAME"] = "Prod"
    os.environ["REFRESH_ACTIVE_INSTANCE_IP"] = "1.2.3.4"
    os.environ.pop("REFRESH_INACTIVE_INSTANCE_NAME", None)
    os.environ.pop("REFRESH_INACTIVE_INSTANCE_IP", None)
    try:
        active, inactive = resolve_active_inactive_from_env()
        assert active is None
        assert inactive is None
    finally:
        os.environ.pop("REFRESH_ACTIVE_INSTANCE_NAME", None)
        os.environ.pop("REFRESH_ACTIVE_INSTANCE_IP", None)


def test_resolve_active_inactive_from_env_full() -> None:
    os.environ["REFRESH_ACTIVE_INSTANCE_NAME"] = "VisaBulletin2GB"
    os.environ["REFRESH_ACTIVE_INSTANCE_IP"] = "44.209.204.255"
    os.environ["REFRESH_INACTIVE_INSTANCE_NAME"] = "VisaBulletinStaging"
    os.environ["REFRESH_INACTIVE_INSTANCE_IP"] = "54.196.241.197"
    try:
        active, inactive = resolve_active_inactive_from_env()
        assert active is not None
        assert inactive is not None
        assert active.name == "VisaBulletin2GB"
        assert active.ip == "44.209.204.255"
        assert inactive.name == "VisaBulletinStaging"
        assert inactive.ip == "54.196.241.197"
    finally:
        for key in (
            "REFRESH_ACTIVE_INSTANCE_NAME",
            "REFRESH_ACTIVE_INSTANCE_IP",
            "REFRESH_INACTIVE_INSTANCE_NAME",
            "REFRESH_INACTIVE_INSTANCE_IP",
        ):
            os.environ.pop(key, None)


def test_is_this_host_active_no_active() -> None:
    assert is_this_host_active("me", None) is True


def test_is_this_host_active_match_name() -> None:
    active = InstanceInfo(name="Prod", ip="1.2.3.4", state="running")
    assert is_this_host_active("Prod", active) is True
    assert is_this_host_active("  Prod  ", active) is True


def test_is_this_host_active_match_ip() -> None:
    active = InstanceInfo(name="Prod", ip="1.2.3.4", state="running")
    assert is_this_host_active("1.2.3.4", active) is True


def test_is_this_host_active_no_match() -> None:
    active = InstanceInfo(name="Prod", ip="1.2.3.4", state="running")
    assert is_this_host_active("Staging", active) is False
    assert is_this_host_active("5.6.7.8", active) is False
