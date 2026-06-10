"""
Shared Django setup for tests.

Tests use PostgreSQL only. We connect to DB_NAME (default postgres) only to
create a separate database test_<DB_NAME> (e.g. test_postgres). All test data
lives in test_postgres; the real postgres DB is never written to.

CREATEDB grant: If PG_SUPERUSER_USER and PG_SUPERUSER_PASSWORD are set (e.g. in
.env), the test runner calls ensure_test_db.grant_createdb() on first use.
"""

import os
from pathlib import Path

import django
from django.apps import apps

_test_db_created = False


def _load_env_file():
    """Load workspace .env into os.environ (setdefault only) so tests get DB_* and PG_SUPERUSER_*."""
    workspace = Path(os.environ.get("BUILD_WORKSPACE_DIRECTORY", os.getcwd()))
    env_file = workspace / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def setup_django_for_tests():
    """Configure Django for the test environment and ensure a migrated test DB.

    Two test-runner regimes coexist in this suite, and the test-DB owner differs:

    * Targets that depend on **pytest-django**: pytest-django loads first and
      installs a DB-access *blocker*, then OWNS the test DB via its
      django_db_setup fixture (Django setup_databases()). If we also tried to
      create the DB here at import time, the blocker raises "Database access not
      allowed" and the *entire conftest import fails* — collection dies and every
      test in the target errors. This was the suite's "DB-collision" failure mode,
      hidden until the false-green fix made tests actually run. So when
      pytest-django is present we must NOT touch the DB here; we only point it at a
      per-process test DB name (parallel bazel targets share one postgres server).

    * Targets WITHOUT pytest-django (plain `unittest.TestCase`, run by pytest with
      no DB plugin): nobody else creates the test DB, so we create+migrate it here
      at import. There is no blocker in this regime, so it is safe.

    Detection: pytest-django, when active, is imported before conftest, so it is in
    sys.modules. That is the switch between the two regimes.
    """
    global _test_db_created
    _load_env_file()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
    # Connect to postgres only to create test_postgres; we never write to postgres.
    os.environ.setdefault("DB_NAME", "postgres")
    # Default DB_USER to current user (Homebrew/macOS often creates this role); CI sets postgres.
    if "DB_USER" not in os.environ:
        os.environ.setdefault("DB_USER", os.environ.get("USER", "postgres"))
    os.environ.setdefault("DB_PASSWORD", "")
    os.environ.setdefault("DB_HOST", "localhost")
    os.environ.setdefault("DB_PORT", "5432")
    os.environ["RUNNING_TESTS"] = "1"

    if not apps.ready:
        django.setup()

    if _test_db_created or os.environ.get("RUNNING_TESTS") != "1":
        return
    try:
        import psycopg2  # noqa: F401
    except ImportError:
        # No DB driver — pure-unit run, nothing to create.
        _test_db_created = True
        return

    from tests.ensure_test_db import grant_createdb

    grant_createdb()

    # Bazel runs each test target in its own process against one shared postgres
    # server; a per-pid test DB name avoids "database already exists" collisions
    # between parallel targets. Both regimes use the same name: we set TEST.NAME so
    # pytest-django's setup_databases() honors it, and the legacy path below reads
    # it back.
    import sys

    from django.conf import settings

    db = settings.DATABASES["default"]
    base = db.get("NAME") or "postgres"
    db.setdefault("TEST", {})
    test_name = db["TEST"].get("NAME") or f"test_{base}_{os.getpid()}"
    db["TEST"]["NAME"] = test_name

    if "pytest_django" in sys.modules:
        # pytest-django owns DB creation (its blocker is active; creating here would
        # raise "Database access not allowed" and fail conftest import). It will
        # create+migrate test_name via setup_databases() when a DB-using test runs.
        _test_db_created = True
        return

    # No pytest-django in this target: create + migrate the test DB ourselves.
    from django.core.management import call_command
    from django.db import connection

    connection.creation.create_test_db(verbosity=0, autoclobber=True)
    # Apply migrations so test DB has all tables (salary_employer, etc.).
    call_command("migrate", verbosity=0)
    _test_db_created = True
