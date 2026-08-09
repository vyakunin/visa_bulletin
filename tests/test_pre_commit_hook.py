"""Pin the pre-commit hook's two silent-failure classes.

The hook has now produced three incidents of one defect: it decided what a
non-zero `bazel test` exit MEANT by grepping the output for a single word, so
every shape that word did not cover was reclassified as whichever branch caught
it last. It reported an analysis error as "0 segfaults, all assertions passed"
and committed clean (main red and untested for three days, 2026-07-30), and it
reported 13 timeouts alongside 112 passes as "No test ran" (2026-08-06). A
fourth face of the same bug is a matter of time, so the classifier gets a test
rather than another branch.

Separately, the hook selected work with the git pathspec `BUILD`, which matches
only a ROOT-level file of that name — so a commit touching `tests/BUILD` or any
other nested one ran neither the dep check nor the tests and printed "No staged
Python/BUILD files — skipping tests".

These run the REAL hook script against a throwaway git repo with a stub `bazel`
on PATH, so they test the shipped artifact, not a copy of its logic.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

HOOK = Path(__file__).resolve().parent.parent / "tools" / "hooks" / "pre-commit"

# A bazel stub that prints whatever the case needs and exits how the case needs.
STUB = """#!/bin/bash
if [ "$1" = "run" ]; then exit 0; fi        # ruff
cat <<'BAZEL_OUT'
{output}
BAZEL_OUT
exit {code}
"""

PASS_LINE = "//tests:test_a                     PASSED in 1.2s"


class PreCommitHookTest(unittest.TestCase):
    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="vb_hook_"))
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.bin = self.dir / "stubbin"
        self.bin.mkdir()
        def run(*a: str) -> None:
            subprocess.run(a, cwd=self.dir, check=True, capture_output=True)

        run("git", "init", "-q")
        run("git", "config", "user.email", "t@t")
        run("git", "config", "user.name", "t")
        # The dep check is a separate concern here; make it a trivial pass.
        (self.dir / "tools").mkdir()
        (self.dir / "tools" / "bazel_dep_check.py").write_text("print('ok')\n")

    def _stub_bazel(self, output: str, code: int) -> None:
        p = self.bin / "bazel"
        p.write_text(STUB.format(output=output, code=code))
        p.chmod(0o755)

    def _stage(self, relpath: str, content: str = "x\n") -> None:
        f = self.dir / relpath
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
        subprocess.run(["git", "add", relpath], cwd=self.dir, check=True, capture_output=True)

    def _run_hook(self) -> subprocess.CompletedProcess:
        env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")
        return subprocess.run(
            ["bash", str(HOOK)], cwd=self.dir, env=env, capture_output=True, text=True
        )

    # --- the pathspec defect -------------------------------------------------

    def test_nested_build_file_is_not_skipped(self):
        """`BUILD` as a pathspec matched only the root one; nested were invisible."""
        self._stub_bazel(PASS_LINE, 0)
        self._stage("webapp/views/BUILD")
        r = self._run_hook()
        self.assertNotIn("skipping tests", r.stdout)
        self.assertIn("Checking Bazel dep declarations", r.stdout)
        self.assertIn("Running all tests with Bazel", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_root_build_file_still_selected(self):
        self._stub_bazel(PASS_LINE, 0)
        self._stage("BUILD")
        r = self._run_hook()
        self.assertNotIn("skipping tests", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)

    def test_unrelated_file_still_skips(self):
        """A docs-only commit must stay cheap — the gate is for code."""
        self._stub_bazel(PASS_LINE, 0)
        self._stage("README.md")
        r = self._run_hook()
        self.assertIn("skipping tests", r.stdout)
        self.assertEqual(r.returncode, 0, r.stdout)

    # --- the classifier ------------------------------------------------------

    def test_analysis_error_fails_closed(self):
        """No per-target status line at all. Must never read as a pass."""
        self._stub_bazel(
            "ERROR: no such target '//tests:nope': target 'nope' not declared", 1
        )
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("analysis/build error", r.stdout)
        self.assertIn("No test ran", r.stdout)

    def test_timeout_is_named_and_fails(self):
        """Reported as 'No test ran' before, over a run with 112 passes."""
        self._stub_bazel(
            f"{PASS_LINE}\n//tests:test_slow                  TIMEOUT in 300.1s", 3
        )
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("TIMED OUT", r.stdout)
        self.assertNotIn("No test ran", r.stdout)

    def test_real_failure_fails(self):
        self._stub_bazel(
            f"{PASS_LINE}\n//tests:test_b                     FAILED in 2.0s", 3
        )
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("FAILED", r.stdout)

    def test_no_status_fails(self):
        """A cut-short run: targets reported nothing. Previously unattributed."""
        self._stub_bazel(
            f"{PASS_LINE}\n//tests:test_c                     NO STATUS", 3
        )
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("NO STATUS", r.stdout)

    def test_segfault_alongside_passes_is_tolerated(self):
        """The one documented carve-out — and only when tests demonstrably ran."""
        self._stub_bazel(
            f"{PASS_LINE}\n//tests:test_d                     FAILED TO BUILD", 1
        )
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("shutdown", r.stdout)

    def test_segfault_with_no_passes_fails_closed(self):
        """Nothing passed, so this is not 'just segfaults' — it must not pass."""
        self._stub_bazel("//tests:test_d                     FAILED TO BUILD", 1)
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)

    def test_unknown_shape_fails_closed(self):
        """The point of the rewrite: an unanticipated shape stops the commit."""
        self._stub_bazel(f"{PASS_LINE}\n//tests:test_e   SOMETHING_NEW in 1s", 7)
        self._stage("tests/BUILD")
        r = self._run_hook()
        self.assertEqual(r.returncode, 1, r.stdout)
        self.assertIn("cannot attribute", r.stdout)


if __name__ == "__main__":
    unittest.main()
