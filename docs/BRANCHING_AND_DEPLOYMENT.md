# Branching Strategy and Deployment Workflow

> ⚠️ **PARTIALLY RETIRED (2026-06-20).** The **branch model** (main → staging → prod)
> is still current. But the **deployment mechanics** described below — AWS/Lightsail
> blue/green **graduation**, static-IP **traffic switch**, instance start/stop — are
> **retired**: that orchestrator (`refresh_and_switch.py` + `instance/traffic_switch/
> orchestrate`) was deleted when prod moved to a self-hosted homeserver behind a
> Cloudflare Tunnel. The **current, canonical** branch + deploy model is
> `.claude/rules/branching.md` + `.claude/rules/deployment.md` (image-tag promotion:
> `docker compose pull web && up -d web`) and `deployment/homeserver/`. Treat the
> graduation/static-IP sections here as historical until this doc is rewritten to the
> homeserver model (ticket 36662b8d).

Canonical reference for how code moves from development to production. Covers branch strategy, separation of concerns (code deploy vs data refresh vs graduation), and operational procedures.

For pipeline-specific operational details (step timeouts, failure modes, resuming), see [PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md).

---

## Branches

Three long-lived branches:

| Branch | Purpose | Volatility |
|--------|---------|------------|
| `main` | Development. WIP, experimental, can be broken. | High — changes frequently |
| `staging` | Release candidate. Real server, real data testing. Data refreshes run here. | Medium — patched until ready |
| `prod` | **Mirror of production. NEVER update unless the change is deployed to prod.** | Low — graduations and critical hotfixes only |

**`main`** is the development workspace. Features are built here, tests run locally, code can be incoherent. Nothing deploys from `main` directly.

**`staging`** accepts cherry-picks from `main`. It gets deployed to the staging instance for end-to-end validation with real data. Data refreshes (orchestrator pipeline) run against the staging instance. `staging` can be patched many times before it's deemed ready. **All features and non-critical fixes go through `staging`, never directly to `prod`.**

**`prod`** is a strict mirror of what's running on the production-serving instance. It must always reflect exactly what's deployed. Updated only in two cases:
- **Graduation**: staging proven stable → IP flip → `prod` branch fast-forwards to match `staging`
- **Critical hotfix**: 5xx errors, crashes, production-down situations — fix on `main`, cherry-pick to `prod`, deploy directly to the prod-serving instance, then cherry-pick to `staging`

**`prod` is NEVER updated for:** features, non-critical fixes, orchestrator scripts, or any code that isn't actually deployed to the prod-serving instance. If it's not running in production, it doesn't belong on the `prod` branch.

---

## Two Instances, Two Static IPs

| Instance | SSH Alias | IP | RAM |
|----------|-----------|-----|-----|
| Instance A | `prod_2Gb_vm` | 44.209.204.255 | 2GB |
| Instance B | `staging_2Gb_vm` | 54.196.241.197 | 2GB |

Each instance runs: one PostgreSQL database (`visa_bulletin`), one app stack (`deployment/docker-compose.yml`, web + redis on port 8000), nginx proxying port 80 to 8000.

One instance holds the **production static IP** (serves live traffic). The other holds the **staging static IP** (testing/refresh). Which instance is which **swaps on each graduation**.

**AWS instance names are sticky** (VisaBulletin2GB, VisaBulletinStaging do not change). SSH aliases are keyed by **IP**: `prod_2Gb_vm` = prod static IP, `staging_2Gb_vm` = staging static IP. After a successful graduation, the instance that had the staging IP gets the prod IP (becomes prod), and the instance that had the prod IP gets the staging IP (becomes staging) and is **stopped** by the orchestrator. So after rotation: prod_2Gb_vm connects to the old staging instance (e.g. VisaBulletinStaging); staging_2Gb_vm connects to the old prod instance (e.g. VisaBulletin2GB), which is typically **stopped** and unreachable until the next pipeline. Verify with `aws lightsail get-static-ips` and `get-instance` / `get-instance-state`.

---

## Local Worktree Layout

**The Cursor IDE workspace (`~/cursor_projects/visa_bulletin/`) always stays on `main`.** This ensures `.cursor/rules/` and `AGENTS.md` are always available to the AI assistant. Separate git worktrees provide access to `staging` and `prod` branches without switching the IDE workspace.

```
~/cursor_projects/
  visa_bulletin/           ← main (Cursor workspace — always open here)
  visa_bulletin_staging/   ← staging worktree (git worktree)
  visa_bulletin_prod/      ← prod worktree (git worktree)
```

### Setup (one-time)

```bash
cd ~/cursor_projects/visa_bulletin
git worktree add ../visa_bulletin_staging staging
git worktree add ../visa_bulletin_prod prod
```

### Usage

Cherry-pick, merge, and push from worktree directories. The IDE workspace stays on `main`.

```bash
# Cherry-pick to staging
cd ~/cursor_projects/visa_bulletin_staging
git cherry-pick <commit-hash>
git push origin staging

# Cherry-pick to prod (hotfix)
cd ~/cursor_projects/visa_bulletin_prod
git cherry-pick <commit-hash>
git push origin prod

# Fast-forward prod after graduation
cd ~/cursor_projects/visa_bulletin_prod
git merge staging
git push origin prod
```

### Why worktrees?

`.cursor/rules/` (AI safety rules, deployment rules, code style) only exists on `main`. If the IDE workspace checks out `staging` or `prod`, the AI loses all safety guardrails. Worktrees solve this by keeping each branch in a separate directory — the IDE never leaves `main`.

### Maintenance

```bash
# List worktrees
git worktree list

# Pull latest in a worktree (before cherry-picking)
cd ~/cursor_projects/visa_bulletin_staging && git pull origin staging

# Remove a worktree (if needed)
git worktree remove ../visa_bulletin_staging
```

---

## Separation of Concerns

Three independent operations. Each has its own trigger, workflow, and scope.

### 1. Code Deployment

Push a git branch to an instance. No data refresh involved.

**Trigger**: developer pushes commits to `staging` or `prod` branch and wants them on the corresponding instance.

**Mechanism**: SSH to instance, `git pull` the correct branch, rebuild Docker image or restart container.

**Scope**: code files only. Database, data, `.env` are untouched.

### 2. Data Refresh

Orchestrator pipeline ingests new data, runs post-processing (clustering, stats, slugs), and validates results.

**Trigger**: new data available from DOL/State Dept sources (eventually cron-automated).

**Where it runs**: the orchestrator binary runs on the **prod host** (Bazel-built, not Docker) and drives all pipeline steps on the **staging host** remotely via SSH. The pipeline (see [PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md)) handles: code sync (git pull on staging), DB migrations, ingest, post-processing, smoke tests.

**Scope**: database content. Code is synced as a prerequisite (step_sync_code), not as the primary goal.

### 3. Graduation (IP Flip)

Staging instance is proven stable (code + data). Swap static IPs so staging becomes prod and prod becomes staging.

**Trigger**: manual decision after validating staging works end-to-end.

**Mechanism**: Lightsail static IP reassignment (see [IP Flip Procedure](#ip-flip-procedure)).

**Post-flip**: update `prod` branch to match `staging`, bring the new staging instance (ex-prod) up to date.

---

## Workflows

### Feature Development

```
main (develop) --> staging (cherry-pick) --> staging instance (deploy + test)
                                                    |
                                              iterate until ready
```

1. Develop on `main`, test locally with `bazel test //tests:...`
2. Cherry-pick ready commits to `staging` via worktree: `cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <commits>`
3. Push: `git push origin staging`
4. Deploy `staging` branch to the staging instance (code deployment)
5. Test on staging IP — verify with real data, end-to-end
6. If issues: fix on `main`, cherry-pick to `staging` worktree, re-deploy. Repeat.

### Graduation (Staging to Prod)

Graduation is automated by the orchestrator. Run it on the **current prod instance** with `--from-step warm_cache` (skips the data pipeline, jumps straight to graduation).

```
orchestrator on prod --> warm cache on inactive
                     --> smoke test on inactive (DB + HTTP)
                     --> [GATE: if smoke fails, STOP - nothing irreversible happened]
                     --> swap static IPs (inactive becomes new prod)
                     --> [from here, orchestrator is on staging since IPs swapped]
                     --> HTTPS setup on new prod (certbot)
                     --> smoke test via public URL (visa-bulletin.us)
                     --> update .env on new prod (swap active/inactive roles)
                     --> update .env on orchestrator/new staging (swap roles)
                     --> staging IP reassign to old prod
                     --> prod-safe override (drop volume mount, restart container)
                     --> git branch update (push prod=staging; new prod checks out prod; staging instance checks out prod branch — after health checks, before stop)
                     --> safety interval
                     --> stop old instance (orchestrator's machine, now staging)
```

**To run graduation:**

```bash
# On prod instance (where orchestrator runs):
cd /opt/visa_bulletin && set -a && source .env && set +a
./bazel-bin/scripts/cron/refresh_and_switch --from-step warm_cache --safety-interval 600
```

**Key flags:**
- `--from-step warm_cache`: start from cache warming (skip full pipeline)
- `--from-step smoke_tests`: start from smoke tests (skip cache warming)
- `--from-step traffic_switch`: skip directly to IP swap
- `--safety-interval N`: seconds to wait after swap before stopping old instance (default 1800)

**What happens at each step:**

1. **Warm cache**: pre-populates Redis cache (market overview, directories, page caches) on the inactive instance
2. **Smoke tests**: verifies DB health (record counts, clustering, slugs) and HTTP endpoints (homepage, autocomplete, directories) on the inactive instance via localhost
3. **IP swap**: detaches prod static IP from current prod, attaches to inactive — traffic now flows to new prod. **This is the irreversible point.** All subsequent steps are non-fatal (warnings only).
4. **HTTPS setup**: runs certbot on new prod so SSL works
5. **Public URL smoke**: curls `https://visa-bulletin.us/` to verify end-to-end
6. **Env update (both)**: swaps `REFRESH_ACTIVE_*` / `REFRESH_INACTIVE_*` on both instances so the next cycle knows which is which
7. **Staging IP reassign**: gives the old prod a stable staging IP for access
8. **Prod-safe override**: replaces `docker-compose.override.yml` (drops volume mount), restarts container to use baked-in Docker image code
9. **Git branch update**: Pushes `prod` branch to match `staging` on origin; new prod checks out `prod` branch (no reload — same code); **then** staging instance (orchestrator host, old prod) fetches and checks out `prod` branch — so `origin/prod` = what prod runs, and staging has `prod` checked out before it is stopped.
10. **Safety interval**: waits to detect issues before shutting down
11. **Stop old instance**: stops the orchestrator's machine (now staging) via AWS API

**Post-rotation checks** (verify both hosts are consistent after graduation):

| Check | Prod (prod_2Gb_vm) | Staging (staging_2Gb_vm) |
|-------|--------------------|--------------------------|
| **.env** | `REFRESH_MY_INSTANCE_NAME` = this instance (e.g. VisaBulletinStaging); `REFRESH_ACTIVE_*` = this instance; `REFRESH_INACTIVE_*` = the other; `REFRESH_STATIC_IP_NAME` and `REFRESH_STAGING_STATIC_IP_NAME` set | `REFRESH_MY_INSTANCE_NAME` = this instance (e.g. VisaBulletin2GB); `REFRESH_ACTIVE_*` = prod instance; `REFRESH_INACTIVE_*` = this instance |
| **Git** | `origin/prod` = code running on prod; this host has `prod` branch checked out | This host has `prod` branch checked out (orchestrator switched it after health checks, before stop) |
| **Static IP** | Prod static IP attached to this instance | Staging static IP attached to this instance |

**Git branch consistency:** The `prod` branch on origin points to what the prod container is running (the old staging branch content after the push). The new prod host checks out `prod`. The staging instance (old prod) is updated to `prod` branch **after** health checks pass and **before** the orchestrator stops it — so when staging is started again for the next pipeline, it has `prod` checked out until the pipeline syncs it to `staging`.

**Manual graduation** (if the orchestrator isn't available):

1. Verify staging is stable (smoke tests pass, manual verification)
2. Tag on `staging` branch: `git tag -a v1.X.Y -m "Release 1.X.Y: ..."`
3. Push tag: `git push origin v1.X.Y`
4. IP flip: swap static IPs (see [IP Flip Procedure](#ip-flip-procedure))
5. Verify production responds at `https://visa-bulletin.us/`
6. Fast-forward `prod` via worktree: `cd ~/cursor_projects/visa_bulletin_prod && git reset --hard origin/staging && git push origin prod --force-with-lease`
7. Replace override on new prod (see orchestrator's `_write_prod_safe_override`)
8. Update `.env` on both instances (swap active/inactive roles)

After graduation, both instances have their roles swapped. Next cycle starts with new development on `main`.

### Critical Hotfix (Prod Bug)

For crashes, 5xx errors, or other critical production issues:

1. Fix the bug on `main` (where the IDE and rules live), commit
2. Cherry-pick to `prod` via worktree: `cd ~/cursor_projects/visa_bulletin_prod && git cherry-pick <fix-hash> && git push origin prod`
3. Deploy `prod` branch to the **production-serving instance** (SSH, git pull, restart container)
4. Verify the fix
5. Cherry-pick to `staging` worktree: `cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <fix-hash> && git push origin staging`

Hotfixes go to `prod` first, then propagate back. You fix what's serving traffic, then bring other branches up to date.

### Data Refresh (No Code Change)

1. Orchestrator runs on the **prod host** (Bazel binary, not Docker) and drives the pipeline on the **staging host** via SSH
2. Pipeline handles: code sync (git pull on staging), ingest, post-processing, smoke
3. After success on staging: graduation flow (IP flip) to promote fresh data to prod

See [PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md) for pipeline steps, failure modes, and resuming.

### Orchestrator Hotfix (Pipeline or Script Fix)

For **critical** fixes to the orchestrator or data-processing scripts that need to be deployed to the prod host during an active pipeline run. This is a form of prod hotfix — only use when the pipeline is broken and needs an immediate fix on the prod host.

**Which files are safe?** `scripts/cron/refresh/`, `scripts/salary/`, `scripts/ingest/`, `scripts/cache/`, `scripts/oneoff/`, build files (`BUILD`, `MODULE.bazel`, `build_all.sh`). For `lib/` files, verify gunicorn doesn't import them: `rg "from lib.the_module" webapp/ models/`.

```
1. Fix on main, cherry-pick to prod via worktree:
   cd ~/cursor_projects/visa_bulletin_prod && git cherry-pick <hash> && git push origin prod
2. ssh prod_2Gb_vm "cd /opt/visa_bulletin && git fetch origin prod && git reset --hard origin/prod"
3. ssh prod_2Gb_vm "cd /opt/visa_bulletin && bazel build //scripts/cron:refresh_and_switch && bazel shutdown"
4. Resume/re-run orchestrator with the updated binary
5. Cherry-pick to staging worktree:
   cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging
```

**Important:** This follows the same principle — `prod` branch is only updated when the code is actually deployed to the prod host. Non-critical script fixes should go through `staging` and wait for the next graduation.

The web container is untouched — gunicorn never imports script files. The next orchestrator run syncs the fixed code to staging automatically via `step_sync_code` (git pull).

**When NOT to use this path:** if the change also touches `webapp/`, `models/`, `django_config/`, or templates. Use the staging graduation path instead. See [Which Deployment Path?](#which-deployment-path) below.

---

## IP Flip Procedure

### Prerequisites

- Both instances are running and healthy
- The staging instance has been validated (smoke tests, manual checks)
- You know which instance currently holds the production static IP

### Check Current State

```bash
export AWS_PROFILE=visa-bulletin-deploy
aws lightsail get-static-ips --region us-east-1
```

### Swap Static IPs

```bash
export AWS_PROFILE=visa-bulletin-deploy

# Detach production IP from current prod instance
aws lightsail detach-static-ip --static-ip-name <prod-static-ip-name> --region us-east-1

# Attach production IP to staging instance (making it the new prod)
aws lightsail attach-static-ip --static-ip-name <prod-static-ip-name> \
  --instance-name <staging-instance-name> --region us-east-1

# If using a second static IP for staging, swap it too:
aws lightsail detach-static-ip --static-ip-name <staging-static-ip-name> --region us-east-1
aws lightsail attach-static-ip --static-ip-name <staging-static-ip-name> \
  --instance-name <old-prod-instance-name> --region us-east-1
```

### Verify

```bash
curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us
ssh <new-prod-alias> "docker ps | grep visa_bulletin_web"
```

### Rollback

If something is wrong after the flip, reverse the IP assignments:

```bash
aws lightsail detach-static-ip --static-ip-name <prod-static-ip-name> --region us-east-1
aws lightsail attach-static-ip --static-ip-name <prod-static-ip-name> \
  --instance-name <old-prod-instance-name> --region us-east-1
```

IP reassignment is near-instant. No DNS propagation delay.

---

## Code Deployment Procedure

Deploy a specific branch to a specific instance. No data refresh, no IP flip.

### Deploy to Staging Instance

```bash
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git fetch origin staging && git checkout staging && git reset --hard origin/staging"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

# Verify
curl -s -o /dev/null -w "%{http_code}" http://<staging-ip>/
```

### Deploy to Production Instance (Hotfix)

```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git fetch origin prod && git checkout prod && git reset --hard origin/prod"
ssh prod_2Gb_vm "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

# Verify
curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us/
```

### When Docker Image Rebuild Is Needed

If the change affects dependencies (requirements.txt), Dockerfile, or static assets baked into the image:

1. Push the branch + tag
2. GitHub Actions builds the image
3. On the instance: `IMAGE_TAG=<tag> docker-compose -f deployment/docker-compose.yml pull && docker-compose -f deployment/docker-compose.yml up -d`

For code-only changes where the existing image + volume-mounted code is sufficient, `git pull + restart` is enough.

---

## Key Rules

### Never scp files to servers

All code changes go through git. Commit to the appropriate branch (`staging` or `prod`), push, then `git pull` on the server. This ensures the branch always reflects what's deployed.

The scp + volume mount pattern was a historical workaround that caused drift between what's in git and what's running on servers. It is **deprecated**.

### Branches are source of truth (use worktrees)

- View `prod` via `~/cursor_projects/visa_bulletin_prod/` — exactly what's in production
- View `staging` via `~/cursor_projects/visa_bulletin_staging/` — what's on the staging instance
- `git log prod` shows the full history of what was deployed
- `git diff staging prod` shows what's different between environments
- **Never check out staging/prod in the main workspace** — use worktrees to preserve AI rules

### `prod` branch is sacred — mirror of production only

- **NEVER** cherry-pick features or non-critical fixes to `prod`
- **NEVER** update `prod` unless the code is actually deployed to the prod-serving instance
- Only two operations touch `prod`: graduation (fast-forward from `staging`) and critical hotfixes (deployed directly)
- If you're unsure, the answer is: go through `staging` first

### Tags mark production releases

Every graduation gets a tag on `staging` before the IP flip: `v1.X.Y`. Tags on `prod` after fast-forward mark the same commits. If you need to know what's in production, check the latest tag on `prod`.

---

## Which Deployment Path?

| Changed files | Path | Deploy to |
|---|---|---|
| `scripts/` or build files only | Orchestrator hotfix | Prod (git pull + bazel build) |
| `webapp/`, `models/`, `django_config/`, templates | Staging graduation | Staging (git pull + restart + IP flip) |
| `lib/` imported only by scripts | Orchestrator hotfix | Prod (verify: `rg "from lib.the_module" webapp/ models/`) |
| `lib/` imported by Django views/models | Staging graduation | Staging |
| Mixed (both orchestrator and serving) | Split commits, or staging graduation | Staging if unsplit |
| Not sure | Staging graduation | Always safe |

**Why the separation matters:** the orchestrator is a Bazel binary running on the host. The web app is a Docker container (gunicorn). They share a git repo on disk but are independent processes. Gunicorn never imports `scripts/`. After post-graduation override cleanup (no volume mount), `git pull` on prod is invisible to the Docker container.

---

## Transition from Current State (Completed 2026-02-19)

One-time steps that were executed to move from the old workflow (everything on `main`, scp patches, drift) to the branch-based workflow. Kept for reference; git history preserves the detailed commands.

### Step 1: Commit all local WIP

Preserve everything locally — broken views, experimental features, all of it. This creates a snapshot you can cherry-pick from later.

```bash
cd /Users/vyakunin/cursor_projects/visa_bulletin

# Create a WIP branch from current HEAD
git checkout -b wip/pre-cleanup

# Stage everything (tracked changes + untracked files)
git add -A

# Commit
git commit -m "WIP: snapshot of all local work before branch cleanup"

# Push to remote so it's preserved
git push origin wip/pre-cleanup

# Go back to main
git checkout main
```

### Step 2: Capture production state, create `prod` branch

Find out exactly what commit + patches are running on the production-serving instance. Create the `prod` branch from that state.

```bash
# 1. Check what commit prod is on
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git log -1 --oneline"

# 2. Check for uncommitted changes (scp patches, local edits)
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git status"
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git diff HEAD --stat"

# 3. If there are diffs, save them to a patch file
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git diff HEAD" > /tmp/prod_patches.diff

# 4. Check if the ../:/app volume mount hack is active
ssh prod_2Gb_vm "grep -n '\\.\\./:/app' /opt/visa_bulletin/deployment/docker-compose.yml || echo 'No volume mount hack found'"
# Also check for override file
ssh prod_2Gb_vm "cat /opt/visa_bulletin/deployment/docker-compose.override.yml 2>/dev/null || echo 'No override file'"

# 5. Create prod branch locally from the same commit
PROD_COMMIT=$(ssh prod_2Gb_vm "cd /opt/visa_bulletin && git rev-parse HEAD")
echo "Prod is on commit: $PROD_COMMIT"

git checkout -b prod $PROD_COMMIT

# 6. If prod had patches (step 3 produced a non-empty diff), apply them
#    Review the diff first — skip anything that shouldn't be permanent
cat /tmp/prod_patches.diff  # review
git apply /tmp/prod_patches.diff  # apply (use --reject if some hunks fail)
git add -A
git commit -m "Apply production patches (captured from prod_2Gb_vm)"

# 7. Tag this as the baseline production state
git tag -a v-baseline-prod -m "Baseline: production state before branch cleanup"

# 8. Push
git push origin prod
git push origin v-baseline-prod
```

**If prod has the `../:/app` volume mount**: the Docker container is serving files from disk, not from the Docker image. The branch must match what's on disk (which is what we captured above). After the transition, the mount should be removed (Step 6).

### Step 3: Capture staging state, create `staging` branch

Same process for the staging instance. Staging may be in a different state (different patches, different commit).

```bash
# 1. Check staging commit and patches
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git log -1 --oneline"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git status"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git diff HEAD --stat"

# 2. Save patches
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git diff HEAD" > /tmp/staging_patches.diff

# 3. Check volume mount / override
ssh staging_2Gb_vm "grep -n '\\.\\./:/app' /opt/visa_bulletin/deployment/docker-compose.yml || echo 'No volume mount hack'"
ssh staging_2Gb_vm "cat /opt/visa_bulletin/deployment/docker-compose.override.yml 2>/dev/null || echo 'No override file'"

# 4. Create staging branch
STAGING_COMMIT=$(ssh staging_2Gb_vm "cd /opt/visa_bulletin && git rev-parse HEAD")
echo "Staging is on commit: $STAGING_COMMIT"

# If staging and prod are on the same commit, branch from prod
# If different, branch from the staging commit
git checkout -b staging $STAGING_COMMIT

# 5. Apply staging patches if any
cat /tmp/staging_patches.diff  # review
git apply /tmp/staging_patches.diff 2>/dev/null
git add -A
git commit -m "Apply staging patches (captured from staging_2Gb_vm)" --allow-empty

# 6. Push
git push origin staging
```

**Decision point**: if staging is significantly behind prod or has conflicting patches, you may want to start `staging` from `prod` (same baseline) and cherry-pick any staging-only changes. The goal is that `staging` is at least as current as `prod`.

### Step 4: Point servers to their branches

Now that the branches exist on the remote, point each server to track its branch instead of `main`.

```bash
# Production: switch to prod branch
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git fetch origin && git checkout prod && git reset --hard origin/prod"

# Staging: switch to staging branch
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git fetch origin && git checkout staging && git reset --hard origin/staging"
```

Verify:
```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git branch --show-current"
# Should output: prod

ssh staging_2Gb_vm "cd /opt/visa_bulletin && git branch --show-current"
# Should output: staging
```

### Step 5: Update GitHub Actions triggers

Current `.github/workflows/docker-build-push.yml` triggers on push to `main` and version tags. Change to trigger on `staging`, `prod`, and tags.

```yaml
on:
  push:
    branches:
      - staging
      - prod
    tags:
      - 'v*.*.*'
```

Update the SHA tag prefix to reflect the branch:
```yaml
tags: |
  type=semver,pattern={{version}}
  type=semver,pattern={{major}}.{{minor}}
  type=semver,pattern={{major}}
  type=raw,value=latest,enable=${{ github.ref == 'refs/heads/prod' }}
  type=sha,prefix={{branch}}-,enable=${{ !startsWith(github.ref, 'refs/tags/') }}
```

This means:
- Push to `prod` builds an image tagged `latest` + `prod-<sha>`
- Push to `staging` builds `staging-<sha>`
- Tags build `v1.2.3`, `v1.2`, `v1`
- Push to `main` does NOT build an image (it's the dev dumpster)

Commit this change to `main`, then cherry-pick to `staging` and `prod`.

### Step 6: Remove volume mount hack from servers

Check both servers and clean up any `../:/app` volume mount or override files.

```bash
# Production
ssh prod_2Gb_vm "grep -n '\\.\\./:/app' /opt/visa_bulletin/deployment/docker-compose.yml"
# If found, the line needs to be removed from the compose file on the server.
# Since prod branch is now the source of truth, fix the compose file in the prod branch,
# push, and git pull on the server.

# Also check for override file (created by orchestrator step_sync_code)
ssh prod_2Gb_vm "ls -la /opt/visa_bulletin/deployment/docker-compose.override.yml 2>/dev/null"
# If present and contains ../:/app mount, remove it:
ssh prod_2Gb_vm "rm -f /opt/visa_bulletin/deployment/docker-compose.override.yml"

# Restart container to use Docker image code (not disk files)
ssh prod_2Gb_vm "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

# Verify
curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us/
```

```bash
# Staging — same check
ssh staging_2Gb_vm "grep -n '\\.\\./:/app' /opt/visa_bulletin/deployment/docker-compose.yml"
ssh staging_2Gb_vm "ls -la /opt/visa_bulletin/deployment/docker-compose.override.yml 2>/dev/null"
# On staging, the override may be needed by the orchestrator (step_sync_code creates it).
# Leave it for now if the orchestrator pipeline is actively running.
# When the orchestrator is updated to use the branch-based workflow, this can be removed.
```

**Important**: removing the volume mount on prod means the Docker container serves what's baked into the image. If the image is stale (built from old `main`), you'll need to rebuild it from the `prod` branch first (Step 5 sets up the GitHub Actions trigger for this). Sequence: push `prod` branch -> GitHub Actions builds image -> pull image on prod -> restart.

### Step 7: Deprecate `scripts/deploy.sh`

The current `deploy.sh` is outdated (pulls from `main`, assumes Docker-first workflow). The code deployment procedure is now: git pull the correct branch + restart container.

Options:
- **Option A**: Delete `deploy.sh` and its BUILD target. Code deployment is documented in this file and in `.cursor/rules/branching.mdc`.
- **Option B**: Rewrite as a thin wrapper around the git pull + restart workflow, taking branch and instance as params.
- **Option C**: Leave as-is with a deprecation notice. Remove later.

If rewriting (Option B), the script would look like:

```bash
#!/bin/bash
# Deploy a branch to an instance. Code-only, no data refresh.
# Usage: ./scripts/deploy.sh <instance-alias> [branch]
#   instance-alias: prod_2Gb_vm or staging_2Gb_vm
#   branch: defaults to matching environment (prod_2Gb_vm -> prod, staging_2Gb_vm -> staging)

set -e
INSTANCE="${1:?Usage: deploy.sh <instance-alias> [branch]}"
# Auto-detect branch from instance name
if [ -z "$2" ]; then
  case "$INSTANCE" in
    *prod*) BRANCH="prod" ;;
    *staging*) BRANCH="staging" ;;
    *) echo "Cannot auto-detect branch for $INSTANCE. Provide branch as second arg."; exit 1 ;;
  esac
else
  BRANCH="$2"
fi

echo "Deploying branch '$BRANCH' to $INSTANCE..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && git fetch origin $BRANCH && git checkout $BRANCH && git reset --hard origin/$BRANCH"
echo "Restarting web container..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"
echo "Verifying..."
ssh "$INSTANCE" "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml ps"
echo "Done."
```

### Step 8: Verify the transition

After all steps, confirm the new state:

```bash
# Local: branches exist
git branch -a | grep -E 'prod|staging|main'

# Servers are on correct branches
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git branch --show-current && git log -1 --oneline"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git branch --show-current && git log -1 --oneline"

# No volume mount hack on prod
ssh prod_2Gb_vm "grep '\\.\\./:/app' /opt/visa_bulletin/deployment/docker-compose.yml && echo 'WARNING: volume mount still present' || echo 'OK: no volume mount'"

# Prod is serving traffic
curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us/

# GitHub Actions is configured for staging/prod branches (check workflow file)
git show main:.github/workflows/docker-build-push.yml | grep -A3 'branches:'
```

### Transition Checklist (Completed 2026-02-19)

- [x] Local WIP committed to `wip/pre-cleanup` and pushed
- [x] `prod` branch created from production server state, pushed (tagged `v-baseline-prod`)
- [x] `staging` branch created from staging server state, pushed
- [x] Production server tracking `prod` branch
- [x] Staging server tracking `staging` branch
- [x] GitHub Actions triggers updated (staging/prod, not main)
- [x] Volume mount hack removed from production server (none existed; staging override rewritten without volume mount)
- [x] `deploy.sh` rewritten (Option B: thin git pull + restart wrapper)
- [x] Both servers verified healthy after changes
- [x] Team (future agents) can discover the workflow via `.cursor/rules/branching.mdc`

**Note**: Production is currently served by the legacy `visa_bulletin_web_blue` container (from the old blue-green setup) with a `/opt/visa_bulletin:/app` volume mount. A `visa_bulletin_redis_fix` container provides the `redis` Docker network alias. This will be cleaned up during the next graduation (IP flip), when the prod instance gets a clean Docker setup from the staging branch's compose file.

---

## Tradeoffs

### Why three branches, not two?

Without `prod`, you can't check out "what's in production" locally. After an IP flip, the `staging` branch immediately starts accepting new patches for the next cycle. The `prod` branch provides a stable snapshot that only moves on graduation or hotfix.

### Why IP flip instead of deploy-to-prod?

- Zero downtime: traffic switches instantly, no container restart on the serving instance
- Instant rollback: flip IPs back
- Clean testing: staging instance is tested with real data before promotion
- Separation: orchestrator runs on prod as a Bazel binary (not Docker), data refresh targets staging, never disrupts production serving

### Why separate code deploy from data refresh?

The orchestrator pipeline (PIPELINE_RUNBOOK.md) is a heavy operation (hours) that includes code sync as a side effect. For quick code fixes, you need a lightweight path: commit, push, pull, restart. Conflating the two leads to either skipping testing or slow iteration.

---

## Docker Safety on Production

### Never touch Docker containers without auditing first

**Before ANY `docker-compose`, `docker stop`, or `docker rm` on prod:**

```bash
# 1. What containers exist?
docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'

# 2. What's actually serving on port 8000?
ss -tlnp | grep 8000

# 3. Which containers share the Docker network?
docker network inspect deployment_default --format '{{range .Containers}}{{.Name}} {{end}}'
```

**Why this matters:** Production may have legacy containers (from old blue-green setup, manual runs, etc.) that are the *actual* serving containers but aren't managed by the current `docker-compose.yml`. These containers rely on Docker DNS — stopping ANY container on the shared network (including redis) can break hostname resolution for the serving container.

### Safe vs dangerous operations

| Operation | Risk | Notes |
|-----------|------|-------|
| `docker pull` | None | Downloads image only |
| `docker logs`, `docker inspect` | None | Read-only |
| `docker-compose restart web` | Low | Restarts named service only |
| `docker restart <container>` | Low | Restarts specific container |
| `docker-compose up -d` | **High** | May recreate/stop other containers |
| `docker-compose down` | **Critical** | Stops ALL project containers |
| `docker stop/rm` any container | **High** | May break DNS for dependent containers |

### Incident: 2026-02-19 prod outage (~3 min)

During the branch transition, `docker-compose up -d` was run on prod to pull a new image. This recreated the `visa_bulletin_redis` container, but the port was occupied by a standalone redis. The actual serving container (`visa_bulletin_web_blue`, a legacy blue-green container) depended on the Docker `redis` hostname for cache. Stopping redis broke DNS → 500 errors.

**Fix**: started a new redis container on the same Docker network with the `redis` alias.

**Lesson**: always audit the full container topology before touching Docker on prod. The serving container may not be the one you expect.
