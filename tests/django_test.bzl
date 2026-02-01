"""
Macro for Django DB-using tests.

Use django_py_test() for tests that need PostgreSQL: they get common deps
(django_setup, psycopg2_binary, models:migrations) and env (RUNNING_TESTS, DB_NAME).
No manual setup: set PG_SUPERUSER_USER and PG_SUPERUSER_PASSWORD when running
tests; django_setup calls ensure_test_db.grant_createdb() on first use.
"""

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

def django_py_test(
        name,
        srcs,
        deps,
        data = None,
        size = "small",
        main = None,
        env = None,
        **kwargs):
    """py_test for Django DB tests: adds django_setup, psycopg2, migrations, env."""
    all_deps = list(deps) + [
        ":django_setup",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ]
    all_data = list(data or []) + ["//models:migrations"]
    all_env = dict(env or {})
    all_env.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
    all_env.setdefault("RUNNING_TESTS", "1")
    all_env.setdefault("DB_NAME", "postgres")
    py_test(
        name = name,
        size = size,
        srcs = srcs,
        main = main,
        data = all_data,
        deps = all_deps,
        env = all_env,
        python_version = "PY3",
        srcs_version = "PY3",
        **kwargs
    )
