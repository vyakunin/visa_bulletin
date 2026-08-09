"""Find py targets that import a first-party module absent from their Bazel dep closure.

Bazel does not enforce this for Python the way it does for Java: an undeclared
import keeps working as long as *some* consumer's dep closure happens to supply
the module. The bug only surfaces when a narrower target is built — which is how
`//models:visa_cutoff_date` shipped for months without declaring
`//models/enums:visa_category`, and only broke when `//scripts/seo:render_sitemap`
(a deliberately thin binary) imported it. See the comment in models/BUILD.

Why this check is STATIC rather than a per-target runtime import test:

1. A runtime test needs scaffolding (Django settings, //webapp:apps), and that
   scaffolding's dep closure re-supplies the very module the test is trying to
   prove is missing. The masking mechanism that hides the bug would hide the
   test for it.
2. A runtime import test only observes module-level imports. Most of the real
   violations in this repo are lazy imports inside function bodies
   (lib/ingest/base.py:122, webapp/apps.py:43), which fail at call time, not
   import time — a runtime test walks straight past them.

Static parsing has neither blind spot. The trade is that it sees only what is
statically declared: `glob()`/`select()` srcs and `importlib` calls are invisible,
and macro-injected deps must be modelled by hand (MACRO_DEPS below).

Usage:
    python3 tools/bazel_dep_check.py           # report violations, exit 1 if any
    python3 tools/bazel_dep_check.py --quiet   # exit code only
"""

import argparse
import ast
import os
import sys
from collections.abc import Iterable

PY_RULES = {"py_library", "py_binary", "py_test", "django_py_test"}

# Top-level packages that are ours. An import outside this set is third-party
# and comes in via requirement(), which this check does not model.
FIRST_PARTY = frozenset({
    "models", "lib", "webapp", "django_config", "scripts",
    "extractors", "tools", "mcp", "tests",
})

# Deps injected by macros, which the BUILD file therefore never spells out.
# Keep in sync with the macro definitions or this check reports false positives.
MACRO_DEPS = {
    # tests/django_test.bzl :: django_py_test
    "django_py_test": [":django_setup", "//django_config:settings", "//webapp:apps"],
}

# Imports this check cannot see through, with the reason. Keep this SHORT — an
# entry here is a hole in the check, not a fix.
#
# Both entries below are genuine CIRCULAR imports, which Bazel cannot express as
# deps in either direction. They are not false positives, but they fail in
# DIFFERENT ways — the fix for each is to break the cycle in code (extract the
# shared surface into a third module), never to add a dep.
ALLOWLIST: set[tuple[str, str]] = {
    # expert_pool.py:130,196,667 <-> solver.py:446,548,588. All six are lazy
    # (in-function), so this fails at CALL time with ModuleNotFoundError when a
    # target depending only on expert_pool invokes the physics experts — reachable
    # via predictors.py:7, not theoretical.
    # Fix: extract the queue engine (SolverResult, get_historical_advancement_rate,
    # calibrate_queue_depth, run_monthly_loop) out of solver into a leaf module;
    # solver re-exports them so external call sites are untouched.
    ("//lib/business/vqs:expert_pool", "lib.business.vqs.solver"),
    # prediction_month_forecast.py:428 -> prediction_views.prediction_detail, against
    # prediction_views.py:318,414,796 -> prediction_month_forecast. Bazel already
    # carries the prediction_views -> prediction_month_forecast direction, so the
    # reverse cannot be declared. This is the stable-canonical-URL design: the
    # monthname slug route renders the forecast pre-drop and delegates to
    # prediction_detail (via _render_at_slug) post-drop, in place, so the
    # ranking-established URL never 301s at peak intent. All four imports are lazy
    # (in-function), so it fails at CALL time with ModuleNotFoundError for a target
    # whose closure has only prediction_month_forecast.
    # Fix: extract the shared URL surface — prediction_canonical_path and
    # forecast_url_for — into a leaf module both import. That breaks this cycle AND
    # removes the reason webapp/views/seo:sitemaps has to depend on prediction_views
    # at all. Tracked separately; not done during the back-port because it reshapes
    # live prediction routing.
    ("//webapp/views/bulletin:prediction_month_forecast", "webapp.views.prediction_views"),
}


def _string_list(node: ast.AST | None) -> list[str]:
    """String literals in a Starlark list. Non-literals (glob, requirement) are skipped."""
    if not isinstance(node, ast.List):
        return []
    return [e.value for e in node.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]


def _type_checking_only(tree: ast.AST) -> set[int]:
    """Line numbers of imports guarded by `if TYPE_CHECKING:` — no runtime dep needed."""
    guarded: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        name = None
        if isinstance(test, ast.Name):
            name = test.id
        elif isinstance(test, ast.Attribute):
            name = test.attr
        if name != "TYPE_CHECKING":
            continue
        for child in node.body:
            for sub in ast.walk(child):
                if isinstance(sub, (ast.Import, ast.ImportFrom)):
                    guarded.add(sub.lineno)
    return guarded


class DepGraph:
    def __init__(self, root: str):
        self.root = root
        self.targets: dict[str, dict] = {}
        # A source file can be owned by SEVERAL targets — this repo pairs a
        # py_binary with a `_lib` py_library over the same srcs (e.g.
        # //scripts/cron:refresh_bulletin and :refresh_bulletin_lib). Depending
        # on any one of them supplies the module, so this maps to a set.
        self.owners: dict[str, set[str]] = {}
        self._parse_builds()

    def _parse_builds(self) -> None:
        for dirpath, dirnames, filenames in os.walk(self.root):
            dirnames[:] = [d for d in dirnames if not d.startswith("bazel-") and d != ".git"]
            if "BUILD" not in filenames:
                continue
            pkg = os.path.relpath(dirpath, self.root)
            pkg = "" if pkg == "." else pkg
            try:
                with open(os.path.join(dirpath, "BUILD"), encoding="utf-8") as fh:
                    tree = ast.parse(fh.read())
            except (SyntaxError, UnicodeDecodeError):
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                rule = getattr(node.func, "id", None)
                if rule not in PY_RULES:
                    continue
                kw = {k.arg: k.value for k in node.keywords if k.arg}
                name_node = kw.get("name")
                if not isinstance(name_node, ast.Constant):
                    continue
                label = f"//{pkg}:{name_node.value}"
                srcs = [os.path.join(pkg, s) if pkg else s for s in _string_list(kw.get("srcs"))]
                deps = _string_list(kw.get("deps")) + MACRO_DEPS.get(rule, [])
                self.targets[label] = {"srcs": srcs, "deps": deps, "pkg": pkg}
                for src in srcs:
                    self.owners.setdefault(src, set()).add(label)

    @staticmethod
    def _normalize(label: str, pkg: str) -> str:
        if label.startswith(":"):
            return f"//{pkg}:{label[1:]}"
        if label.startswith("//") and ":" not in label:
            return f"{label}:{label.rsplit('/', 1)[-1]}"
        return label

    def closure(self, label: str) -> set[str]:
        seen: set[str] = set()
        stack = [label]
        while stack:
            cur = stack.pop()
            if cur in seen or cur not in self.targets:
                continue
            seen.add(cur)
            pkg = self.targets[cur]["pkg"]
            stack.extend(self._normalize(d, pkg) for d in self.targets[cur]["deps"])
        return seen

    def _module_path(self, module: str) -> str | None:
        rel = module.replace(".", "/") + ".py"
        return rel if os.path.exists(os.path.join(self.root, rel)) else None

    def _imports(self, relpath: str) -> list[str]:
        full = os.path.join(self.root, relpath)
        if not os.path.exists(full):
            return []
        try:
            with open(full, encoding="utf-8") as fh:
                tree = ast.parse(fh.read())
        except (SyntaxError, UnicodeDecodeError):
            return []
        guarded = _type_checking_only(tree)
        modules: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Import, ast.ImportFrom)):
                continue
            if node.lineno in guarded:
                continue
            if isinstance(node, ast.Import):
                modules += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                if node.level or not node.module:
                    continue  # relative import: same package, already a src
                modules.append(node.module)
                # `from models.enums import country` also names a submodule.
                modules += [f"{node.module}.{a.name}" for a in node.names]
        return [m for m in modules if m.split(".")[0] in FIRST_PARTY]

    def violations(self) -> list[tuple[str, str, str, str]]:
        """(target, src, module, required_dep), sorted and deduped."""
        found: set[tuple[str, str, str, str]] = set()
        for label, info in self.targets.items():
            reachable = self.closure(label)
            own = set(info["srcs"])
            for src in info["srcs"]:
                for module in self._imports(src):
                    path = self._module_path(module)
                    if path is None or path in own:
                        continue
                    providers = self.owners.get(path)
                    if not providers or providers & reachable:
                        continue
                    if (label, module) in ALLOWLIST:
                        continue
                    # Report the narrowest candidate: a `_lib` library is the
                    # right dep for a test, not the py_binary beside it.
                    suggestion = sorted(providers, key=lambda p: (not p.endswith("_lib"), p))[0]
                    found.add((label, src, module, suggestion))
        return sorted(found)


def format_report(violations: Iterable[tuple[str, str, str, str]]) -> str:
    lines: list[str] = []
    current = None
    for label, src, module, provider in violations:
        if label != current:
            lines.append(f"\n{label}")
            current = label
        lines.append(f"    {src}: imports {module}\n        add dep: {provider}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    parser.add_argument("--quiet", action="store_true", help="exit code only")
    args = parser.parse_args()

    graph = DepGraph(args.root)
    violations = graph.violations()
    if not args.quiet:
        print(f"scanned {len(graph.targets)} py targets in {args.root}")
        if violations:
            print(f"\n{len(violations)} undeclared first-party import(s):")
            print(format_report(violations))
            print("\nEach import above needs the listed dep in that target's BUILD entry.")
        else:
            print("all first-party imports are declared")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
