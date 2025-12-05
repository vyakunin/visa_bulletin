#!/bin/bash
# Restart the local development server

set -e

# Initialize Homebrew if available (for Apple Silicon Macs)
if [ -x /opt/homebrew/bin/brew ]; then
    eval "$(/opt/homebrew/bin/brew shellenv)"
elif [ -x /usr/local/bin/brew ]; then
    eval "$(/usr/local/bin/brew shellenv)"
fi

# Get workspace root (works both from Bazel and direct execution)
if [ -n "$BUILD_WORKSPACE_DIRECTORY" ]; then
    PROJECT_ROOT="$BUILD_WORKSPACE_DIRECTORY"
else
    PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi

echo "🛑 Stopping existing server..."
# Find and gracefully terminate runserver processes
pgrep -f "runserver" > /dev/null && pkill -TERM -f "runserver" && sleep 2
# If still running, force kill
pgrep -f "runserver" > /dev/null && pkill -KILL -f "runserver" && sleep 1
echo "   ✓ Server stopped"

echo "🚀 Starting server..."
cd "$PROJECT_ROOT"

# Verify bazel is available
if ! command -v bazel &> /dev/null; then
    echo "❌ Error: bazel not found in PATH"
    echo "   PATH: $PATH"
    echo "   Try: brew install bazelisk"
    exit 1
fi

# Run bazel from the workspace root (not from bazel-bin)
if [[ "$1" == "--background" ]]; then
    # Background mode: redirect output to log file
    LOG_FILE="/tmp/visa-bulletin-server.log"
    nohup bazel run //:runserver > "$LOG_FILE" 2>&1 &
    SERVER_PID=$!
    echo "   ✓ Server started in background (PID: $SERVER_PID)"
    echo "   📋 Logs: tail -f $LOG_FILE"
    echo "   🛑 Stop: kill $SERVER_PID or pkill -f runserver"
else
    # Foreground mode: for interactive use
    exec bazel run //:runserver
fi

