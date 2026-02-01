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
    workspace = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', os.getcwd()))
    env_file = workspace / '.env'
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def setup_django_for_tests():
    """Configure Django for test environment and ensure test DB exists with migrations."""
    global _test_db_created
    _load_env_file()
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
    # Connect to postgres only to create test_postgres; we never write to postgres.
    os.environ.setdefault('DB_NAME', 'postgres')
    # Default DB_USER to current user (Homebrew/macOS often creates this role); CI sets postgres.
    if 'DB_USER' not in os.environ:
        os.environ.setdefault('DB_USER', os.environ.get('USER', 'postgres'))
    os.environ.setdefault('DB_PASSWORD', '')
    os.environ.setdefault('DB_HOST', 'localhost')
    os.environ.setdefault('DB_PORT', '5432')
    os.environ['RUNNING_TESTS'] = '1'

    if not apps.ready:
        django.setup()

    # When run via unittest (not manage.py test), the test DB is never created.
    # Optionally ensure DB_USER has CREATEDB, then create test_postgres and run migrations.
    # Only run if this test uses the DB (psycopg2 loadable); skip if test has no DB deps.
    if not _test_db_created and os.environ.get('RUNNING_TESTS') == '1':
        try:
            import psycopg2  # noqa: F401
        except ImportError:
            _test_db_created = True
        else:
            from tests.ensure_test_db import grant_createdb
            grant_createdb()
            from django.db import connection
            from django.core.management import call_command
            # Bazel runs tests in parallel; each process needs its own DB to avoid "already exists".
            base_name = connection.settings_dict['NAME']
            if base_name == 'postgres':
                connection.settings_dict['NAME'] = f'postgres_{os.getpid()}'
            connection.creation.create_test_db(verbosity=0, autoclobber=True)
            # Apply migrations so test DB has all tables (salary_employer, etc.).
            call_command('migrate', verbosity=0)
            _test_db_created = True











