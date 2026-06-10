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

if __name__ == "__main__":
    # argv[1:] = the test file paths bazel substituted from $(rootpath ...).
    # no:cacheprovider — the sandbox is read-only; -v for per-test visibility in
    # the bazel test log (so a future false-green is obvious: "Ran 0 tests").
    targets = sys.argv[1:] or ["."]
    raise SystemExit(pytest.main([*targets, "-v", "-p", "no:cacheprovider"]))
