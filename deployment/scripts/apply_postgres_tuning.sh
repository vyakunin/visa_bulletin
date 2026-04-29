#!/usr/bin/env bash
# Apply Postgres performance tuning for the 2GB Lightsail instance.
#
# Default Postgres ships with workstation defaults that are wildly under-sized
# for our 5.5 GB DB. See docs/PERFORMANCE_IMPROVEMENTS.md §1.
#
# This script is idempotent: re-running with the same values is a no-op.
# It uses ALTER SYSTEM (writes to postgresql.auto.conf) so we never touch
# the distro-managed postgresql.conf.
#
# Settings:
#   shared_buffers       = 384MB   (~20% of RAM; needs a Postgres restart)
#   effective_cache_size = 1200MB  (planner hint; reload-only)
#   work_mem             = 8MB     (per-sort/hash; reload-only)
#   maintenance_work_mem = 128MB   (VACUUM/CREATE INDEX; reload-only)
#   random_page_cost     = 1.1     (SSD-shaped; reload-only)
#
# Usage:
#   ./deployment/scripts/apply_postgres_tuning.sh                # reload only
#   ./deployment/scripts/apply_postgres_tuning.sh --restart      # also restart
#                                                                # postgres so
#                                                                # shared_buffers
#                                                                # actually
#                                                                # changes
#   ./deployment/scripts/apply_postgres_tuning.sh --analyze      # also run
#                                                                # VACUUM ANALYZE
#                                                                # on the hot
#                                                                # tables
#
# Run on the host (not inside the web container). Requires sudo to talk to the
# `postgres` system user.

set -euo pipefail

WANT_RESTART=0
WANT_ANALYZE=0
for arg in "$@"; do
    case "$arg" in
        --restart) WANT_RESTART=1 ;;
        --analyze) WANT_ANALYZE=1 ;;
        --help|-h)
            sed -n '2,30p' "$0"
            exit 0
            ;;
        *)
            echo "Unknown arg: $arg" >&2
            exit 2
            ;;
    esac
done

# Use sudo -u postgres so we don't need pg_hba role for the running user.
psql_postgres() {
    sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 "$@"
}

echo "[apply_postgres_tuning] Current settings before change:"
psql_postgres -tAc "
    SELECT name || ' = ' || setting || COALESCE(' ' || unit, '')
    FROM pg_settings
    WHERE name IN (
        'shared_buffers', 'effective_cache_size', 'work_mem',
        'maintenance_work_mem', 'random_page_cost'
    )
    ORDER BY name;
"

echo "[apply_postgres_tuning] Applying ALTER SYSTEM settings..."
psql_postgres <<'SQL'
ALTER SYSTEM SET shared_buffers = '384MB';
ALTER SYSTEM SET effective_cache_size = '1200MB';
ALTER SYSTEM SET work_mem = '8MB';
ALTER SYSTEM SET maintenance_work_mem = '128MB';
ALTER SYSTEM SET random_page_cost = 1.1;
SQL

echo "[apply_postgres_tuning] Reloading Postgres config (picks up everything except shared_buffers)..."
psql_postgres -c "SELECT pg_reload_conf();" >/dev/null
echo "[apply_postgres_tuning] Reload OK."

if [ "$WANT_RESTART" = "1" ]; then
    echo "[apply_postgres_tuning] Restarting Postgres so shared_buffers takes effect..."
    # Detect the cluster name + version from pg_lsclusters when available;
    # fall back to systemd unit pattern.
    if command -v pg_lsclusters >/dev/null 2>&1; then
        version=$(pg_lsclusters -h | awk 'NR==1 {print $1}')
        cluster=$(pg_lsclusters -h | awk 'NR==1 {print $2}')
        echo "[apply_postgres_tuning] Restarting cluster ${version}/${cluster} via systemd..."
        sudo systemctl restart "postgresql@${version}-${cluster}.service"
    else
        sudo systemctl restart postgresql
    fi
    # Wait for it to come back.
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        if psql_postgres -tAc 'SELECT 1' >/dev/null 2>&1; then
            echo "[apply_postgres_tuning] Postgres is back."
            break
        fi
        sleep 1
    done
else
    echo "[apply_postgres_tuning] (skipping restart; pass --restart to make shared_buffers take effect)"
fi

if [ "$WANT_ANALYZE" = "1" ]; then
    echo "[apply_postgres_tuning] Refreshing planner stats on hot tables..."
    sudo -u postgres psql -d visa_bulletin -v ON_ERROR_STOP=1 <<'SQL'
VACUUM (ANALYZE, VERBOSE) salary_record;
VACUUM (ANALYZE, VERBOSE) salary_employer;
VACUUM (ANALYZE, VERBOSE) salary_employer_cluster;
VACUUM (ANALYZE, VERBOSE) salary_job_title;
VACUUM (ANALYZE, VERBOSE) salary_job_title_cluster;
SQL
fi

echo "[apply_postgres_tuning] Settings after change (in_use shows what is live now):"
psql_postgres -tAc "
    SELECT name || ' = ' || setting || COALESCE(' ' || unit, '') ||
           CASE WHEN pending_restart THEN ' [PENDING RESTART]' ELSE '' END
    FROM pg_settings
    WHERE name IN (
        'shared_buffers', 'effective_cache_size', 'work_mem',
        'maintenance_work_mem', 'random_page_cost'
    )
    ORDER BY name;
"

echo "[apply_postgres_tuning] Done."
