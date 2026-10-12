"""cluster_job_titles runs without the application statement timeout."""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import sys  # noqa: E402

import pytest  # noqa: E402
from django.db import connection  # noqa: E402

from scripts.salary import cluster_job_titles  # noqa: E402


def _statement_timeout() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_clustering_runs_without_the_application_statement_timeout(monkeypatch):
    with connection.cursor() as cursor:
        cursor.execute("SET statement_timeout = 45000")
    seen: list[str] = []
    monkeypatch.setattr(
        cluster_job_titles, "cluster_job_titles", lambda dry_run: seen.append(_statement_timeout())
    )
    monkeypatch.setattr(sys, "argv", ["cluster_job_titles"])

    cluster_job_titles.main()

    assert seen == ["0"]
