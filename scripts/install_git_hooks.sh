#!/bin/bash
#
# Install the repo's tracked git hooks into this clone.
#
# Usage:
#   ./scripts/install_git_hooks.sh            # symlink (default — cannot drift)
#   ./scripts/install_git_hooks.sh --copy     # copy, for filesystems without symlinks
#   ./scripts/install_git_hooks.sh --check    # verify only; exit 1 if not installed
#
# Installs into $GIT_COMMON_DIR/hooks, NOT via core.hooksPath. Setting a
# repo-local core.hooksPath would shadow a machine-global hooks dir if one is
# configured, silently disabling whatever else it runs (commit-msg, pre-push).
# The common-dir path is deliberate too: in a linked worktree
# --absolute-git-dir points at .git/worktrees/<name>/, which has no hooks/, so
# installing there would leave every other worktree ungated.
#
# Symlinks by default so the installed hook cannot drift from the tracked one —
# a copy silently keeps running an old gate after the tracked hook is fixed,
# which is the failure this script exists to end.

set -euo pipefail

MODE="symlink"
case "${1:-}" in
    --copy)  MODE="copy" ;;
    --check) MODE="check" ;;
    "")      ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
esac

REPO_ROOT=$(git rev-parse --show-toplevel)
HOOKS_DIR=$(git rev-parse --path-format=absolute --git-common-dir)/hooks
SRC="$REPO_ROOT/tools/hooks/pre-commit"
DEST="$HOOKS_DIR/pre-commit"

[ -f "$SRC" ] || { echo "❌ missing $SRC" >&2; exit 1; }

if [ "$MODE" = "check" ]; then
    if [ ! -x "$DEST" ]; then
        echo "❌ no pre-commit hook installed at $DEST"
        echo "   run: ./scripts/install_git_hooks.sh"
        exit 1
    fi
    if diff -q "$SRC" "$DEST" >/dev/null 2>&1; then
        echo "✅ pre-commit hook installed and current ($DEST)"
        exit 0
    fi
    echo "⚠️  installed hook DIFFERS from the tracked one at $SRC"
    echo "   re-run: ./scripts/install_git_hooks.sh"
    exit 1
fi

mkdir -p "$HOOKS_DIR"

# Never clobber a hand-written hook without keeping a copy of it.
if [ -e "$DEST" ] && [ ! -L "$DEST" ] && ! diff -q "$SRC" "$DEST" >/dev/null 2>&1; then
    BACKUP="$DEST.bak.$(date +%Y%m%d_%H%M%S)"
    cp "$DEST" "$BACKUP"
    echo "ℹ️  existing hook backed up to $BACKUP"
fi

# Build beside the target and rename over it. rm-then-create leaves a window in
# which the hook does not exist, and a commit landing in that window is not
# merely delayed — the global dispatcher's `[ -x "$local_hook" ]` test fails and
# the commit proceeds UNGATED, silently. rename(2) is atomic, so there is no
# instant at which $DEST is missing. Matters because clones get shared.
TMP="$DEST.installing.$$"
rm -f "$TMP"
if [ "$MODE" = "copy" ]; then
    cp "$SRC" "$TMP"
else
    ln -s "$SRC" "$TMP"
fi
chmod +x "$TMP"
mv -f "$TMP" "$DEST"

echo "✅ installed pre-commit hook: $DEST -> $SRC ($MODE)"
echo "   It runs ruff, tools/bazel_dep_check.py, then bazel test //tests:all."
echo "   Verify at any time with: ./scripts/install_git_hooks.sh --check"
