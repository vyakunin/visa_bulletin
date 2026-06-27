# Project Scripts and Workflows

## Rule: Use Project Scripts for Common Tasks

**ALWAYS use project scripts in `./scripts/` instead of ad-hoc commands.**

**✅ GOOD:** `./scripts/restart_server.sh` (dev) / `bazel run //:run_sql`
**❌ BAD:** `pkill -9 -f "runserver"` / `ps aux | grep runserver | awk...` / `bazel run //:runserver`

> **🚨 Releases/deploys/promotions are NOT in this `./scripts/` dir — they live in the VB
> platform repo (`~/cursor_projects/visa_bulletin_platform/hosting/`).** Never hand-roll a
> prod deploy or call a legacy `./scripts/deploy.sh`-style script for a release. The canonical
> release surfaces (`cutover.sh`, `promote.sh`, `graduate.sh`, `cf_cache_purge.py`) and the
> Path-1-vs-Path-2 decision are owned by `branching.md` + `deployment.md` + `hosting/RELEASE_PATHS.md`.
> This file covers DEV/operational scripts only.

## Rule: Use run_sql Tool for Database Queries (Never Raw psql)

**🚨 CRITICAL: ALWAYS use `bazel run //:run_sql`. NEVER fall back to raw `psql`.**

`run_sql` handles Django setup, DB connections, and env vars automatically. When it fails, debug the tool — don't bypass it.

**✅ Local:** `bazel run //:run_sql -- --query "SELECT COUNT(*) FROM salary_job_title"`
**✅ Remote (read-only prod):** `ssh homeserver "docker exec vb_postgres psql -U visa_bulletin_user visa_bulletin -c 'SELECT COUNT(*) ...'"` — prod runs Postgres in the `vb_postgres` container (no Bazel on the box). See `ground_truth.md` for the read-only prod-query posture (small box, add `LIMIT`/indexed `WHERE`).
**ℹ️ `run_sql` is the LOCAL/dev path** (it needs the Bazel WORKSPACE + a `.env`); on prod, query the container directly per the line above.

**Debugging run_sql failures:**
1. Check env vars: `ssh homeserver "cat /opt/stack/visa_bulletin/.env | grep DB_"`
2. Ensure `set -a && source .env && set +a` (not just `source .env`)
3. List tables: `bazel run //:run_sql -- --query "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"`
4. Test connection: `bazel run //:run_sql -- --query "SELECT 1"`

**Common issues:**

| Issue | Fix |
|-------|-----|
| Password auth failed | Use `set -a && source .env && set +a` |
| Table "models_*" doesn't exist | Query `pg_tables` for actual table names |
| Connection refused | Check `DB_HOST` in `.env` (use `localhost` for local PG) |
| Permission denied | Verify `DB_USER` / `DB_PASSWORD` in `.env` |

## Rule: Database Table Naming Convention

**Django model names ≠ PostgreSQL table names.** Pattern: `{app_label}_{model_name_snake_case}`. Always query actual table names first.

**✅ GOOD:** `SELECT COUNT(*) FROM salary_job_title`
**❌ BAD:** `SELECT COUNT(*) FROM models_jobtitle`

**Table mappings:**

| Django Model | PostgreSQL Table | File |
|-------------|------------------|------|
| `JobTitle` | `salary_job_title` | `models/salary.py` |
| `JobTitleCluster` | `salary_job_title_cluster` | `models/salary.py` |
| `SalaryRecord` | `salary_record` | `models/salary.py` |
| `Employer` | `salary_employer` | `models/salary.py` |
| `Bulletin` | `bulletin` | `models/bulletin.py` |
| `VisaCutoffDate` | `visa_cutoff_date` | `models/bulletin.py` |

Find table names: query `pg_tables` (fastest), check migrations for `CREATE TABLE`, or use `Model._meta.db_table`.

## Rule: Remote (prod) Database Query Pattern

**Prod runs Postgres in the `vb_postgres` Docker container on the homeserver — there is NO Bazel/`run_sql` on the prod box.** Query the container directly via the `homeserver` SSH alias (read-only; this is live-traffic state — `ground_truth.md`):

```bash
ssh homeserver "docker exec vb_postgres psql -U visa_bulletin_user visa_bulletin \
  -c 'SELECT COUNT(*) FROM salary_job_title'"
# staging DB is a SEPARATE container: vb_stg_postgres — never mix the two (ground_truth.md)
```

- **Read-only `SELECT` only.** Add `LIMIT` + indexed `WHERE` on big tables (`salary_record`, `lca_case`, `dol_case`); the box serves live traffic. Don't `EXPLAIN ANALYZE` heavy queries without telling the user first.
- The old `ssh prod_2Gb_vm "cd /opt/visa_bulletin && bazel run //:run_sql ..."` pattern is **Lightsail-era and dead** — that VM, the `/opt/visa_bulletin` path, and on-box Bazel no longer exist. See `homeserver_visa_bulletin.md` for current topology.

## Rule: Run restart_server.sh with --background Flag

**AI assistants:** `./scripts/restart_server.sh --background` (requires `required_permissions: ["all"]` for Bazel `/var/tmp` access). Logs to `/tmp/visa-bulletin-server.log`.

**Interactive use:** `./scripts/restart_server.sh` (foreground, live logs, Ctrl+C to stop).

## Available Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `restart_server.sh` | Graceful **dev** server restart | `./scripts/restart_server.sh [--background]` |
| `setup_dev_tools.sh` | Install dev dependencies | `./scripts/setup_dev_tools.sh` |
| `check_cls.sh` | CLS check for SEO | `./scripts/check_cls.sh` |
| `check_debug_mode.py` | Verify DEBUG=False in prod | `bazel run //scripts:check_debug_mode` |
| `generate_favicon_png.sh` | Generate favicon variants | `./scripts/generate_favicon_png.sh` |

> **No `deploy.sh` here.** Any Lightsail-era `./scripts/deploy.sh` is dead — production deploys/promotions go through the VB platform repo (`visa_bulletin_platform/hosting/`), never a hand-rolled script in this repo. See `branching.md` §"ALL releases go through `visa_bulletin_platform/hosting/`".

## SSH Access

**Production + staging run on the homeserver** (migrated off AWS Lightsail 2026-05-08). Use the `homeserver` SSH alias (host/user/key configured in your private `~/.ssh/config`; concrete values live in the private ops repo). The old `prod_2Gb_vm` / `backup_0_5Gb_vm` Lightsail aliases and the `/opt/visa_bulletin` path are **retired** — current paths are `/opt/stack/visa_bulletin` (prod) and the staging stack (`vb_stg_*` containers).

```bash
ssh homeserver                                                       # Connect
ssh homeserver "docker ps --format '{{.Names}} {{.Status}}'"          # Container state (vb_*)
ssh homeserver "docker logs vb_web --tail 50"                         # View web logs
```

**Before ANY container lifecycle op on prod** (`docker compose up/down/stop`, `docker stop/rm`), run the topology audit in `AGENTS.md` / `deployment.md` first. `docker pull` / `docker logs` / `docker inspect` are always safe; releases themselves go through `hosting/` (above), not raw `docker compose` on the box.

## Environment Variables

- `GITHUB_TOKEN_VYAKUNIN` (in `~/.zshrc`) — GitHub PAT. Usage: `export GITHUB_TOKEN=$GITHUB_TOKEN_VYAKUNIN`

## Note: Employer Clustering Rules

Moved to `.claude/rules/employer_clustering.md`. See also `lib/business/salary/README.md`.

## Rule: Delete Instead of Deprecate

**ALWAYS delete old code instead of deprecating.** Git history preserves old code if needed.

**Process:** Merge functionality → update all references (BUILD, docs, scripts) → delete old script → remove BUILD target → update docs.

**✅ GOOD:** `rm scripts/old_script.py` after merging
**❌ BAD:** Adding `"""DEPRECATED: Use new_script.py"""` and keeping dead code

**Deprecation acceptable only** when external systems depend on the script (give migration period).

## Rule: Always Search for Existing Scripts Before Creating New Ones

See `general_script_development.md` for full details. Summary:

1. Search codebase and `scripts/README.md` for similar functionality
2. Prefer extending existing scripts with new flags over creating new ones
3. Create new only if functionality is fundamentally different (different category/purpose)

## Rule: Always Document New Scripts

See `general_script_development.md` for full details. Summary:

**Every script needs:** docstring (purpose, usage, flags), BUILD target, entry in `scripts/README.md` (permanent), script usage logging (`ScriptLogger` for permanent, `log_context()` for one-off).

**Temporary scripts:** docstring + `log_context()` + place in `scripts/oneoff/`.

## Documentation Files

`README.md` | `CONTRIBUTING.md` | `BAZEL.md` | `DOCKER_DEPLOYMENT.md` | `MIGRATION_TO_DOCKER.md` | `scripts/README.md` (comprehensive script docs)
