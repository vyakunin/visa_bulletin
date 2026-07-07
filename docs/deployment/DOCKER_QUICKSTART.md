# Docker Deployment Quick Start

> Production is a single Docker Compose stack on a self-hosted homeserver behind a
> Cloudflare Tunnel (migrated off AWS Lightsail 2026-05-08). **Releases/promotions run
> from the private VB platform repo `visa_bulletin_platform/hosting/`** (zero-downtime
> `cutover.sh --code <sha>`), NOT from this repo and NOT via a GitHub Actions deploy
> workflow. Canonical: [`.claude/rules/branching.md`](../../.claude/rules/branching.md)
> + [`.claude/rules/deployment.md`](../../.claude/rules/deployment.md). (The old
> `scripts/deploy.sh` + `deploy-production.yml` were deleted 2026-06-27.)

## TL;DR

**Local development:**
```bash
docker-compose -f docker-compose.dev.yml up    # Docker
bazel run //:runserver                          # or Bazel, as before
bazel test //tests:...
```

**Build a release image:** push to the `staging` / `prod` branch (or a `v*` tag).
GitHub Actions (`docker-build-push.yml`) builds and pushes to
`ghcr.io/vyakunin/visa_bulletin:<tag>` automatically. Nothing deploys from `main`.

**Promote to prod:** from the platform repo, `cd ~/cursor_projects/visa_bulletin_platform/hosting && ./cutover.sh --code <sha>`.
See [ROLLOUT_FLOW.md](ROLLOUT_FLOW.md).

## What the image contains

Python runtime, system deps (libpq5), pip packages, gunicorn, and baked-in app code.
Prod and staging run baked-in image code (no `../:/app` volume mount). To ship a code
change: push the branch → CI publishes the image → swap the image tag on the target
stack (prod via the zero-downtime `cutover.sh`, staging via `docker compose up -d web`).

> ⚠️ `docker restart` does NOT update the image — it reuses the old one. A new image
> requires recreating the container via `docker compose up -d`. Verify with
> `docker inspect <name> --format '{{.Config.Image}}'`.

## Files

1. **Dockerfile** — gunicorn for production.
2. **docker-compose.yml** — pulls from GHCR; baked-in code.
3. **docker-compose.dev.yml** — local development.
4. **Release tooling** — lives in `visa_bulletin_platform/hosting/` (`cutover.sh`, `promote.sh`, `graduate.sh`), not this repo.
5. **.github/workflows/docker-build-push.yml** — builds + pushes images on `staging`/`prod`/tag pushes.

## Common commands (on the homeserver — `homeserver` SSH alias)

> Before ANY container lifecycle op on prod, run the topology audit in `AGENTS.md` /
> `.claude/rules/deployment.md`. `docker pull` / `docker logs` / `docker inspect` are
> always safe; `docker compose up/down` is not.

```bash
docker compose -f deployment/docker-compose.yml logs -f web   # logs
docker compose -f deployment/docker-compose.yml ps            # status
```

## Releases

```bash
git tag -a v1.2.3 -m "Release 1.2.3" && git push origin v1.2.3
# GitHub Actions builds + pushes ghcr.io/vyakunin/visa_bulletin:v1.2.3 (+ v1.2, v1)
# Then promote via the hosting flow (above) — there is no `gh workflow run deploy-*` step.
```

## Troubleshooting

### Image won't pull
```bash
docker pull ghcr.io/vyakunin/visa_bulletin:latest                 # public, no auth
echo $GITHUB_TOKEN | docker login ghcr.io -u vyakunin --password-stdin   # if private
```

### Rollback
Re-promote the previous image SHA: `./cutover.sh --code <previous-sha>` from
`visa_bulletin_platform/hosting/` (the registry keeps prior images).

## Related

- [ROLLOUT_FLOW.md](ROLLOUT_FLOW.md) — promotion quick reference
- [`.claude/rules/branching.md`](../../.claude/rules/branching.md) — branch + release model
- [`.claude/rules/deployment.md`](../../.claude/rules/deployment.md) — deploy process, perf baselines, smoke tests
