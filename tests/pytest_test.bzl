"""Macro for non-Django tests (no DB, no Django settings).

Use pytest_py_test() for pure-python tests: static source guards, pure helpers,
anything that doesn't touch the ORM. Django DB tests use django_py_test() from
django_test.bzl instead.

WHY THIS EXISTS: a raw `py_test` with the test file as its implicit main only
*imports* the module and exits 0 — pytest never runs, so `bazel test` reports
PASSED while executing zero assertions (false-green; see pytest_main.py). That
trap was fixed for Django tests by django_py_test on 2026-06-10, but raw py_test
targets bypassed the runner and silently reintroduced it. This macro wires the
same `pytest_main.py` entrypoint without pulling in the Django deps.
"""

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

def pytest_py_test(
        name,
        srcs,
        deps = None,
        data = None,
        size = "small",
        env = None,
        **kwargs):
    """py_test for non-Django tests, run under pytest via the shared entrypoint."""
    py_test(
        name = name,
        size = size,
        srcs = list(srcs) + ["pytest_main.py"],
        main = "pytest_main.py",
        # Pass each real test src as a runtime arg so pytest collects + runs it.
        args = ["$(rootpath %s)" % s for s in srcs],
        data = data,
        deps = list(deps or []) + [requirement("pytest")],
        env = env,
        python_version = "PY3",
        srcs_version = "PY3",
        **kwargs
    )
