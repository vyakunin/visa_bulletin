#!/bin/bash
# Start development server (DEVELOPMENT/TESTING ONLY)
# For production, use Docker: cd deployment && docker-compose up -d

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

echo "Starting development server on port 8000..."
echo "⚠️  This is for DEVELOPMENT/TESTING only"
echo "⚠️  For production, use: cd deployment && docker-compose up -d"
echo ""

# Load environment variables
if [ -f .env ]; then
    set -a
    source .env
    set +a
    echo "✅ Loaded .env"
else
    echo "❌ .env file not found"
    exit 1
fi

# Build runserver binary if needed
if [ ! -f "./bazel-bin/runserver" ]; then
    echo "Building runserver binary..."
    bazel build //:runserver
    bazel shutdown
fi

# Convert DB_HOST for host-based execution
if [ "$DB_HOST" = "host.docker.internal" ]; then
    export DB_HOST=localhost
    echo "✅ Converted DB_HOST to localhost (host-based execution)"
fi

# Start server
echo "Starting server..."
echo "Access at: http://localhost:8000"
echo "Stop with: Ctrl+C or pkill -f runserver"
echo ""

exec ./bazel-bin/runserver runserver 0.0.0.0:8000
