"""Phase 2 of cluster_job_titles logs progress by count, and by time when a stretch of titles is slow."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

from scripts.salary.cluster_job_titles import (  # noqa: E402
    PHASE2_HEARTBEAT_S,
    PHASE2_PROGRESS_EVERY,
    phase2_progress_due,
)


def test_progress_logs_at_every_count_boundary_without_elapsed_time():
    assert phase2_progress_due(PHASE2_PROGRESS_EVERY, now=0.0, last_logged_at=0.0)


def test_progress_logs_a_heartbeat_when_a_slow_stretch_reaches_the_interval():
    assert phase2_progress_due(3, now=PHASE2_HEARTBEAT_S, last_logged_at=0.0)


def test_progress_stays_quiet_mid_stretch_before_the_interval():
    assert not phase2_progress_due(3, now=PHASE2_HEARTBEAT_S - 1, last_logged_at=0.0)
