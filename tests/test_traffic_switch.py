# tests/test_traffic_switch.py
"""Unit tests for scripts/cron/refresh traffic_switch: attach_staging_static_ip_to_old_prod."""

from unittest.mock import patch

from scripts.cron.refresh.traffic_switch import (
    _aws_region,
    attach_staging_static_ip_to_old_prod,
    switch_traffic_static_ip,
)


def test_aws_region_uses_refresh_then_default() -> None:
    with patch.dict("os.environ", {}, clear=False):
        # REFRESH_AWS_REGION and AWS_DEFAULT_REGION not set -> us-east-1
        assert _aws_region() == "us-east-1"
    with patch.dict("os.environ", {"REFRESH_AWS_REGION": "eu-west-1"}, clear=False):
        assert _aws_region() == "eu-west-1"
    with patch.dict("os.environ", {"AWS_DEFAULT_REGION": "ap-south-1"}, clear=False):
        assert _aws_region() == "ap-south-1"
    with patch.dict(
        "os.environ",
        {"REFRESH_AWS_REGION": "eu-west-1", "AWS_DEFAULT_REGION": "ap-south-1"},
        clear=False,
    ):
        assert _aws_region() == "eu-west-1"


def test_attach_staging_static_ip_to_old_prod_success() -> None:
    """When detach and attach succeed, returns True."""
    with patch("scripts.cron.refresh.traffic_switch.subprocess.run") as m_run:
        m_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        result = attach_staging_static_ip_to_old_prod(
            "VisaBulletinStaging-ip", "VisaBulletin2GB"
        )
    assert result is True
    assert m_run.call_count >= 2  # detach + at least one attach
    detach_call = m_run.call_args_list[0]
    assert "detach-static-ip" in detach_call[0][0]
    assert "VisaBulletinStaging-ip" in detach_call[0][0]
    attach_call = m_run.call_args_list[1]
    assert "attach-static-ip" in attach_call[0][0]
    assert "VisaBulletinStaging-ip" in attach_call[0][0]
    assert "VisaBulletin2GB" in attach_call[0][0]


def test_attach_staging_static_ip_to_old_prod_detach_not_attached_then_attach_success() -> None:
    """When detach fails with 'not attached' we still attach and succeed."""
    with patch("scripts.cron.refresh.traffic_switch.subprocess.run") as m_run:
        detach_fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "is not attached"})()
        attach_ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        m_run.side_effect = [detach_fail, attach_ok]
        result = attach_staging_static_ip_to_old_prod(
            "Staging-ip", "VisaBulletin2GB", max_attach_retries=1
        )
    assert result is True
    assert m_run.call_count == 2


def test_attach_staging_static_ip_to_old_prod_attach_fails_after_retries() -> None:
    """When attach fails all retries, returns False."""
    with patch("scripts.cron.refresh.traffic_switch.subprocess.run") as m_run:
        detach_ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        attach_fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "InvalidParameter"})()
        m_run.side_effect = [detach_ok, attach_fail, attach_fail, attach_fail]
        result = attach_staging_static_ip_to_old_prod(
            "Staging-ip", "VisaBulletin2GB", max_attach_retries=3
        )
    assert result is False
    assert m_run.call_count == 4  # 1 detach + 3 attach


def test_attach_staging_static_ip_to_old_prod_attach_succeeds_on_second_retry() -> None:
    """When attach fails once then succeeds, returns True."""
    with patch("scripts.cron.refresh.traffic_switch.subprocess.run") as m_run:
        with patch("scripts.cron.refresh.traffic_switch.time.sleep"):
            detach_ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            attach_fail = type("R", (), {"returncode": 1, "stdout": "", "stderr": "Throttling"})()
            attach_ok = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
            m_run.side_effect = [detach_ok, attach_fail, attach_ok]
            result = attach_staging_static_ip_to_old_prod(
                "Staging-ip", "VisaBulletin2GB", max_attach_retries=3
            )
    assert result is True
    assert m_run.call_count == 3


def test_switch_traffic_static_ip_success() -> None:
    """switch_traffic_static_ip detaches then attaches prod IP."""
    with patch("scripts.cron.refresh.traffic_switch.subprocess.run") as m_run:
        m_run.return_value = type("R", (), {"returncode": 0, "stdout": "", "stderr": ""})()
        result = switch_traffic_static_ip("VisaBulletin-ip", "VisaBulletinStaging")
    assert result is True
    # 3 calls: an idempotency pre-check (get-static-ip), then detach, then attach.
    assert m_run.call_count == 3
    assert "get-static-ip" in m_run.call_args_list[0][0][0]
    assert "detach-static-ip" in m_run.call_args_list[1][0][0]
    assert "attach-static-ip" in m_run.call_args_list[2][0][0]
    assert "VisaBulletinStaging" in m_run.call_args_list[2][0][0]
