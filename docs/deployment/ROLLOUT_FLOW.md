# Rollout Flow

> **Canonical reference:** [`.claude/rules/branching.md`](../../.claude/rules/branching.md)
> + [`.claude/rules/deployment.md`](../../.claude/rules/deployment.md). This file is a
> quick-reference summary of the current homeserver flow.
>
> **All releases/promotions/data-graduations go through the private VB platform repo
> `visa_bulletin_platform/hosting/`** — never hand-roll a `docker compose` deploy or an
> ad-hoc script. The old AWS-Lightsail "IP flip" / blue-green graduation is retired
> (migrated to a self-hosted homeserver behind a Cloudflare Tunnel, 2026-05-08).

## Topology (abstract — concrete hosts/keys live in the private ops repo)

Production is a single Docker Compose stack at `/opt/stack/visa_bulletin` on the
homeserver (`vb_web`, `vb_postgres`, `vb_redis`, `vb_nginx`, `vb_cloudflared`), reached
via the `homeserver` SSH alias. Staging is a separate stack (`vb_stg_*` containers).
All public traffic enters via Cloudflare Tunnel — no router port forwards, no origin IP.

## Quick Reference

### Feature deployment to staging

```bash
# 1. Cherry-pick from main to staging (via the staging worktree)
cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <commit> && git push origin staging
# 2. Wait for CI to publish ghcr.io/vyakunin/visa_bulletin:staging-<sha>, then on the staging stack:
cd /opt/stack/visa_bulletin_staging && IMAGE_TAG=staging-<sha> docker compose pull web && docker compose up -d web
# 3. Verify
curl -s -o /dev/null -w "%{http_code}\n" https://staging.visa-bulletin.us/
```

### Promotion (staging → prod) — ZERO-DOWNTIME default

```bash
# Gate on staging, then swap the homeserver image while the standby serves prod (vb never 502s):
cd ~/cursor_projects/visa_bulletin_platform/hosting && ./cutover.sh --code <sha>   # --dry to preview
# Keep the prod branch mirror honest:
cd ~/cursor_projects/visa_bulletin_prod && git merge --ff-only staging && git push origin prod
```

Data/DB-level promotion (after a verified off-prod refresh) → `./cutover.sh --data`.
Disruptive fallback (only if the cutover is unavailable; ~10-15s prod 502s):
`./promote.sh <sha> --prod --accept-502`. Path-1 (code) vs Path-2 (data) decision:
`hosting/RELEASE_PATHS.md`.

### Critical hotfix (prod-down only)

```bash
# Fix on main → cherry-pick to prod → deploy → back-port to staging
cd ~/cursor_projects/visa_bulletin_prod && git cherry-pick <fix> && git push origin prod
cd ~/cursor_projects/visa_bulletin_platform/hosting && ./cutover.sh --code <sha>
cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <fix> && git push origin staging
```

### Rollback

Re-promote the previous image SHA via `cutover.sh --code <previous-sha>` (the registry
keeps prior images). No AWS IP-flip step anymore.

## Key Rules

- **Never scp/edit files on servers.** All changes go through git branches + the `hosting/` flow.
- **Releases go through `visa_bulletin_platform/hosting/`** (zero-downtime `cutover.sh`), never a hand-rolled script in this repo. (The old `scripts/deploy.sh` was deleted 2026-06-27.)
- **Code deploy and data refresh are separate operations.** See `.claude/rules/branching.md`.
- **Keep staging in parity with prod** — mirror any direct-prod runtime-config change to staging in the same task (`.claude/rules/branching.md`).
