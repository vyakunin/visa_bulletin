# Deployment configuration

Generic, host-agnostic deployment artifacts for the Visa Bulletin Dashboard
(`https://visa-bulletin.us`). Everything here is portable — it names **roles**
(prod server, staging server, data-pipeline server), never specific hardware,
hostnames, or IP addresses.

## What lives here

```
deployment/
├── docker-compose.yml      # app stack: web (gunicorn) + redis + nginx + postgres
├── docker-compose.dev.yml  # local-dev override
├── nginx/                  # reverse-proxy / rate-limit / log-format configs
├── postgres/conf.d/        # PostgreSQL tuning (bulk-ingest friendly)
├── redis/                  # redis maxmemory policy
├── cron/                   # cron installers (bulletin refresh)
├── scripts/                # postgres tuning, adaptive bot rate-limit, CF setup
├── systemd/                # optional systemd units (non-Docker hosts)
└── DOMAIN_SETUP.md         # DNS / TLS / CDN setup (abstract)
```

## Release model (roles, not hosts)

Two paths — full spec in **`docs/deployment/RELEASE_PATHS.md`**:

- **Path 1 — lightweight / routine.** Rendering, view, template, and config-only
  changes: build image → deploy to **staging** → promote to **prod** (image swap,
  no DB touch). Routine data (the hourly bulletin ingest) lands on prod
  automatically; no staging step.
- **Path 2 — heavyweight.** Data-pipeline / schema / format changes and heavy
  re-ingests run on the **data-pipeline (dev) server**, then graduate
  **dev → staging → prod**. Nothing heavyweight or schema-changing runs directly
  on prod except an urgent outage hotfix.

Branch model: `main` (dev) → `staging` → `prod`, via worktrees + cherry-pick;
image-tag deploys from `ghcr.io/vyakunin/visa_bulletin`. See
`.claude/rules/branching.md`.

## Concrete hosting topology is intentionally not in this repo

This is a **public** repository. The specific server topology — hostnames,
internal IPs, hardware, the staging/standby/cutover mechanics, backup wiring,
and DR runbooks — lives in the **private ops repo** (`visa_bulletin_platform/hosting/`).
Operators with access work from there; this directory holds only what is safe and
useful to publish.
