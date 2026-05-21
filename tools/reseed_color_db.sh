#!/usr/bin/env bash
# tools/reseed_color_db.sh — Reseed one color's postgres DB from another color's.
#
# Built for the blue-green migration plan (Notion ticket
# "Blue-green deploys: migration plan from current staging+prod (homeserver)").
# This script is the primitive that blue_green_deploy.sh and the refresh
# pipeline both call: pg_dump from source container, pg_restore into target.
#
# Runs ON homeserver, operating on local docker containers via docker exec.
# Target web container is stopped during restore; restarted on completion.
#
# Usage:
#   tools/reseed_color_db.sh [--dry-run] [--no-stop-target] <source-color> <target-color>
#
# Color aliases (stack_dir : postgres_container : web_container):
#   blue    => /opt/stack/visa_bulletin            : vb_postgres        : vb_web
#   green   => /opt/stack/visa_bulletin_green      : vb_green_postgres  : vb_green_web
#   staging => /opt/stack/visa_bulletin_staging    : vb_stg_postgres    : vb_stg_web   (legacy, pre-blue-green)
#
# Exit codes:
#   0 = success
#   1 = usage / setup error
#   2 = row-count verification failed
#   3 = dump or restore step failed

set -euo pipefail

usage() {
  sed -n '2,/^$/p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
}

DRY_RUN=0
STOP_TARGET=1
while [[ $# -gt 0 && "$1" == --* ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1 ;;
    --no-stop-target) STOP_TARGET=0 ;;
    -h|--help) usage ;;
    *) echo "Unknown flag: $1" >&2; usage ;;
  esac
  shift
done
[[ $# -eq 2 ]] || usage

resolve_color() {
  case "$1" in
    blue)    echo "/opt/stack/visa_bulletin:vb_postgres:vb_web" ;;
    green)   echo "/opt/stack/visa_bulletin_green:vb_green_postgres:vb_green_web" ;;
    staging) echo "/opt/stack/visa_bulletin_staging:vb_stg_postgres:vb_stg_web" ;;
    *) echo "Unknown color: $1 (want: blue|green|staging)" >&2; exit 1 ;;
  esac
}

SRC="$1"; TGT="$2"
[[ "$SRC" == "$TGT" ]] && { echo "Source and target must differ" >&2; exit 1; }

IFS=: read -r SRC_DIR SRC_PG SRC_WEB <<<"$(resolve_color "$SRC")"
IFS=: read -r TGT_DIR TGT_PG TGT_WEB <<<"$(resolve_color "$TGT")"

# Read DB creds from each .env. Subshell so we don't leak vars.
read_env() {
  local env_file="$1" key="$2"
  [[ -f "$env_file" ]] || { echo "Missing $env_file" >&2; exit 1; }
  grep -E "^${key}=" "$env_file" | head -1 | cut -d= -f2-
}

SRC_DB_NAME=$(read_env "$SRC_DIR/.env" DB_NAME)
SRC_DB_USER=$(read_env "$SRC_DIR/.env" DB_USER)
SRC_DB_PASS=$(read_env "$SRC_DIR/.env" DB_PASSWORD)
TGT_DB_NAME=$(read_env "$TGT_DIR/.env" DB_NAME)
TGT_DB_USER=$(read_env "$TGT_DIR/.env" DB_USER)
TGT_DB_PASS=$(read_env "$TGT_DIR/.env" DB_PASSWORD)

echo "[reseed_color_db] Source: $SRC ($SRC_PG / db=$SRC_DB_NAME)"
echo "[reseed_color_db] Target: $TGT ($TGT_PG / db=$TGT_DB_NAME)"

# Verify containers exist
docker inspect "$SRC_PG" >/dev/null 2>&1 || { echo "Source container $SRC_PG not found" >&2; exit 1; }
docker inspect "$TGT_PG" >/dev/null 2>&1 || { echo "Target container $TGT_PG not found" >&2; exit 1; }

if [[ "$DRY_RUN" == 1 ]]; then
  echo "[reseed_color_db] DRY RUN — args resolve cleanly; containers reachable. Exiting without changes."
  exit 0
fi

START_AFTER=0
if [[ "$STOP_TARGET" == 1 ]] && docker inspect "$TGT_WEB" >/dev/null 2>&1; then
  if [[ "$(docker inspect -f '{{.State.Running}}' "$TGT_WEB")" == "true" ]]; then
    echo "[reseed_color_db] Stopping $TGT_WEB during restore"
    docker stop "$TGT_WEB" >/dev/null
    START_AFTER=1
  fi
fi

DUMP_FILE="/tmp/reseed_${SRC}_to_${TGT}_$(date +%Y%m%d_%H%M%S).dump"
echo "[reseed_color_db] $(date -Iseconds) Dumping $SRC_PG:$SRC_DB_NAME → $DUMP_FILE (custom format)"
if ! docker exec -e PGPASSWORD="$SRC_DB_PASS" "$SRC_PG" \
     pg_dump -U "$SRC_DB_USER" -d "$SRC_DB_NAME" -Fc --no-owner --no-acl > "$DUMP_FILE"; then
  echo "[reseed_color_db] pg_dump failed" >&2
  [[ "$START_AFTER" == 1 ]] && docker start "$TGT_WEB" >/dev/null || true
  exit 3
fi
DUMP_MB=$(( $(stat -c%s "$DUMP_FILE") / 1024 / 1024 ))
echo "[reseed_color_db] $(date -Iseconds) Dump complete: ${DUMP_MB} MB"

echo "[reseed_color_db] $(date -Iseconds) Recreating target DB $TGT_DB_NAME on $TGT_PG"
# Drop+create requires no active connections to the DB. Force-disconnect first.
docker exec -e PGPASSWORD="$TGT_DB_PASS" "$TGT_PG" psql -U "$TGT_DB_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${TGT_DB_NAME}' AND pid <> pg_backend_pid();" >/dev/null
docker exec -e PGPASSWORD="$TGT_DB_PASS" "$TGT_PG" psql -U "$TGT_DB_USER" -d postgres -c \
  "DROP DATABASE IF EXISTS ${TGT_DB_NAME};"
docker exec -e PGPASSWORD="$TGT_DB_PASS" "$TGT_PG" psql -U "$TGT_DB_USER" -d postgres -c \
  "CREATE DATABASE ${TGT_DB_NAME} OWNER ${TGT_DB_USER};"

echo "[reseed_color_db] $(date -Iseconds) Restoring into $TGT_PG:$TGT_DB_NAME"
# pg_restore --jobs=N is not supported when reading from stdin; we accept the
# serial restore here (still fast enough for ~4GB DBs). For larger DBs, copy
# the dump into the target container first and use --jobs.
if ! cat "$DUMP_FILE" | docker exec -i -e PGPASSWORD="$TGT_DB_PASS" "$TGT_PG" \
     pg_restore -U "$TGT_DB_USER" -d "$TGT_DB_NAME" --no-owner --no-acl 2>&1 | tail -20; then
  echo "[reseed_color_db] pg_restore failed" >&2
  [[ "$START_AFTER" == 1 ]] && docker start "$TGT_WEB" >/dev/null || true
  exit 3
fi
echo "[reseed_color_db] $(date -Iseconds) Restore complete."

echo "[reseed_color_db] Row-count verification on key tables:"
TABLES=(salary_record worksite_record salary_employer salary_employer_cluster salary_job_title_cluster visa_cutoff_date)
MISMATCH=0
for t in "${TABLES[@]}"; do
  SRC_N=$(docker exec -e PGPASSWORD="$SRC_DB_PASS" "$SRC_PG" psql -U "$SRC_DB_USER" -d "$SRC_DB_NAME" -tA -c "SELECT count(*) FROM $t" 2>/dev/null || echo "?")
  TGT_N=$(docker exec -e PGPASSWORD="$TGT_DB_PASS" "$TGT_PG" psql -U "$TGT_DB_USER" -d "$TGT_DB_NAME" -tA -c "SELECT count(*) FROM $t" 2>/dev/null || echo "?")
  if [[ "$SRC_N" == "$TGT_N" ]]; then
    printf "  ✓ %-35s %12s rows\n" "$t" "$SRC_N"
  else
    printf "  ✗ %-35s src=%s tgt=%s\n" "$t" "$SRC_N" "$TGT_N"
    MISMATCH=1
  fi
done

if [[ "$START_AFTER" == 1 ]]; then
  echo "[reseed_color_db] Restarting $TGT_WEB"
  docker start "$TGT_WEB" >/dev/null
fi

rm -f "$DUMP_FILE"

if [[ "$MISMATCH" == 1 ]]; then
  echo "[reseed_color_db] FAIL — row count mismatch" >&2
  exit 2
fi

echo "[reseed_color_db] $(date -Iseconds) DONE."
