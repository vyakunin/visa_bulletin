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

## Keep staging and prod in PARITY — mirror every direct-prod change to staging immediately

Staging is only a trustworthy release-candidate (and `promote.sh` diff-gate) if it differs from prod **only by the change under test**. Any change made directly to the **prod** stack's *runtime config* — monetization `overrides/*.html`, `.env`, compose volumes/services, an `ALLOWED_HOSTS` edit, a hotfix applied straight to prod — MUST be mirrored to the **staging** stack in the **same task**. Otherwise divergence silently accumulates and pollutes the next diff-gate with phantom deltas, eroding trust in the gate.

- **Runtime config is NOT carried by the image.** `promote.sh` swaps the web image; it does **not** sync `overrides/`, `.env`, or compose between stacks. Those are per-stack and drift unless you sync them by hand.
- **Source of truth = live prod behavior.** When you change prod runtime config, copy the same files/values into `hosting/staging/`, restart the staging web, and flush staging Redis. When a `monetization/` override is deployed to prod, deploy it to staging too.
- **Mirror immediately, same task** — "sync staging later" means the next diff-gate is noisy and someone re-explains a known divergence.
- **Verify parity:** `diff` the staging vs prod override/`.env` files (or curl both and diff the rendered HTML) and confirm they match except the intended delta.

Origin: 2026-06-23 — staging's monetization overrides were stale (support-CTA card removed from prod 6/18, affiliate updated 6/20, neither mirrored), so the priority-date `promote.sh` diff-gate flagged a phantom "Buy-Me-a-Coffee card on staging." Vladimir: *"tighten the rules to prevent divergences: even on direct prod deploys we should immediately follow with staging updates."*

## 🚨 Heavyweight data tasks: compute OFF-PROD on staging, graduate via cutover — NEVER mutate the serving prod box directly

**A heavyweight data task NEVER runs its heavy compute/mutation on the live prod box. The heavy work runs OFF-PROD on the staging stack (against a prod data copy); the verified DATA is then graduated via the Path-2 `cutover.sh --data` cutover, during which the STAGING stack SERVES prod traffic while the homeserver resyncs FROM staging.** Prod must never be simultaneously *heavy-mutating* AND *sole-serving*.

**What counts as heavyweight (this rule applies):** employer **re-clustering** (`cluster_existing_employers`), job-title re-clustering, the weekly **salary/bulletin data refresh** (millions of rows), any **mass UPDATE/DELETE/reprocess**, **schema migrations** on large tables, and **index drop/rebuild**. Rule of thumb: if it rewrites/derives a large fraction of a big table or runs minutes-to-hours, it is heavyweight → off-prod + cutover.

**The flow (do NOT shortcut to a direct prod run):**
1. Run the heavy job on the **staging stack** (minipc), against staging's prod-copy DB. Validate the result (counts, before/after diffs, 0 orphaned FKs, spot-check sample rows). Measure runtime.
2. Graduate the verified DATA with `cutover.sh --data <sha>` (RELEASE_PATHS.md Option A): the staging stack serves `visa-bulletin.us` from its already-graduated DB while the homeserver resyncs from it. **Zero vb compute on prod**, zero vb downtime.
3. Ship any code the job depends on in the prod image so the cron/future runs use it.
4. Verify the prod end-state from a fresh read (profile pages, counts) — `verify_end_state`.

**Forbidden:** a direct `nice`'d heavy mutation against the live prod DB "because it's only ~5 min", or any heavy job whose sole-serving prod box also bears the compute/I/O. Even a read-heavy `pg_dump` of live prod is avoided where possible (see the release-protocol note below).

**Index drop/rebuild (answering "do we still do this?"):** the **clustering** job does NOT drop indexes — its repair re-run only re-points the merged-away clusters' members (a small, bounded write set), so it runs fine with indexes live (validated: full staging re-cluster, 302k employers, 81 merges, 4.6 min, indexes on). Index drop/rebuild is reserved for **from-scratch mass population** (the millions-row salary refresh, `deployment.md` "Weekly DB Refresh Pattern") where mass writes against live indexes are the bottleneck — and that, too, runs off-prod on staging per this rule. Any `CREATE INDEX`/`ALTER` on a large table that DOES run near prod uses `CONCURRENTLY` (`deployment.md`).

Origin: 2026-06-21 — the employer-clustering split-cluster fix was validated on staging (off-prod) and its prod graduation was (correctly) held as a Path-2 cutover, not a direct prod re-cluster. Vladimir: "this is an example of a heavyweight task that requires serving on staging while clustering on prod — make it very clear in rules."

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
