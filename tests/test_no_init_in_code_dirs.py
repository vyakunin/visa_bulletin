"""
Enforce no __init__.py in designated code directories.

Scans the directories listed in NO_INIT_DIRS and fails if any contain __init__.py.
See .cursor/rules/general_code_health.mdc "No __init__.py in Designated Code Directories".
"""

import os
from pathlib import Path


# Directories that must not contain __init__.py (paths relative to repo root).
NO_INIT_DIRS = [
    "lib/business/salary",
]


def _repo_root() -> Path:
    """Return workspace/repo root (Bazel sets BUILD_WORKSPACE_DIRECTORY)."""
    if os.environ.get("BUILD_WORKSPACE_DIRECTORY"):
        return Path(os.environ["BUILD_WORKSPACE_DIRECTORY"])
    # Fallback when run outside Bazel (e.g. pytest in IDE): tests/ -> repo root
    return Path(__file__).resolve().parent.parent


def test_no_init_in_code_dirs():
    """Fail if any designated code directory contains __init__.py."""
    root = _repo_root()
    found = []
    for rel_dir in NO_INIT_DIRS:
        init_py = root / rel_dir / "__init__.py"
        if init_py.exists():
            found.append(init_py)
    assert not found, (
        f"__init__.py must not exist in designated code dirs. Found: {[str(p) for p in found]}. "
        "See .cursor/rules/general_code_health.mdc 'No __init__.py in Designated Code Directories'."
    )
