"""Unit tests for tools/bazel_dep_check.py, the undeclared-Bazel-dep checker.

These build synthetic BUILD/source trees in a tmpdir rather than scanning the
real repo. That is deliberate: Bazel's glob() cannot cross package boundaries, so
a sandboxed test can never receive all 45 BUILD files as data. The repo-wide scan
therefore runs from the pre-commit hook (like ruff); this file pins the parsing
and closure logic that scan depends on.
"""

import os
import sys
import tempfile
import textwrap
import unittest

# Under Bazel the workspace root is already on sys.path; this keeps a bare
# `python3 tests/test_bazel_dep_check.py` working too.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.bazel_dep_check import DepGraph  # noqa: E402


class _Tree:
    """Builds a throwaway workspace so each case states its own BUILD graph."""

    def __init__(self):
        self.dir = tempfile.TemporaryDirectory()
        self.root = self.dir.name

    def write(self, relpath, content):
        full = os.path.join(self.root, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as fh:
            fh.write(textwrap.dedent(content))

    def graph(self):
        return DepGraph(self.root)

    def cleanup(self):
        self.dir.cleanup()


class TestDepCheck(unittest.TestCase):
    def setUp(self):
        self.tree = _Tree()
        self.addCleanup(self.tree.cleanup)

    def test_flags_undeclared_import(self):
        """The bug this whole check exists for: import present, dep absent."""
        self.tree.write("models/enums/visa_category.py", "CATEGORY = 1\n")
        self.tree.write("models/enums/BUILD", """
            py_library(name = "visa_category", srcs = ["visa_category.py"])
        """)
        self.tree.write("models/visa_cutoff_date.py",
                        "from models.enums.visa_category import CATEGORY\n")
        self.tree.write("models/BUILD", """
            py_library(name = "visa_cutoff_date", srcs = ["visa_cutoff_date.py"])
        """)

        violations = self.tree.graph().violations()
        self.assertEqual(len(violations), 1, violations)
        label, _src, module, provider = violations[0]
        self.assertEqual(label, "//models:visa_cutoff_date")
        self.assertEqual(module, "models.enums.visa_category")
        self.assertEqual(provider, "//models/enums:visa_category")

    def test_declared_import_is_clean(self):
        self.tree.write("models/enums/visa_category.py", "CATEGORY = 1\n")
        self.tree.write("models/enums/BUILD", """
            py_library(name = "visa_category", srcs = ["visa_category.py"])
        """)
        self.tree.write("models/visa_cutoff_date.py",
                        "from models.enums.visa_category import CATEGORY\n")
        self.tree.write("models/BUILD", """
            py_library(
                name = "visa_cutoff_date",
                srcs = ["visa_cutoff_date.py"],
                deps = ["//models/enums:visa_category"],
            )
        """)
        self.assertEqual(self.tree.graph().violations(), [])

    def test_transitive_dep_satisfies(self):
        """A dep reached through an intermediate target counts as declared."""
        self.tree.write("models/a.py", "A = 1\n")
        self.tree.write("models/b.py", "from models.a import A\n")
        self.tree.write("models/c.py", "from models.a import A\n")
        self.tree.write("models/BUILD", """
            py_library(name = "a", srcs = ["a.py"])
            py_library(name = "b", srcs = ["b.py"], deps = [":a"])
            py_library(name = "c", srcs = ["c.py"], deps = [":b"])
        """)
        self.assertEqual(self.tree.graph().violations(), [])

    def test_lazy_in_function_import_is_flagged(self):
        """The case a runtime import test would miss entirely."""
        self.tree.write("lib/utils/http_utils.py", "def download(): pass\n")
        self.tree.write("lib/utils/BUILD", """
            py_library(name = "http_utils", srcs = ["http_utils.py"])
        """)
        self.tree.write("lib/ingest/base.py", """
            def fetch():
                from lib.utils.http_utils import download
                return download()
        """)
        self.tree.write("lib/ingest/BUILD", """
            py_library(name = "base", srcs = ["base.py"])
        """)
        violations = self.tree.graph().violations()
        self.assertEqual([v[2] for v in violations], ["lib.utils.http_utils"])

    def test_type_checking_import_is_not_flagged(self):
        """`if TYPE_CHECKING:` imports never execute, so they need no dep."""
        self.tree.write("models/salary.py", "class Employer: pass\n")
        self.tree.write("models/BUILD", """
            py_library(name = "salary", srcs = ["salary.py"])
        """)
        self.tree.write("lib/utils/db_utils.py", """
            from typing import TYPE_CHECKING
            if TYPE_CHECKING:
                from models.salary import Employer
        """)
        self.tree.write("lib/utils/BUILD", """
            py_library(name = "db_utils", srcs = ["db_utils.py"])
        """)
        self.assertEqual(self.tree.graph().violations(), [])

    def test_any_owner_of_a_shared_source_satisfies(self):
        """A py_binary and its _lib share srcs; depending on either is enough."""
        self.tree.write("scripts/publish.py", "def publish(): pass\n")
        self.tree.write("scripts/BUILD", """
            py_binary(name = "publish", srcs = ["publish.py"])
            py_library(name = "publish_lib", srcs = ["publish.py"])
        """)
        self.tree.write("scripts/cron/refresh.py", "from scripts.publish import publish\n")
        self.tree.write("scripts/cron/BUILD", """
            py_library(
                name = "refresh",
                srcs = ["refresh.py"],
                deps = ["//scripts:publish_lib"],
            )
        """)
        self.assertEqual(
            self.tree.graph().violations(), [],
            "depending on the _lib must satisfy the import even though the "
            "py_binary also owns that source",
        )

    def test_shared_source_suggests_the_lib_target(self):
        """When nothing is declared, suggest the importable _lib, not the binary."""
        self.tree.write("scripts/publish.py", "def publish(): pass\n")
        self.tree.write("scripts/BUILD", """
            py_binary(name = "publish", srcs = ["publish.py"])
            py_library(name = "publish_lib", srcs = ["publish.py"])
        """)
        self.tree.write("scripts/cron/refresh.py", "from scripts.publish import publish\n")
        self.tree.write("scripts/cron/BUILD", """
            py_library(name = "refresh", srcs = ["refresh.py"])
        """)
        violations = self.tree.graph().violations()
        self.assertEqual(len(violations), 1, violations)
        self.assertEqual(violations[0][3], "//scripts:publish_lib")

    def test_third_party_imports_are_ignored(self):
        """Only first-party packages are modelled; requirement() is not parsed."""
        self.tree.write("lib/x.py", "import django\nimport numpy\n")
        self.tree.write("lib/BUILD", """
            py_library(name = "x", srcs = ["x.py"])
        """)
        self.assertEqual(self.tree.graph().violations(), [])

    def test_macro_injected_deps_are_modelled(self):
        """django_py_test injects deps the BUILD file never spells out."""
        self.tree.write("webapp/apps.py", "class Config: pass\n")
        self.tree.write("webapp/BUILD", """
            py_library(name = "apps", srcs = ["apps.py"])
        """)
        self.tree.write("tests/test_thing.py", "from webapp.apps import Config\n")
        self.tree.write("tests/BUILD", """
            django_py_test(name = "test_thing", srcs = ["test_thing.py"])
        """)
        self.assertEqual(
            self.tree.graph().violations(), [],
            "//webapp:apps is injected by the django_py_test macro, so importing "
            "it from a django test is already declared",
        )

    def test_same_target_sources_do_not_need_deps(self):
        """Two srcs in one target can import each other freely."""
        self.tree.write("lib/a.py", "A = 1\n")
        self.tree.write("lib/b.py", "from lib.a import A\n")
        self.tree.write("lib/BUILD", """
            py_library(name = "both", srcs = ["a.py", "b.py"])
        """)
        self.assertEqual(self.tree.graph().violations(), [])


if __name__ == "__main__":
    unittest.main()
