# Branching and Deployment Strategy

> Concrete hosting topology (hosts, IPs, hardware, the staging/standby/cutover mechanics, backup wiring, DR) lives in the private ops repo, not in this public repository. Public docs use abstract roles (production / staging / data-pipeline server). The 3-branch model below is host-agnostic.

**Canonical reference:** `docs/BRANCHING_AND_DEPLOYMENT.md`.

## Three Branches

- **`main`** — Development. Can be messy, broken, WIP. Nothing deploys from `main`.
- **`staging`** — Release candidate. Cherry-picks from `main`. Deployed to the staging stack. Data refreshes run here.
- **`prod`** — **Mirror of production. NEVER update unless the change is actually deployed to production.** Updated only in two cases: (1) promotion — fast-forward to match `staging` after staging is verified, (2) critical hotfix — fix deployed directly. The branch must always reflect exactly what's running.

## Separation of Concerns

Three independent operations — never conflate them:

- **Code deployment**: `docker compose pull web && docker compose up -d web` on the server against the stack you're deploying to. No data refresh.
- **Data refresh**: weekly job that ingests new salary/bulletin data, run against the staging DB.
- **Promotion (staging → prod)**: either (a) deploying the staging-tested image tag to the prod stack, or (b) atomically swapping the postgres-data volumes (for DB-level promotion after a refresh).

## Which release path — rendering vs data-population

Before promoting, classify the change. **Any "yes" → Path 2 (data-refresh graduation), not a Path 1 image swap:**

- Schema migration, data-format change, index drop/rebuild, or heavyweight reprocessing?
- **Changes HOW DATA IS POPULATED** — the ingest pipeline, clustering, stats/`updated_at` population, anything under `lib/ingest/`, `scripts/salary/`, `scripts/cron/` that writes or derives data?

All "no" (pure rendering/view/template/SEO/copy/config) → **Path 1** (image-tag swap: `staging` image → `prod` image, no DB touch).

- **`no schema migration` ≠ Path 1.** A data-population code change is Path 2 *even with no migration* and *even though the new code sits inert in the prod image until a refresh runs it* — validating it requires running the refresh against real data on the off-prod staging stack and checking the derived data + downstream effects, then graduating the DATA via the cutover. A quick Path 1 swap skips that and leaves the next refresh running unvalidated pipeline code at prod scale.
- **A mixed batch is Path 2.** If even one commit in the promote set touches data-population, the whole promotion is Path 2 — or split the batch and ship only the pure-rendering commits via Path 1.

## Staging runs OFF the prod box — always

The production server is resource-constrained (it serves live load); a co-resident staging stack competes with prod for CPU/RAM on *every* release, not just heavy ones. **Staging belongs on a separate box (the data-pipeline/staging server), never on the prod-serving host.** A staging stack currently co-resident with prod is a stopgap to retire, not the design. Concrete topology + the cutover engine: the private ops repo (`visa_bulletin_platform/hosting/RELEASE_PATHS.md`).

## Workflows (Summary)

**Feature:** `main` → cherry-pick to `staging` → deploy to staging stack → test → iterate. **Never to `prod`.**

**Promotion:** verify staging → fast-forward `prod` from `staging` → on the production server `cd /opt/stack/visa_bulletin_prod && IMAGE_TAG=<tag> docker compose pull web && docker compose up -d web`.

**Hotfix (critical prod issue only):** fix on `main` → cherry-pick to `prod` → deploy to prod stack → cherry-pick to `staging`. **Only for crashes/5xx — not for features or non-critical fixes.**

**Data refresh:** reset staging DB from prod → run refresh pipeline against staging → smoke staging → atomic flip (swap postgres-data volumes between prod and staging stacks). See `deployment.md` "Weekly DB Refresh Pattern".

## Local Worktree Layout

**The working copy always stays on `main`** so AI rules (`.claude/rules/`) are always available. Separate git worktrees handle `staging` and `prod` branches.

```
~/cursor_projects/
  visa_bulletin/           ← main (working copy, always open here)
  visa_bulletin_staging/   ← staging worktree
  visa_bulletin_prod/      ← prod worktree
```

**Cherry-pick workflow (never leave main in the IDE):**
```bash
# Cherry-pick to staging
cd ~/cursor_projects/visa_bulletin_staging
git cherry-pick <commit-hash>
git push origin staging

# Cherry-pick to prod (hotfix)
cd ~/cursor_projects/visa_bulletin_prod
git cherry-pick <commit-hash>
git push origin prod
```

**Why worktrees:** Checking out `staging` or `prod` in the main workspace loses `.claude/rules/` (those files only exist on `main`). Worktrees keep each branch in its own directory so the IDE workspace never changes branches.

## Key Rules

- **Never scp files to servers.** All changes through git branches.
- **Never check out staging/prod in the main workspace.** Use worktrees.
- **`prod` branch = exact mirror of production.** NEVER cherry-pick features or non-critical fixes to it. Only promotion (fast-forward from staging after staging is verified) or critical hotfixes (crashes/5xx deployed directly to prod). If the code isn't running on the prod-serving stack, it doesn't belong on the `prod` branch.
- **`staging` branch = what's on staging.** View via `visa_bulletin_staging/` worktree. All features go through staging first.
- **Tags mark releases.** `v1.X.Y` on `staging` before promotion, then on `prod` after fast-forward.
- **Code deploy ≠ data refresh.** Code deploy = `docker compose pull web && docker compose up -d web` (~30 s). Data refresh = weekly pipeline run on the staging DB followed by atomic flip (~30 min total).
- **Audit Docker before touching containers on prod.** See `AGENTS.md` and `.claude/rules/deployment.md`. Never `docker-compose up/down` without knowing what's actually serving — `vb_web`, `vb_postgres`, `vb_redis`, `vb_nginx`, `vb_cloudflared` are the current prod containers.
- **Promotion is image-tag-based.** Production runs as a single Compose stack; promotion happens via image-tag bump in `docker compose up -d` or postgres-data volume swap.

## Code Deployment (Quick Reference)

**Image-tag deploy** (the current production model). SSH to the relevant server (production or staging — see the private ops repo for aliases) and run the `docker compose` steps:
```bash
# Cherry-pick to staging worktree, push (CI builds image automatically)
cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging
# Wait for GHA to publish ghcr.io/vyakunin/visa_bulletin:staging-<sha>

# Deploy to staging stack first (on the staging server):
cd /opt/stack/visa_bulletin_staging && IMAGE_TAG=staging-<sha> docker compose pull web && docker compose up -d web
# Smoke-test https://staging.visa-bulletin.us/, then promote:
cd ~/cursor_projects/visa_bulletin_prod && git merge --ff-only staging && git push origin prod
# On the production server:
cd /opt/stack/visa_bulletin_prod && IMAGE_TAG=<tag> docker compose pull web && docker compose up -d web
```
