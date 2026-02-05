#!/bin/bash
# scripts/cron/refresh_data.sh
# Thin wrapper: source .env and run Python refresh pipeline (local).
#
# For cross-instance (prod -> staging): run refresh_and_switch.py instead:
#   bazel run //scripts/cron:refresh_and_switch_py -- --no-traffic-switch   # first validation
#   bazel run //scripts/cron:refresh_and_switch_py                          # full cycle with traffic switch
#
# OPTIONS: passed to refresh_data.py (e.g. --resume)
# Cron: 0 2 * * 0 cd /opt/visa_bulletin && scripts/cron/refresh_data.sh >> /var/log/visa-bulletin/refresh.log 2>&1

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_ROOT"
export BUILD_WORKSPACE_DIRECTORY="$PROJECT_ROOT"
set -a
[ -f .env ] && source .env
set +a
if [ "${DB_HOST:-}" = "host.docker.internal" ]; then
    export DB_HOST=localhost
fi
exec python3 scripts/cron/refresh_data.py "$@"
