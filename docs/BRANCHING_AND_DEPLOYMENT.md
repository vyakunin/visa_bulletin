# Branching Strategy and Deployment Workflow

> **Current-state overview.** The authoritative operating rules are
> [`.claude/rules/branching.md`](../.claude/rules/branching.md) +
> [`.claude/rules/deployment.md`](../.claude/rules/deployment.md); the release tooling
> lives in the private VB platform repo `visa_bulletin_platform/hosting/`. This doc is
> the human-readable narrative of the model — read the rules for exact commands.
>
> The AWS-Lightsail blue/green deployment (two instances, two static IPs, "IP flip"
> graduation, the `refresh_and_switch.py` orchestrator) was **retired** when prod moved
> to a self-hosted homeserver behind a Cloudflare Tunnel (2026-05-08). Git history
> preserves the old Lightsail worklog if ever needed.

For pipeline-specific operational detail, see [PIPELINE_RUNBOOK.md](PIPELINE_RUNBOOK.md)
(itself mostly retired) and `.claude/rules/deployment.md` "Weekly DB Refresh Pattern".

---

## Topology (abstract — concrete hosts/keys live in the private ops repo)

Production is a single Docker Compose stack at `/opt/stack/visa_bulletin` on the
homeserver (reached via the `homeserver` SSH alias):

| Container | Purpose |
|---|---|
| `vb_postgres` | PostgreSQL 14 (data on `./postgres-data/`) |
| `vb_redis` | Page cache + sessions |
| `vb_web` | Django + gunicorn |
| `vb_nginx` | Static files + reverse proxy |
| `vb_cloudflared` | Cloudflare Tunnel connector |

Staging is a **separate** stack (`vb_stg_*` containers) — ideally off the prod-serving
box. All public traffic enters via Cloudflare Tunnel — there are no router port forwards
and no public origin IP; TLS terminates at the Cloudflare edge. Public hostnames:
`visa-bulletin.us` / `www.visa-bulletin.us` (prod), `staging.visa-bulletin.us` (staging).

---

## Three Branches

| Branch | Purpose | Volatility |
|--------|---------|------------|
| `main` | Development. WIP, experimental, can be broken. Nothing deploys from `main`. | High |
| `staging` | Release candidate. Cherry-picks from `main`. Deployed to the staging stack; data refreshes run here. | Medium |
| `prod` | **Mirror of production. NEVER update unless the change is actually deployed to prod.** | Low |

**`prod` is updated only by** (1) promotion — fast-forward to match `staging` after
staging is verified, or (2) a critical hotfix deployed directly. It must always reflect
exactly what's running. **Never** cherry-pick features or non-critical fixes to `prod`.

**Branch divergence is expected** — `staging`/`prod` legitimately trail `main` by many
commits, and promotion-by-cherry-pick rewrites hashes, so the branches diverge in commit
count even when their working trees are identical. Judge parity by **content**
(`git diff --stat <a> <b>`) and the **deployed image tag**, never by commit count. Never
reset/force-push `staging` or `prod` to "tidy lineage". See `.claude/rules/branching.md`.

---

## Local Worktree Layout

The working copy always stays on `main` so `.claude/rules/` are available. Separate git
worktrees handle `staging` and `prod`:

```
~/cursor_projects/
  visa_bulletin/           ← main (always open here)
  visa_bulletin_staging/   ← staging worktree
  visa_bulletin_prod/      ← prod worktree
```

```bash
# one-time
git worktree add ../visa_bulletin_staging staging
git worktree add ../visa_bulletin_prod prod
# cherry-pick to staging
cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging
```

Checking out `staging`/`prod` in the main workspace would lose `.claude/rules/` (those
files only exist on `main`); worktrees keep each branch in its own directory.

---

## Separation of Concerns

Three independent operations — never conflate them:

1. **Code deployment** — an image-tag swap on the target stack. No data touched.
2. **Data refresh** — the weekly ingest pipeline, run **off-prod on the staging stack**
   against a prod data copy, then graduated.
3. **Promotion (staging → prod)** — code via the zero-downtime `cutover.sh --code <sha>`;
   data via `cutover.sh --data` (postgres-data volume swap after a verified refresh).

Heavyweight data tasks (re-clustering, the weekly refresh, mass UPDATE/DELETE, schema
migrations, index rebuilds) **never** run on the live prod box — compute off-prod on
staging, then graduate the verified data via `cutover.sh --data`. See
`.claude/rules/branching.md` "Heavyweight data tasks".

---

## Release paths (which one?)

Classify the change before promoting (full rule: `.claude/rules/branching.md` "Which
release path"):

- **Path 1 (code)** — pure rendering/view/template/SEO/copy/config; no schema migration
  and nothing that changes how data is populated → `cutover.sh --code <sha>`.
- **Path 2 (data)** — schema migration, index drop/rebuild, OR any change to how data is
  populated (ingest pipeline, clustering, stats) → validate off-prod on staging, then
  `cutover.sh --data`. A mixed batch is Path 2 (or split it).

The Path-1-vs-Path-2 decision matrix lives in `visa_bulletin_platform/hosting/RELEASE_PATHS.md`.

---

## Workflows (summary)

**Feature:** `main` → cherry-pick to `staging` → deploy to the staging stack → test →
iterate. Never directly to `prod`.

**Promotion (zero-downtime default):** verify staging → `cutover.sh --code <sha>` (gates
on staging, then swaps the homeserver image while the standby serves prod, so vb never
502s) → fast-forward the `prod` branch from `staging`. The disruptive in-place
`docker compose up -d web` (`promote.sh --prod --accept-502`, ~10-15s 502s) is a fallback
only when the cutover is unavailable.

**Hotfix (prod-down only):** fix on `main` → cherry-pick to `prod` → deploy via
`cutover.sh` → back-port to `staging`. Only for crashes/5xx.

**Data refresh:** reset staging DB from prod → run the refresh pipeline against staging →
smoke staging → graduate via `cutover.sh --data`. See `.claude/rules/deployment.md`.

---

## Keep staging in parity with prod

The promotion ships a **code image** — it does NOT carry per-stack **runtime config**
(compose `command`/env, volumes, monetization `overrides/`, `ALLOWED_HOSTS`). Any direct
change to prod runtime config must be mirrored to staging **in the same task**, or the
next promote diff-gate fills with phantom deltas. Discovering drift = reconcile it in the
same turn. Full rule: `.claude/rules/branching.md` "Keep staging and prod in PARITY".

---

## Key Rules

- **Never scp/edit files on servers.** All changes go through git branches + the `hosting/` flow.
- **All releases go through `visa_bulletin_platform/hosting/`** — never a hand-rolled `docker compose` deploy or ad-hoc script in this repo.
- **`prod` branch = exact mirror of production.** Only promotion (fast-forward from staging) or critical hotfix touch it.
- **Tags mark releases** — `v1.X.Y` on `staging` before promotion, then on `prod` after fast-forward.
- **Audit Docker topology before any container lifecycle op on prod** (see below).

---

## Why three branches, not two?

Without `prod` you can't check out "what's in production" locally. After a promotion the
`staging` branch immediately starts accepting the next cycle's patches; the `prod` branch
provides a stable snapshot that only moves on promotion or hotfix.

---

## Docker Safety on Production

**Before ANY `docker compose up/down`, `docker stop`, or `docker rm` on prod:**

```bash
docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'   # what exists
ss -tlnp | grep 8000                                         # what's actually serving
docker network inspect <network> --format '{{range .Containers}}{{.Name}} {{end}}'
```

Understand which container is *actually serving traffic* before touching anything.
Containers may depend on Docker DNS (e.g. the `redis` hostname) — stopping ANY container
on the shared network can break hostname resolution for the serving container.

| Operation | Risk |
|-----------|------|
| `docker pull`, `docker logs`, `docker inspect` | None (read-only) |
| `docker compose restart web` / `docker restart <container>` | Low (named service only) |
| `docker compose up -d` | **High** — may recreate/stop other containers |
| `docker compose down` | **Critical** — stops ALL project containers |
| `docker stop/rm` any container | **High** — may break DNS for dependents |

**Cautionary incident (Lightsail era, 2026-02-19):** a `docker-compose up -d` on prod
recreated the redis container while a legacy serving container depended on the `redis`
Docker hostname for cache → DNS broke → 500s for ~3 min. Lesson: always audit the full
container topology before touching Docker on prod; the serving container may not be the
one you expect.
