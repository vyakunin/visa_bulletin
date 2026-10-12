"""Only the web server runs under the 45 s per-query limit."""

from tests.django_setup import setup_django_for_tests

setup_django_for_tests()

import pytest  # noqa: E402
from django.db import connection  # noqa: E402

from django_config.settings import statement_timeout_option  # noqa: E402


def test_gunicorn_gets_the_45s_limit():
    argv = ["/usr/local/bin/gunicorn", "--preload", "django_config.wsgi:application"]
    assert statement_timeout_option(argv) == "-c statement_timeout=45000"


@pytest.mark.parametrize(
    "argv",
    [
        ["manage.py", "migrate", "--noinput"],
        ["/app/scripts/salary/cluster_job_titles.py"],
        ["/opt/gunicorn/warm_cache.py"],
        [],
    ],
)
def test_everything_else_runs_without_a_limit(argv):
    assert statement_timeout_option(argv) == "-c statement_timeout=0"


@pytest.mark.django_db
def test_a_script_connection_has_no_limit():
    with connection.cursor() as cursor:
        cursor.execute("SHOW statement_timeout")
        assert cursor.fetchone()[0] == "0"
