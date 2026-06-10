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
        deps = None,
        data = None,
        size = "small",
        env = None,
        **kwargs):
    """py_test for Django DB tests: adds django_setup, psycopg2, migrations, env.

    Runs the test srcs under pytest via the shared `pytest_main.py` entrypoint —
    a plain py_test with the test file as `main` only *imports* the module and
    exits 0 (no runner → false-green; see pytest_main.py). pytest executes both
    unittest.TestCase subclasses and bare `test_*` functions.
    """
    all_deps = list(deps or []) + [
        ":django_setup",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("pytest"),
    ]
    all_data = list(data or []) + ["//models:migrations"]
    all_env = dict(env or {})
    all_env.setdefault("DJANGO_SETTINGS_MODULE", "django_config.settings")
    all_env.setdefault("RUNNING_TESTS", "1")
    all_env.setdefault("DB_NAME", "postgres")
    # pytest_main.py is the entrypoint; pass each real test src as a runtime arg
    # so pytest collects + runs it. $(rootpath) resolves to the runfiles path.
    py_test(
        name = name,
        size = size,
        srcs = list(srcs) + ["pytest_main.py"],
        main = "pytest_main.py",
        args = ["$(rootpath %s)" % s for s in srcs],
        data = all_data,
        deps = all_deps,
        env = all_env,
        python_version = "PY3",
        srcs_version = "PY3",
        **kwargs
    )
