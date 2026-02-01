# Tests

Tests use **PostgreSQL only** (no SQLite). We **always** use a dedicated test database: we connect to the server using `DB_NAME` (default `postgres`) only to **create** a separate database `test_<DB_NAME>` (e.g. `test_postgres`). All test data lives in `test_postgres`; the real `postgres` (or your app DB) is **never** written to.

## Local

1. **PostgreSQL** must be running (same as for dev).
2. **DB user must have CREATEDB** so we can create `test_postgres`:
   - **Default:** With no `.env`, tests use `DB_USER=$USER` (current OS user). On macOS/Homebrew PostgreSQL that role often has CREATEDB.
   - **With `.env`:** Tests load workspace `.env`; set `PG_SUPERUSER_USER` and `PG_SUPERUSER_PASSWORD` to have the runner grant CREATEDB to `DB_USER` on first use.
3. Optional: set `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` in `.env`. Do **not** set `DB_NAME` to a production database when running tests.

```bash
bazel test //tests/...
```

## CI

`.github/workflows/test.yml` runs tests with a PostgreSQL 15 service. It sets `DB_NAME=postgres`, `DB_USER=postgres`, `DB_PASSWORD=postgres`. The `postgres` user has CREATEDB, so we create `test_postgres` and run migrations there. The real `postgres` database is never written to; only `test_postgres` is used for test data.

## Staging

Run the full test suite on the staging VM (uses `.env` there; DB user must have CREATEDB or use `postgres` for tests):

```bash
./scripts/run_tests_on_staging.sh
# Or with a specific SSH alias:
./scripts/run_tests_on_staging.sh staging_2Gb_vm
```

Tests on staging create and use `test_postgres` on the staging DB server; they do not touch the real app database.

## Macro for DB tests

DB-using tests can use the `django_py_test()` macro in `tests/django_test.bzl` so they get common deps (django_setup, psycopg2_binary, models:migrations) and env (RUNNING_TESTS, DB_NAME). Example: `test_job_title_profile_view` uses it. New DB tests should use this macro.

## Safeguards

- **Test DB only:** We always use a database whose name starts with `test_` for test runs. Your normal DB (e.g. `visa_bulletin_dev`) is not used. Under Bazel (parallel tests), each process uses `test_postgres_<pid>` so processes don't conflict.
- **Connection target:** `DB_NAME=postgres` means we connect to the server and create `test_postgres`; we never write tables into the real `postgres` database.
- **Connection pooling:** Disabled during tests (`CONN_MAX_AGE=0`) when `RUNNING_TESTS=1` is set by `setup_django_for_tests()`.
