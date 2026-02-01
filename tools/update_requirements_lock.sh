#!/bin/bash
# Update requirements.lock from requirements.txt using pip-compile
# Requires: pip-tools installed (pip install pip-tools)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WORKSPACE_DIR="${BUILD_WORKSPACE_DIRECTORY:-$(cd "$SCRIPT_DIR/.." && pwd)}"
cd "$WORKSPACE_DIR"

REQUIREMENTS_TXT="$WORKSPACE_DIR/requirements.txt"
REQUIREMENTS_LOCK="$WORKSPACE_DIR/requirements.lock"

if [ ! -f "$REQUIREMENTS_TXT" ]; then
    echo "ERROR: $REQUIREMENTS_TXT not found" >&2
    exit 1
fi

# Ensure user site-packages are in PYTHONPATH
USER_SITE=$(python3 -m site --user-site 2>/dev/null || echo "")
if [ -n "$USER_SITE" ] && [ -d "$USER_SITE" ]; then
    export PYTHONPATH="${USER_SITE}:${PYTHONPATH:-}"
fi

# Check if pip-compile is available, install if needed
if ! command -v pip-compile &> /dev/null; then
    if ! python3 -c "import pip_tools" &> /dev/null 2>&1; then
        echo "Installing pip-tools..." >&2
        python3 -m pip install --quiet --user pip-tools 2>&1 || {
            echo "ERROR: Failed to install pip-tools. Install manually with:" >&2
            echo "  python3 -m pip install --user pip-tools" >&2
            exit 1
        }
        # Re-export PYTHONPATH after installation
        USER_SITE=$(python3 -m site --user-site 2>/dev/null || echo "")
        if [ -n "$USER_SITE" ] && [ -d "$USER_SITE" ]; then
            export PYTHONPATH="${USER_SITE}:${PYTHONPATH:-}"
        fi
    fi
fi

# Determine command to use
if command -v pip-compile &> /dev/null; then
    PIP_COMPILE_CMD="pip-compile"
else
    # Use python3 with explicit PYTHONPATH
    PIP_COMPILE_CMD="python3 -m pip_tools.cli"
fi

echo "Generating $REQUIREMENTS_LOCK from $REQUIREMENTS_TXT..."
echo "Using: $PIP_COMPILE_CMD"

$PIP_COMPILE_CMD \
    --output-file "$REQUIREMENTS_LOCK" \
    "$REQUIREMENTS_TXT"

echo "✓ Successfully generated $REQUIREMENTS_LOCK"
echo ""
echo "Next steps:"
echo "  1. Review $REQUIREMENTS_LOCK"
echo "  2. Commit if changes look correct"
echo "  3. Bazel will use the lock file automatically"










