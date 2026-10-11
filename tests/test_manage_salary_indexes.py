"""manage_salary_indexes builds indexes without the application statement timeout."""

# Use shared Django setup
from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import sys  # noqa: E402

import pytest  # noqa: E402
import yaml  # noqa: E402
from django.db import connection  # noqa: E402

from scripts.salary import manage_salary_indexes  # noqa: E402


def _statement_timeout() -> str:
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        return cursor.fetchone()[0]


@pytest.mark.django_db(transaction=True)
def test_recreate_runs_without_the_application_statement_timeout(tmp_path, monkeypatch):
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tablename, indexname, indexdef FROM pg_indexes"
            " WHERE tablename = 'salary_record' AND indexdef NOT LIKE 'CREATE UNIQUE%' LIMIT 1"
        )
        table, name, indexdef = cursor.fetchone()
        cursor.execute("SET statement_timeout = 45000")
    snapshot = tmp_path / "salary_indexes.yaml"
    snapshot.write_text(
        yaml.safe_dump(
            {"indexes": [{"schema": "public", "table": table, "name": name, "indexdef": indexdef}]}
        )
    )
    monkeypatch.setattr(
        sys, "argv", ["manage_salary_indexes", "--recreate", "--force", "--snapshot", str(snapshot)]
    )

    manage_salary_indexes.main()

    assert _statement_timeout() == "0"
