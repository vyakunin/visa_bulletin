#!/bin/bash
# Restart the local development server

set -e

# Get workspace root (works both from Bazel and direct execution)
if [ -n "$BUILD_WORKSPACE_DIRECTORY" ]; then
    PROJECT_ROOT="$BUILD_WORKSPACE_DIRECTORY"
else
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

echo "🛑 Stopping existing server..."
pkill -9 -f "runserver" 2>/dev/null || echo "   (no server was running)"

sleep 2

echo "🚀 Starting server..."
cd "$PROJECT_ROOT"

# Run bazel from the workspace root (not from bazel-bin)
exec bazel run //:runserver

