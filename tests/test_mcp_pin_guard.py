"""Static guard: PEP-723 scripts sharing the daily_checkup MCP server must pin mcp to 1.x.

`mcp/daily_checkup_server.py` imports `mcp.server.fastmcp.FastMCP`. That module
exists only on the mcp 1.x line — mcp 2.0.0 removed it outright (the successor is
`mcp.server.mcpserver.MCPServer`, a different API). The server itself never noticed,
because the orchestrator runs it from `mcp/` where `uv.lock` pins mcp==1.27.1.

The CLI scripts under `scripts/` import that same module, but each carries its own
PEP-723 inline dependency list and so resolves its own ephemeral env. While those
listed a bare `"mcp"`, uv resolved whatever was newest at the moment each env was
built — so the scripts died one at a time, silently and on different days, as their
cached envs were rebuilt after mcp 2.0.0 shipped. Two were already dead when this
guard was written (`gc_section_shares`, `run_daily_checkup`, both on 2.0.0) while two
still ran on stale 1.28.1 envs. Nothing failed loudly; the daily digest kept working,
which is exactly why the breakage went unnoticed.

The constraint has one owner, `mcp/pyproject.toml`. PEP-723 inline metadata cannot
import a shared value, so each script must restate it — and restated constraints drift.
This test is what keeps them equal:

  1. the owner admits the locked version and excludes 2.0.0,
  2. every script in the class does the same,
  3. the class is non-empty (a scan that matches nothing must not pass vacuously).

SCOPE: top-level `scripts/*.py`, which is where every current importer lives. A future
importer under `scripts/<subdir>/` is a separate Bazel package and would need adding to
this target's `data`. Nothing here checks that mcp 1.x still *publishes* `fastmcp` — that
is what actually running a script proves, and no hermetic test can.
"""

import re
import sys
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS_DIR = _REPO / "scripts"
_OWNER_PYPROJECT = _REPO / "mcp" / "pyproject.toml"
_OWNER_LOCK = _REPO / "mcp" / "uv.lock"

# The shared module whose import creates the mcp dependency in the first place.
_SHARED_MODULE = "daily_checkup_server"

# A version that must NOT satisfy any declared constraint: it is the release that
# dropped `mcp.server.fastmcp` and would break every importer of the shared module.
_BREAKING_VERSION = Version("2.0.0")

# PEP-723 inline metadata: a `# /// script` ... `# ///` block of commented TOML.
_PEP723_BLOCK = re.compile(
    r"^# /// script\s*$(?P<body>.*?)^# ///\s*$",
    re.MULTILINE | re.DOTALL,
)


def _parse_pep723(source: str) -> dict | None:
    """Return a script's PEP-723 inline metadata, or None if it carries none."""
    match = _PEP723_BLOCK.search(source)
    if match is None:
        return None
    # Strip the leading "# " (or a bare "#") from each line to recover the TOML.
    body = "\n".join(
        line[2:] if line.startswith("# ") else line[1:]
        for line in match.group("body").splitlines()
        if line.startswith("#")
    )
    return tomllib.loads(body)


def _mcp_requirement(dependencies: list[str]) -> Requirement | None:
    for dep in dependencies:
        req = Requirement(dep)
        if req.name == "mcp":
            return req
    return None


def _locked_mcp_version() -> Version:
    """The mcp version the daily_checkup server actually runs on."""
    lock = tomllib.loads(_OWNER_LOCK.read_text(encoding="utf-8"))
    for package in lock.get("package", []):
        if package.get("name") == "mcp":
            return Version(package["version"])
    pytest.fail(f"no 'mcp' package entry in {_OWNER_LOCK} — lockfile shape changed?")


def _scripts_importing_shared_module() -> list[Path]:
    """Top-level scripts that import the shared module AND declare inline deps."""
    found = []
    for path in sorted(_SCRIPTS_DIR.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        if _SHARED_MODULE not in source:
            continue
        if not re.search(rf"^from {_SHARED_MODULE} import|^import {_SHARED_MODULE}",
                         source, re.MULTILINE):
            continue
        if _parse_pep723(source) is None:
            continue
        found.append(path)
    return found


def _owner_mcp_requirement() -> Requirement:
    pyproject = tomllib.loads(_OWNER_PYPROJECT.read_text(encoding="utf-8"))
    req = _mcp_requirement(pyproject["project"]["dependencies"])
    assert req is not None, f"{_OWNER_PYPROJECT} no longer declares an 'mcp' dependency"
    return req


def test_pep723_metadata_parser_reads_a_real_header():
    """The scan is only as good as its parser — pin it against a known header."""
    parsed = _parse_pep723(
        '#!/usr/bin/env -S uv run --script\n'
        '# /// script\n'
        '# requires-python = ">=3.11"\n'
        '# dependencies = ["httpx", "mcp>=1.0.0,<2"]\n'
        '# ///\n'
        '"""docstring"""\n'
    )
    assert parsed is not None
    assert parsed["dependencies"] == ["httpx", "mcp>=1.0.0,<2"]
    assert _parse_pep723('"""no inline metadata here"""\n') is None


def test_owner_constraint_admits_the_locked_version_and_excludes_2x():
    """mcp/pyproject.toml owns the constraint; it must match what the server runs on."""
    req = _owner_mcp_requirement()
    locked = _locked_mcp_version()

    assert req.specifier.contains(locked, prereleases=True), (
        f"{_OWNER_PYPROJECT} declares 'mcp{req.specifier}', which excludes the locked "
        f"version {locked} from {_OWNER_LOCK}. The declaration and the lock disagree."
    )
    assert not req.specifier.contains(_BREAKING_VERSION, prereleases=True), (
        f"{_OWNER_PYPROJECT} declares 'mcp{req.specifier}', which admits "
        f"{_BREAKING_VERSION}. That release removed `mcp.server.fastmcp`, so a "
        f"`uv lock --upgrade` would silently break the daily digest."
    )


def test_the_class_of_dependent_scripts_is_non_empty():
    """A scan that silently matches nothing would pass every other assertion here."""
    scripts = _scripts_importing_shared_module()
    assert scripts, (
        f"no script under {_SCRIPTS_DIR} was found importing {_SHARED_MODULE!r} with "
        "PEP-723 inline metadata. Either the scan broke, or the scripts moved and this "
        "guard is now watching nothing."
    )


@pytest.mark.parametrize(
    "script",
    _scripts_importing_shared_module(),
    ids=lambda p: p.name,
)
def test_dependent_script_pins_mcp_to_the_line_the_server_runs(script: Path):
    """Every importer must resolve the same mcp line the daily_checkup server uses."""
    metadata = _parse_pep723(script.read_text(encoding="utf-8"))
    req = _mcp_requirement(metadata.get("dependencies", []))

    assert req is not None, (
        f"{script.name} imports {_SHARED_MODULE} but declares no 'mcp' dependency; "
        "the import will fail under `uv run`."
    )
    assert str(req.specifier), (
        f"{script.name} declares a bare 'mcp' with no version bound, so `uv run` "
        f"resolves whatever is newest — today that is >= {_BREAKING_VERSION}, which "
        f"removed `mcp.server.fastmcp` and breaks the import. Declare the bound from "
        f"{_OWNER_PYPROJECT.name}: 'mcp{_owner_mcp_requirement().specifier}'."
    )
    assert not req.specifier.contains(_BREAKING_VERSION, prereleases=True), (
        f"{script.name} declares 'mcp{req.specifier}', which admits "
        f"{_BREAKING_VERSION} — the release that removed `mcp.server.fastmcp`."
    )
    locked = _locked_mcp_version()
    assert req.specifier.contains(locked, prereleases=True), (
        f"{script.name} declares 'mcp{req.specifier}', which excludes {locked} — the "
        f"version {_OWNER_LOCK.name} pins for the daily_checkup server. The CLI and the "
        "digest would run different mcp lines."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
