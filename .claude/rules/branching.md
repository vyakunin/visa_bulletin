# Branching and Deployment Strategy

> Concrete hosting topology (hosts, IPs, hardware, the staging/standby/cutover mechanics, backup wiring, DR) lives in the private ops repo, not in this public repository. Public docs use abstract roles (production / staging / data-pipeline server). The 3-branch model below is host-agnostic.

**Canonical reference:** `docs/BRANCHING_AND_DEPLOYMENT.md`.

## 🚨 Rule: ALL releases go through `visa_bulletin_platform/hosting/` — never hand-roll a deploy

**Every deploy / promotion / cutover / graduation / runtime-config change uses the committed release code in the private ops repo `~/cursor_projects/visa_bulletin_platform/hosting/`. Do NOT hand-roll a `docker compose` invocation, a one-off deploy script, or an ad-hoc image swap — and NEVER edit files directly on the server (`deployment.md`).** This is strict, no exceptions short of the platform script itself being broken (then fix the script, don't bypass it).

Canonical release surfaces (the ONLY paths to prod):

| Operation | Use | Never instead |
|---|---|---|
| Promote staging→prod (Path 1, code-only) | **`hosting/cutover.sh --code <sha>`** — zero-downtime (gates on staging, then swaps while the minipc serves prod; vb never 502s) | `promote.sh --prod` or a bare `docker compose pull web && up -d` on the box — both 502 prod ~10–15 s. Disruptive fallback ONLY when the cutover is unavailable (and then `promote.sh <sha> --prod --accept-502`). |
| Data-refresh / heavyweight graduation (Path 2) | `hosting/cutover.sh --data` / `hosting/graduate.sh` | a direct heavy mutation on the serving prod box |
| Runtime config (compose, `.env`, monetization `overrides/`) | edit the per-stack file under `hosting/{homeserver,staging,standby}/` then deploy it; **mirror to staging same task** (parity rule below) | `sed`/`vi` on `/opt/stack/...` on the server |
| Edge cache purge | `hosting/scripts/cf_cache_purge.py` | manual CF dashboard clicks |
| Release-path decision (Path 1 vs Path 2) | `hosting/RELEASE_PATHS.md` | guessing |

**Two-repo split for a code change that needs runtime config:** the *code* (e.g. `webapp/`, `Dockerfile`) lands in THIS public repo and ships as a CI-built image; the *runtime config* (compose `command:`/env, volumes, `overrides/`) lands in `visa_bulletin_platform/hosting/` because **the image does not carry per-stack runtime config** (`promote.sh` swaps the image only). A change touching both is not done until BOTH repos are committed AND the hosting-side config is deployed to the stack. Build new release tooling (e.g. a future `blue_green_deploy.sh`) **inside `hosting/`**, never in this public repo's `tools/`.

Origin: 2026-06-24 — the EB-dashboard worker-warmup fix needed `VQS_WARM=1` on the gunicorn command, which lives in the `hosting/{homeserver,staging,standby}/docker-compose.yml` runtime composes (the Dockerfile CMD is overridden in prod). Vladimir: *"Make sure you use vb platform rules/code for releases, have a strict rule about that."*

## Three Branches

- **`main`** — Development. Can be messy, broken, WIP. Nothing deploys from `main`.
- **`staging`** — Release candidate. Cherry-picks from `main`. Deployed to the staging stack. Data refreshes run here.
- **`prod`** — **Mirror of production. NEVER update unless the change is actually deployed to production.** Updated only in two cases: (1) promotion — fast-forward to match `staging` after staging is verified, (2) critical hotfix — fix deployed directly. The branch must always reflect exactly what's running.

### Branch divergence is EXPECTED — judge parity by CONTENT, never by commit count

`git rev-list --count` between these branches is a **misleading signal** and must NOT be treated as drift to "fix":

- **`staging`/`prod` legitimately trail `main` by tens of commits** — `main` is dev and carries unreleased WIP. "staging is N commits behind main" is the model working, not a problem. **NEVER "reconcile" by merging/resetting `main` → `staging`** — that dumps unvalidated WIP into the release candidate and breaks the whole 3-branch separation.
- **Promotion is by CHERRY-PICK (and image-SHA), which rewrites the commit hash.** So the *same* change lands under a *different* SHA on each branch, and the three branches diverge in commit count and SHA even when their working trees are **byte-identical**. A large `main…staging` / `staging…prod` count is almost always this artifact, not real divergence.
- **The only parity that matters: (a) working-tree CONTENT and (b) the deployed image tag.** Verify content parity with `git diff --stat <a> <b>` (empty = identical) or `git show <branch> --format= | git patch-id` (same patch-id on each tip = same change, cherry-picked). Verify deployed state against the live prod image tag, not the `prod` branch SHA — prod runs the promoted `staging-<sha>` image; the `prod` branch is a content-mirror for reference, not the source of the running SHA.
- **Do NOT force-push/reset `staging` or `prod` to "tidy lineage."** History rewrites on shared release branches are Tier 3 (`automation_safety.md`) and can desync the branch↔deployed-image mapping. If the branches are content-equal at the tip and serving correctly, there is nothing to reconcile — leave them.

## Separation of Concerns

Three independent operations — never conflate them:

- **Code deployment**: image-tag swap on the target stack. To **staging**, that's `IMAGE_TAG=staging-<sha> docker compose pull web && docker compose up -d web` on the staging stack. To **prod**, it's the zero-downtime `hosting/cutover.sh --code <sha>` (NOT a bare in-place `docker compose up -d web`, which 502s prod — see "Promote via the ZERO-DOWNTIME cutover"). No data refresh.
- **Data refresh**: weekly job that ingests new salary/bulletin data, run against the staging DB (off-prod), then graduated via `hosting/cutover.sh --data`.
- **Promotion (staging → prod)**: code → `hosting/cutover.sh --code <sha>`; data/DB-level → `hosting/cutover.sh --data` (postgres-data volume swap after a verified refresh). Always via the VB platform `hosting/` tooling, never hand-rolled.

## Which release path — rendering vs data-population

Before promoting, classify the change. **Any "yes" → Path 2 (data-refresh graduation), not a Path 1 image swap:**

- Schema migration, data-format change, index drop/rebuild, or heavyweight reprocessing?
- **Changes HOW DATA IS POPULATED** — the ingest pipeline, clustering, stats/`updated_at` population, anything under `lib/ingest/`, `scripts/salary/`, `scripts/cron/` that writes or derives data?

All "no" (pure rendering/view/template/SEO/copy/config) → **Path 1** (image-tag swap: `staging` image → `prod` image, no DB touch).

- **`no schema migration` ≠ Path 1.** A data-population code change is Path 2 *even with no migration* and *even though the new code sits inert in the prod image until a refresh runs it* — validating it requires running the refresh against real data on the off-prod staging stack and checking the derived data + downstream effects, then graduating the DATA via the cutover. A quick Path 1 swap skips that and leaves the next refresh running unvalidated pipeline code at prod scale.
- **A mixed batch is Path 2.** If even one commit in the promote set touches data-population, the whole promotion is Path 2 — or split the batch and ship only the pure-rendering commits via Path 1.

## Staging runs OFF the prod box — always

The production server is resource-constrained (it serves live load); a co-resident staging stack competes with prod for CPU/RAM on *every* release, not just heavy ones. **Staging belongs on a separate box (the data-pipeline/staging server), never on the prod-serving host.** A staging stack currently co-resident with prod is a stopgap to retire, not the design. Concrete topology + the cutover engine: the private ops repo (`visa_bulletin_platform/hosting/RELEASE_PATHS.md`).

## Promote via the ZERO-DOWNTIME cutover — never the 502 web-swap by default

A code-only promotion to prod **defaults to `hosting/cutover.sh --code <sha>`**, which gates on staging (it calls `promote.sh <sha>` internally) and then swaps the homeserver image *while the minipc serves prod traffic* — so **vb never 502s**. Do NOT routinely promote with `promote.sh --prod` or a bare `docker compose pull web && docker compose up -d web`: those recreate the live `web` container in place, 502-ing prod for ~10–15 s on every release. Disturbing prod is not the cost of a routine deploy; the no-downtime path is BUILT — use it.

- **The cutover's only blast cost is bubba's ~30–60 s blip** (shared homeserver tunnel) — and policy (2026-06-22, `RELEASE_PATHS.md`) already ACCEPTS that as collateral: it does not gate or window a VB release. So there is no "low-traffic window" excuse to fall back to the 502 swap.
- **`promote.sh --prod` is a fallback only when the cutover is genuinely unavailable** (minipc below the RAM floor for the standby restore, standby stack down). It now refuses to run without an explicit `--accept-502` flag, precisely so the disruptive swap can't be taken by habit.
- **Hotfix exception:** a true prod-down emergency (sustained 5xx, broken parser pre-publication) MAY take the fast disruptive swap — but say so; "it was just quicker" is not an emergency.
- **Verify:** zero vb 502s during the swap is the end-state (`promote.sh --prod` would show the ~10–15 s window; the cutover shows none). `cutover.sh --code <sha> --dry` prints the plan + preflight first.

Origin: 2026-06-24 — vb promotions kept disturbing prod with the `promote.sh --prod` / `docker compose up -d web` web-swap (~10–15 s 502s) even though the zero-downtime `cutover.sh --code` was built and is the documented no-downtime path. Vladimir: *"vb promotion keeps disturbing prod, ignoring no-downtime process. Tighten its rules to defer here for promotion."* → flipped the default to the cutover here + in `RELEASE_PATHS.md`, and guarded `promote.sh --prod` behind `--accept-502`.

## Keep staging and prod in PARITY — mirror every direct-prod change to staging immediately

Staging is only a trustworthy release-candidate (and `promote.sh` diff-gate) if it differs from prod **only by the change under test**. Any change made directly to the **prod** stack's *runtime config* — monetization `overrides/*.html`, `.env`, compose volumes/services, an `ALLOWED_HOSTS` edit, a hotfix applied straight to prod — MUST be mirrored to the **staging** stack in the **same task**. Otherwise divergence silently accumulates and pollutes the next diff-gate with phantom deltas, eroding trust in the gate.

- **Runtime config is NOT carried by the image.** `promote.sh` swaps the web image; it does **not** sync `overrides/`, `.env`, or compose between stacks. Those are per-stack and drift unless you sync them by hand.
- **Source of truth = live prod behavior.** When you change prod runtime config, copy the same files/values into `hosting/staging/`, restart the staging web, and flush staging Redis. When a `monetization/` override is deployed to prod, deploy it to staging too.
- **Mirror immediately, same task** — "sync staging later" means the next diff-gate is noisy and someone re-explains a known divergence.
- **Verify parity:** `diff` the staging vs prod override/`.env` files (or curl both and diff the rendered HTML) and confirm they match except the intended delta.
- **DISCOVERING drift = reconcile it in the SAME task — don't defer, don't ask.** The trigger is not only "I'm about to change prod." When a `promote.sh` diff-gate (or any staging↔prod curl-diff) surfaces a **phantom delta** — a difference on a page your change didn't touch, prod runtime config ahead of/behind staging, an override deployed to one stack only — that discovery IS the mandate to mirror it back into parity right then, in the turn that found it. The diff-gate exists precisely to catch this; surfacing it and walking away defeats the gate. This is `~/.claude/rules/drive_dont_defer.md` applied to parity: the mirror is unblocked work you can do with the access in hand, so do it.
- **No excuses that defer it:** "that's the ads/monetization workstream's config, not this SEO turn," "I'll mirror it as a separate step," "it's pre-existing, not mine" — none suspend the same-task mirror. Parity is whoever-touches-the-stack's job; the turn that finds the drift owns its reconciliation, not the workstream that authored it.

❌ Anti-pattern (2026-06-24): an SEO image-promotion's diff-gate surfaced ~308 phantom difflines (prod's affiliate/ads `overrides/` ahead of staging, never mirrored). I correctly flagged it — then ended the turn with *"Want me to mirror prod's affiliate overrides → staging as a separate step?"* That's confirmation-fishing on unblocked work. ✅ Right: copy prod's `overrides/` → `hosting/staging/`, restart staging web, flush staging Redis, re-diff to confirm only the intended delta remains — all in the same turn — then report it done.

Origin: 2026-06-23 — staging's monetization overrides were stale (support-CTA card removed from prod 6/18, affiliate updated 6/20, neither mirrored), so the priority-date `promote.sh` diff-gate flagged a phantom "Buy-Me-a-Coffee card on staging." Vladimir: *"tighten the rules to prevent divergences: even on direct prod deploys we should immediately follow with staging updates."*
Origin: 2026-06-24 — on an SEO promotion I discovered prod's affiliate/ads `overrides/` were ahead of staging (~308 phantom difflines) and *asked* to mirror it "as a separate step" instead of doing it in-task. Vladimir: *"Tighten your rules to always keep staging up to date … maybe share some?"* → added the discovered-drift / no-excuses clauses here + promoted the generic principle to `~/.claude/rules/staging_prod_parity.md`.

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

**Promotion:** verify staging → **`hosting/cutover.sh --code <sha>`** (zero-downtime; gates staging then swaps with vb never 502ing) → fast-forward `prod` from `staging`. Never the in-place `docker compose up -d web` on prod by default — that 502s (see "Promote via the ZERO-DOWNTIME cutover" above).

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
- **Code deploy ≠ data refresh.** Code deploy to **prod** = `hosting/cutover.sh --code <sha>` (zero-downtime; the in-place `docker compose up -d web` is the disruptive fallback only — see Promotion line below). Data refresh = weekly pipeline run on the staging DB followed by atomic flip via `cutover.sh --data` (~30 min total).
- **Audit Docker before touching containers on prod.** See `AGENTS.md` and `.claude/rules/deployment.md`. Never `docker-compose up/down` without knowing what's actually serving — `vb_web`, `vb_postgres`, `vb_redis`, `vb_nginx`, `vb_cloudflared` are the current prod containers.
- **Promotion is image-tag-based, run via the zero-downtime cutover.** Production runs as a single Compose stack; a code promotion bumps the image tag — but **default to `hosting/cutover.sh --code <sha>`** so the swap happens with the minipc serving prod (no 502s), not a bare in-place `docker compose up -d web`. Data promotion = postgres-data volume swap via `cutover.sh --data`.

## Code Deployment (Quick Reference)

**Image-tag deploy** (the current production model). SSH to the relevant server (production or staging — see the private ops repo for aliases) and run the `docker compose` steps:
```bash
# Cherry-pick to staging worktree, push (CI builds image automatically)
cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging
# Wait for GHA to publish ghcr.io/vyakunin/visa_bulletin:staging-<sha>

# Deploy to staging stack first (on the staging server):
cd /opt/stack/visa_bulletin_staging && IMAGE_TAG=staging-<sha> docker compose pull web && docker compose up -d web
# Smoke-test https://staging.visa-bulletin.us/, then promote ZERO-DOWNTIME (default):
cd ~/cursor_projects/visa_bulletin_platform/hosting && ./cutover.sh --code <sha>
# ^ gates staging, then swaps the homeserver image while the minipc serves prod — vb never 502s.
#   (preview: ./cutover.sh --code <sha> --dry)
# Then fast-forward the prod branch to keep the mirror honest:
cd ~/cursor_projects/visa_bulletin_prod && git merge --ff-only staging && git push origin prod
#
# DISRUPTIVE FALLBACK only if the cutover is unavailable (minipc RAM floor / standby down) —
# ~10-15s prod 502s; must pass --accept-502:
#   cd ~/cursor_projects/visa_bulletin_platform/hosting && ./promote.sh <sha> --prod --accept-502
```
