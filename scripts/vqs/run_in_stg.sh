#!/usr/bin/env bash
# Run a VQS script/module against the LIVE staging DB (prod-copy data) with the
# current *working tree* mounted over /app — so uncommitted model edits are
# exercised. Uses the same runtime image the staging web container runs, joined
# to the staging compose network for Postgres access.
#
# This is the canonical way to iterate on backtests / evaluate_model /
# publish_predictions while developing VQS model changes locally (the staging
# web container runs *committed* code and has no repo mount, so it can't see
# working-tree edits). See docs/PREDICTION_SYSTEM_OVERVIEW.md §4.
#
# Usage:
#   scripts/vqs/run_in_stg.sh -m scripts.vqs.backtest_fy_boundary --start-year 2016
#   scripts/vqs/run_in_stg.sh -m scripts.vqs.analyze_fy_transitions
#   scripts/vqs/run_in_stg.sh -m scripts.vqs.evaluate_model --horizons 1 3 6
#   scripts/vqs/run_in_stg.sh scripts/vqs/run_backtest.py --help   # (file form ok too)
#
# Env overrides: VB_STG_WEB (default vb_stg_web), VB_STG_NET (auto-detected).
set -euo pipefail

WEB="${VB_STG_WEB:-vb_stg_web}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if ! docker inspect "$WEB" >/dev/null 2>&1; then
  echo "error: staging web container '$WEB' not found (is the staging stack up?)" >&2
  exit 1
fi

NET="${VB_STG_NET:-$(docker inspect "$WEB" --format '{{range $k,$v := .NetworkSettings.Networks}}{{$k}}{{end}}')}"
IMAGE="$(docker inspect "$WEB" --format '{{.Config.Image}}')"
DBP="$(docker exec "$WEB" printenv DB_PASSWORD)"
DBN="$(docker exec "$WEB" printenv DB_NAME)"
DBU="$(docker exec "$WEB" printenv DB_USER)"

exec docker run --rm --network "$NET" \
  -v "$REPO_ROOT":/app -w /app \
  -e PYTHONPATH=/app \
  -e DJANGO_SETTINGS_MODULE=django_config.settings \
  -e DB_HOST=postgres -e DB_PORT=5432 \
  -e DB_NAME="$DBN" -e DB_USER="$DBU" -e DB_PASSWORD="$DBP" \
  "$IMAGE" python3 "$@"
