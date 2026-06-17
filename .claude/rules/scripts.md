# Project Scripts and Workflows

## Rule: Use Project Scripts for Common Tasks

**ALWAYS use project scripts in `./scripts/` instead of ad-hoc commands.**

**✅ GOOD:** `./scripts/restart_server.sh` / `./scripts/deploy.sh`
**❌ BAD:** `pkill -9 -f "runserver"` / `ps aux | grep runserver | awk...` / `bazel run //:runserver`

## Rule: Use run_sql Tool for Database Queries (Never Raw psql)

**🚨 CRITICAL: ALWAYS use `bazel run //:run_sql`. NEVER fall back to raw `psql`.**

`run_sql` handles Django setup, DB connections, and env vars automatically. When it fails, debug the tool — don't bypass it.

**✅ Local:** `bazel run //:run_sql -- --query "SELECT COUNT(*) FROM salary_job_title"`
**✅ Remote:** `ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && bazel run //:run_sql -- --query 'SELECT COUNT(*)...'"`
**❌ BAD:** `ssh prod_2Gb_vm "psql -U visa_bulletin_user -d visa_bulletin -c '...'"`

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

## Rule: Remote VM Database Query Pattern

**Required pattern** (each component is critical):

```bash
ssh prod_2Gb_vm \
  "cd /opt/visa_bulletin && set -a && source .env && set +a && \
   bazel run //:run_sql -- --query 'YOUR_QUERY_HERE'"
```

- `cd` first (Bazel needs WORKSPACE), `set -a` before `source` (exports vars for subprocess), single quotes around query (prevents local shell expansion).
- Missing `set -a` = run_sql can't see env vars. This is the most common failure.

## Rule: Run restart_server.sh with --background Flag

**AI assistants:** `./scripts/restart_server.sh --background` (requires `required_permissions: ["all"]` for Bazel `/var/tmp` access). Logs to `/tmp/visa-bulletin-server.log`.

**Interactive use:** `./scripts/restart_server.sh` (foreground, live logs, Ctrl+C to stop).

## Available Scripts

| Script | Purpose | Usage |
|--------|---------|-------|
| `restart_server.sh` | Graceful dev server restart | `./scripts/restart_server.sh [--background]` |
| `setup_dev_tools.sh` | Install dev dependencies | `./scripts/setup_dev_tools.sh` |
| `deploy.sh` | Docker-based production deploy | `./scripts/deploy.sh [ssh-key-path] [image-tag]` |
| `check_cls.sh` | CLS check for SEO | `./scripts/check_cls.sh` |
| `check_debug_mode.py` | Verify DEBUG=False in prod | `bazel run //scripts:check_debug_mode` |
| `generate_favicon_png.sh` | Generate favicon variants | `./scripts/generate_favicon_png.sh` |

## SSH Access

**Aliases** (`~/.ssh/config`): `prod_2Gb_vm` (Production), `backup_0_5Gb_vm` (Backup)

```bash
ssh prod_2Gb_vm                                                    # Connect
ssh prod_2Gb_vm "cd /opt/visa_bulletin && docker-compose ps"       # Remote command
ssh prod_2Gb_vm "cd /opt/visa_bulletin && docker-compose logs -f"  # View logs
```

See `SSH_COMMANDS.md` for comprehensive examples.

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
