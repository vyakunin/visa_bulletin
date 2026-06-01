#!/usr/bin/env bash
# refresh_via_staging.sh — quarterly DOL data refresh on the homeserver, done
# safely on the STAGING stack and (optionally) promoted to prod.
#
# WHY THIS EXISTS
#   Prod must never run the heavy/flaky ingest directly (it drops indexes and
#   can fail mid-load). This script mirrors prod -> staging, ingests the new
#   DOL quarter on staging, validates, and leaves promotion as an explicit
#   gated step. Goal: a near-unsupervised quarterly refresh.
#
# RUN ON: the homeserver (has the vb_* / vb_stg_* containers). No Bazel here —
#   pipeline steps run as `docker exec -w /app vb_stg_web python3 -m <module>`.
#
# USAGE
#   ./refresh_via_staging.sh reseed     # mirror prod DB -> staging (drops+restores)
#   ./refresh_via_staging.sh ingest     # drop indexes -> discover+ingest DOL -> recreate -> cluster -> stats
#   ./refresh_via_staging.sh verify     # spot-check staging vs prod
#   ./refresh_via_staging.sh all        # reseed + ingest + verify (NOT promote)
#   ./refresh_via_staging.sh promote    # GATED: atomic postgres-data volume swap (asks first)
#
# Each phase is idempotent enough to re-run. Secrets (DB_PASSWORD) are read
# from each stack's .env at call time and never echoed.
set -euo pipefail

PROD_DIR=/opt/stack/visa_bulletin
STG_DIR=/opt/stack/visa_bulletin_staging
PROD_PG=vb_postgres
STG_PG=vb_stg_postgres
STG_WEB=vb_stg_web
DB=visa_bulletin
DB_USER=visa_bulletin_user
MIN_FREE_GB=6                       # abort if root free space below this
LOG="/tmp/vb_refresh_$(date +%Y%m%d_%H%M%S).log"

log(){ echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }
prod_pw(){ grep '^DB_PASSWORD=' "$PROD_DIR/.env" | cut -d= -f2-; }
stg_pw(){  grep '^DB_PASSWORD=' "$STG_DIR/.env"  | cut -d= -f2-; }
# psql into a container; password passed via -e so it never hits the cmdline log
spsql(){ docker exec -e PGPASSWORD="$(stg_pw)" "$STG_PG" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB" -t -A -F'|' -c "$1"; }

check_disk(){
  local free_gb; free_gb=$(df -BG / | awk 'NR==2{gsub("G","",$4); print $4}')
  log "disk free: ${free_gb}G"
  if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    log "ABORT: free disk ${free_gb}G < ${MIN_FREE_GB}G. Run: docker builder prune -f && docker image prune -f"
    exit 1
  fi
}

prod_health(){ curl -s -o /dev/null -w 'prod=%{http_code} t=%{time_total}s' https://visa-bulletin.us/ | tee -a "$LOG"; echo; }

# --- PG planner tuning (re-applied after every reseed; reseed wipes auto.conf) ---
apply_pg_tuning(){
  log "re-applying staging PG tuning (SSD planner settings)"
  docker exec -e PGPASSWORD="$(stg_pw)" "$STG_PG" psql -h 127.0.0.1 -U "$DB_USER" -d "$DB" -c "
    ALTER SYSTEM SET random_page_cost=1.1;
    ALTER SYSTEM SET effective_io_concurrency=200;
    ALTER SYSTEM SET effective_cache_size='3GB';
    ALTER SYSTEM SET work_mem='16MB';
    ALTER SYSTEM SET default_statistics_target=200;
    SELECT pg_reload_conf();" >>"$LOG" 2>&1
}

phase_reseed(){
  check_disk
  log "bringing up staging postgres+redis"
  ( cd "$STG_DIR" && docker compose up -d postgres redis )
  for i in $(seq 1 20); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$STG_PG" 2>/dev/null)" = healthy ] && break; sleep 3
  done
  log "reseed: drop+recreate staging DB, stream pg_dump(prod) -> pg_restore(staging)"
  docker exec -e PGPASSWORD="$(stg_pw)" "$STG_PG" psql -h 127.0.0.1 -U "$DB_USER" -d postgres -c \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='$DB' AND pid<>pg_backend_pid();" >>"$LOG" 2>&1
  docker exec -e PGPASSWORD="$(stg_pw)" "$STG_PG" dropdb   -h 127.0.0.1 -U "$DB_USER" --if-exists "$DB"
  docker exec -e PGPASSWORD="$(stg_pw)" "$STG_PG" createdb -h 127.0.0.1 -U "$DB_USER" "$DB"
  docker exec -e PGPASSWORD="$(prod_pw)" "$PROD_PG" pg_dump -h 127.0.0.1 -U "$DB_USER" -Fc -d "$DB" \
    | docker exec -i -e PGPASSWORD="$(stg_pw)" "$STG_PG" pg_restore -h 127.0.0.1 -U "$DB_USER" -d "$DB" --no-owner --no-privileges
  apply_pg_tuning
  log "reseed done: salary=$(spsql 'SELECT COUNT(*) FROM salary_record') bulletins=$(spsql 'SELECT COUNT(*) FROM bulletin')"
  ( cd "$STG_DIR" && docker compose up -d web nginx )   # web boot also runs migrate
}

# Run a pipeline / salary module inside the staging web container.
sweb(){ docker exec -w /app "$STG_WEB" python3 -m "$@"; }

phase_ingest(){
  check_disk
  log "clear stale RUNNING ingest_run rows (controlled refresh)"
  spsql "UPDATE ingest_run SET status=4 WHERE status=2;" >/dev/null || true
  # DROP indexes BEFORE ingest. This is the big speedup: a quarter is ~200k+
  # rows and inserting with the trigram GIN indexes live takes HOURS; dropping
  # them makes the COPY fast, then we rebuild once at the end.
  log "drop salary indexes (snapshot saved)"
  sweb scripts.salary.manage_salary_indexes --drop \
    --snapshot data/index_snapshots/salary_indexes.yaml --overwrite >>"$LOG" 2>&1 || \
    log "WARN: index drop failed (continuing; ingest just slower)"
  log "discover + ingest DOL quarter (LCA/PERM/PW/Worksite)"
  sweb scripts.ingest.run_pipeline discover --domain dol >>"$LOG" 2>&1
  sweb scripts.ingest.run_pipeline discover-and-ingest --domain dol >>"$LOG" 2>&1 || \
    log "NOTE: some sources may report 'no records' (appendix files are not wage data)"
  log "recreate indexes from snapshot"
  sweb scripts.salary.manage_salary_indexes --recreate \
    --snapshot data/index_snapshots/salary_indexes.yaml >>"$LOG" 2>&1 || \
    sweb scripts.salary.manage_salary_indexes --create-clustering-indexes >>"$LOG" 2>&1
  # Post-ingest: link + cluster + stats. Order per scripts/cron/refresh/config.py
  # and job_title_coherence.md (cluster_job_titles -> stats -> slugs).
  log "post-ingest: backfill source dates"
  sweb scripts.salary.backfill_source_file_date >>"$LOG" 2>&1 || log "WARN backfill_source_file_date"
  log "post-ingest: backfill job-title links"
  sweb scripts.salary.backfill_job_title_links >>"$LOG" 2>&1 || log "WARN backfill_job_title_links"
  log "post-ingest: cluster job titles"
  sweb scripts.salary.cluster_job_titles >>"$LOG" 2>&1
  log "post-ingest: cluster employers (LONG — 30-60min+; skips already-clustered)"
  sweb scripts.salary.cluster_existing_employers >>"$LOG" 2>&1
  log "post-ingest: employer stats"
  sweb scripts.salary.update_employer_stats >>"$LOG" 2>&1 || log "WARN update_employer_stats"
  log "post-ingest: job-title cluster stats"
  sweb scripts.salary.update_job_title_cluster_stats >>"$LOG" 2>&1
  log "post-ingest: populate job-title slugs"
  sweb scripts.salary.populate_job_title_slugs >>"$LOG" 2>&1
  log "vacuum analyze"
  spsql "VACUUM ANALYZE;" >/dev/null || true
  prod_health
}

phase_verify(){
  log "spot-check: newest source file present + Q2 row counts"
  spsql "SELECT source_file, COUNT(*) FROM salary_record GROUP BY source_file ORDER BY MAX(source_file_date) DESC NULLS LAST LIMIT 8;" | tee -a "$LOG"
  log "staging home page renders?"
  docker exec "$STG_WEB" sh -c "wget -qO- -S http://localhost:8000/ 2>&1 | head -1" | tee -a "$LOG" || true
}

# GATED. Promote = swap the postgres-data volumes between prod and staging
# stacks. ~30s blip. NOT auto-run. Requires the operator to type CONFIRM.
phase_promote(){
  echo "PROMOTE will stop both stacks and swap prod<->staging postgres-data (~30s downtime)."
  echo "Pre-req: phase_verify looked correct. Prod's current DB is archived first."
  read -r -p "Type CONFIRM to proceed: " ans
  [ "$ans" = "CONFIRM" ] || { echo "aborted"; exit 1; }
  local ts; ts=$(date +%Y%m%d_%H%M%S)
  log "stopping web on both stacks"
  ( cd "$PROD_DIR" && docker compose stop web )
  ( cd "$STG_DIR" && docker compose stop web )
  log "stopping postgres on both stacks"
  ( cd "$PROD_DIR" && docker compose stop postgres )
  ( cd "$STG_DIR" && docker compose stop postgres )
  log "archiving prod postgres-data -> postgres-data.pre_$ts and swapping in staging's"
  sudo mv "$PROD_DIR/postgres-data" "$PROD_DIR/postgres-data.pre_$ts"
  sudo cp -a "$STG_DIR/postgres-data" "$PROD_DIR/postgres-data"   # copy (keep staging usable)
  log "restarting prod"
  ( cd "$PROD_DIR" && docker compose up -d postgres && sleep 8 && docker compose up -d web nginx )
  ( cd "$STG_DIR" && docker compose up -d postgres web nginx )
  sleep 5; prod_health
  log "PROMOTE done. Rollback: stop prod, mv postgres-data.pre_$ts back, restart."
}

cmd="${1:-all}"
case "$cmd" in
  reseed)   phase_reseed ;;
  ingest)   phase_ingest ;;
  verify)   phase_verify ;;
  all)      phase_reseed; phase_ingest; phase_verify; log "DONE (promote is separate + gated)";;
  promote)  phase_promote ;;
  *) echo "usage: $0 {reseed|ingest|verify|all|promote}"; exit 2 ;;
esac
log "phase '$cmd' complete. Full log: $LOG"
