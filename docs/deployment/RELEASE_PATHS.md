# Release paths — visa_bulletin

Two release paths, chosen by **what the change touches**. The deciding question:
*does this change run heavyweight processing, alter the DB schema/format, or
disrupt indexes?* No → Path 1. Yes → Path 2.

> This repo is public, so it describes the process in terms of **roles**
> (`prod server`, `staging server`, `data-pipeline / dev env`) — never concrete
> hosts, addresses, or tunnel identifiers. The concrete server mapping, the
> graduation runbook, and the operational scripts live in the **private ops
> repo** (`visa_bulletin_platform/hosting/`). Operators: see that runbook for the
> real topology and step-by-step commands.

---

## Core invariant

**Nothing heavyweight or schema-changing runs directly on the prod server, ever
— except an urgent outage hotfix.** Prod's only job is to serve. All heavy work
(DOL quarter ingest, re-clustering, index drop/rebuild, migrations, data-format
changes) happens off-prod, gets verified, then graduates in via a cutover that
keeps prod serving the whole time.

The prod server is resource-constrained; a separate, beefier **staging server**
is the off-prod heavy-lift + cutover host. **Staging does not run on the prod
server** — keeping it off-box frees prod's full capacity for serving.

---

## Path 1 — lightweight: rendering / view / config code + routine data

**Scope:** changes that only alter rendering or behavior, with **no** schema
change, data-format change, or heavyweight reprocessing — templates, views, SEO,
copy, bug fixes, config. Plus **routine data updates**, which need no release.

- **Routine data (hourly bulletin ingest):** runs on the **prod server
  automatically**. Append-only, ~1 row/hour. Staging is not involved.
- **Lightweight code:** `main` → cherry-pick to `staging` → CI builds a
  `staging-<sha>` image → deploy to the **staging server** → smoke + prod-diff
  (the HTML/blog diff gate in `.claude/rules/deployment.md`) → fast-forward
  `prod` → CI builds `prod-<sha>` → pull + recreate the prod `web` container →
  flush the page cache.

**Downtime:** the prod `web` swap is ~10–15 s of 502s on uncached/POST requests
— acceptable at a low-traffic hour. Code-only deploys **do not touch the DB**;
prod keeps its data, only the image changes. No cutover needed.

**Why staging still matters for code-only:** the pre-promote diff (staging vs
prod HTML on top URLs) catches template/content regressions a 200-status smoke
misses.

---

## Path 2 — heavyweight: pipeline / schema / format / data refresh

**Scope:** anything that changes the ingest pipeline, data formats, the schema
(migrations), or requires heavyweight reprocessing (new DOL quarter, full
re-cluster, index rebuilds).

**Where the heavy work runs:** off-prod. Develop + iterate the pipeline / format
/ migration code in the **dev / pipeline env** (full toolchain, safe to re-run).
The prod-scale heavy run executes on the **staging server** — reseeded from a
fresh prod dump, the new pipeline applied, indexes dropped for the bulk load then
rebuilt, then clustering + stats + vacuum. The prod server keeps serving its
current data, untouched, the entire time.

**Then graduate via the cutover** — zero prod downtime. (Mechanics + concrete
commands: the private ops runbook.)

---

## The graduation cutover (shape; concrete steps in the private runbook)

Replaces the old in-place postgres-data swap on the prod server (which had
~1–2 min downtime + a role/password re-align gotcha). Prod stays up the whole
time because the staging server temporarily serves prod traffic while the prod
server is resynced to the new state.

1. **Freeze prod writes** — pause the hourly bulletin ingest (the only prod
   writer; a 30–60 min gap is harmless). Prevents split-brain: the staging
   server is the sole writer during the window.
2. **Cut serving over to the staging server** — it begins serving prod traffic
   from the verified new DB; the prod server stops serving.
3. **Resync the prod server to the new state** — restore the new DB onto it (via
   logical dump/restore, not a data-dir copy — that sidesteps the role/password
   gotcha) and pull the new image.
4. **Cut serving back to the prod server** on the new image; smoke; flush cache.
5. **Drop the staging duplicate**; resume the hourly ingest.

**Net:** heavy processing never touched prod; prod served continuously (zero
downtime); the role/password gotcha is gone.

---

## Branch model (unchanged)

`main` (dev) → `staging` (release candidate, deployed to the staging server) →
`prod` (mirror of what's live). Full detail: `.claude/rules/branching.md`.

## Related
- `.claude/rules/deployment.md` — deploy mechanics + the diff gate (role terms).
- `.claude/rules/branching.md` — the 3-branch model.
- **Private ops repo `visa_bulletin_platform/hosting/`** — concrete server
  mapping, the graduation runbook, and all operational scripts. Operators start
  there.
