"""Shared bazel `py_test` entrypoint — runs pytest over the test file(s).

WHY THIS EXISTS: a bazel `py_test` runs its `main` script as `__main__` and
exits with that script's exit code. Our test modules only *define* TestCase
classes / `test_*` functions — without a runner they were imported and the
process exited 0, so `bazel test` reported PASSED while executing zero
assertions (the suite was false-green until 2026-06-10). This shim is wired as
the `main` of every test target by the `django_py_test` macro; the BUILD passes
each real test src as an argument (`args = ["$(rootpath test_x.py)", ...]`), and
pytest collects + runs it. pytest (not `unittest.main()`) is the universal
runner because it executes BOTH `unittest.TestCase` subclasses AND bare
module-level `test_*` functions; `unittest.main()` silently skips the latter.
"""

import sys

import pytest


class _TemplateInstrumentationPlugin:
    """Keep Django's template-render instrumentation active for view tests.

    `setup_test_environment()` patches `Template._render` to emit the
    `template_rendered` signal — the mechanism that populates `response.context`
    and `response.templates` on the Django test client. For targets that depend
    on `:conftest_lib`, `pytest_django` is loaded and its session-scoped
    `django_test_environment` fixture installs this correctly — we MUST NOT touch
    it there (calling `setup_test_environment()` a second time raises
    `RuntimeError: setup_test_environment() was already called`, erroring every
    test in the target).

    But the pure Django view tests (`test_employer_profile_view`,
    `test_prediction_category_landing`, …) deliberately do NOT depend on
    `:conftest_lib`, so `pytest_django` never loads and nothing instruments the
    template renderer — every `response.context["..."]` read returns `None` →
    `TypeError: 'NoneType' object is not subscriptable`. For those targets this
    plugin (registered explicitly via `pytest.main(plugins=[...])`, so its hooks
    fire) installs the instrumentation once.

    Discriminator: `"pytest_django" in sys.modules` — the same signal
    `tests/django_setup.py` uses. It is loaded iff the target depends on
    `:conftest_lib` (whose `conftest.py` sets `pytest_plugins=["pytest_django"]`),
    which is exactly the runfiles split that decides who manages the environment.
    """

    def pytest_runtest_setup(self, item):
        if "pytest_django" in sys.modules:
            return  # pytest-django owns the test environment for this target.
        try:
            from django.template.base import Template
            from django.test.utils import setup_test_environment
        except Exception:
            return  # Django not configured for this target — nothing to do.
        if getattr(Template._render, "__qualname__", "") == "instrumented_test_render":
            return  # already instrumented — leave it alone.
        setup_test_environment()


if __name__ == "__main__":
    # argv[1:] = the test file paths bazel substituted from $(rootpath ...).
    # no:cacheprovider — the sandbox is read-only; -v for per-test visibility in
    # the bazel test log (so a future false-green is obvious: "Ran 0 tests").
    targets = sys.argv[1:] or ["."]
    raise SystemExit(
        pytest.main(
            [*targets, "-v", "-p", "no:cacheprovider"],
            plugins=[_TemplateInstrumentationPlugin()],
        )
    )
