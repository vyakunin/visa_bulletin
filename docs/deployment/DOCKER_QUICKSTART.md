# Docker Deployment Quick Start

## TL;DR

**For Developers:**
```bash
# Test locally with Docker
docker-compose -f docker-compose.dev.yml up

# Test locally with Bazel (as before)
bazel run //:runserver
```

**For Production Deployment:**
Releases run from the VB platform repo, not this one — zero-downtime
`visa_bulletin_platform/hosting/cutover.sh --code <sha>`. See
`.claude/rules/branching.md`. (The old `./scripts/deploy.sh` was deleted 2026-06-27.)

**For Releases:**
```bash
# Tag and push - GitHub Actions handles the rest
git tag -a v1.2.3 -m "Release 1.2.3"
git push origin v1.2.3

# Image automatically built and pushed to:
# ghcr.io/vyakunin/visa_bulletin:v1.2.3

# Trigger deployment from command line (requires GitHub CLI)
gh workflow run deploy-production.yml -f version=v1.2.3
gh run watch  # Watch progress
```

## What Changed?

### Before (Old Way)
```
Local:  Bazel → Test
Prod:   git pull → pip install → systemd restart
```

### After (New Way)
```
Local:  Bazel → Test (unchanged)
CI:     GitHub Actions → Docker Build → Push to GHCR
Prod:   docker pull → docker-compose up
```

## Key Benefits

1. **No more memory issues on Lightsail** - Build happens in CI, not on prod
2. **Faster deployments** - Pull image instead of pip install
3. **Easy rollbacks** - Just run previous image tag
4. **Reproducible** - Same image everywhere

## Architecture

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   GitHub     │ → │     GHCR     │ → │  Lightsail   │
│   Actions    │    │   Registry   │    │   Docker     │
│  (builds)    │    │  (storage)   │    │  (runs)      │
└──────────────┘    └──────────────┘    └──────────────┘
```

## Files Modified

1. **Dockerfile** - Now uses gunicorn instead of dev server
2. **docker-compose.yml** - Pulls from GHCR instead of building locally
3. **docker-compose.dev.yml** - New file for local development
4. **Release tooling** - lives in `visa_bulletin_platform/hosting/` (`cutover.sh`), not this repo
5. **.github/workflows/** - New CI/CD workflows

## Documentation

- **DOCKER_DEPLOYMENT.md** - Complete Docker deployment guide
- **DOCKER_QUICKSTART.md** - This file

## Common Commands

### Development
```bash
# Local development with Docker
docker-compose -f docker-compose.dev.yml up

# Local development with Bazel (unchanged)
bazel run //:runserver
bazel test //tests:...
```

### Deployment
Releases run from `visa_bulletin_platform/hosting/` (zero-downtime `cutover.sh --code <sha>`),
not from this repo. See `.claude/rules/branching.md` + `.claude/rules/deployment.md`.

### On Production
```bash
# View logs
docker-compose logs -f web

# Restart services
docker-compose restart

# Check status
docker-compose ps

# Update to new version
docker-compose pull
docker-compose up -d
```

### Releases
```bash
# Create semantic version tag
git tag -a v1.2.3 -m "Release description"
git push origin v1.2.3

# GitHub Actions will:
# 1. Build image with Bazel
# 2. Push to ghcr.io/vyakunin/visa_bulletin:v1.2.3
# 3. Also tag as v1.2, v1, latest

# Deploy from command line (requires: brew install gh)
gh workflow run deploy-production.yml -f version=v1.2.3
gh run watch  # Watch deployment progress
```

## Troubleshooting

### Image won't pull
```bash
# For public repos, no auth needed
docker pull ghcr.io/vyakunin/visa_bulletin:latest

# For private repos, login first
echo $GITHUB_TOKEN | docker login ghcr.io -u vyakunin --password-stdin
```

### Container won't start
```bash
# Check logs
docker-compose logs web

# Restart fresh
docker-compose down
docker-compose up -d
```

### Rollback
```bash
# On production
export IMAGE_TAG=v1.2.2  # Previous working version
docker-compose pull
docker-compose up -d
```

## GitHub Actions Setup

### Required Secrets

Add to GitHub → Settings → Secrets and variables → Actions:

1. **LIGHTSAIL_SSH_KEY** - SSH private key
2. **LIGHTSAIL_IP** - Server IP address

(GITHUB_TOKEN is automatic)

### Workflows

Two workflows are configured:

1. **docker-build-push.yml** - Builds on push/tag
2. **deploy-production.yml** - Deploys to prod (manual trigger)

## Current Status

✅ **Docker deployment is live** (migrated Jan 2026)

- Docker images built via GitHub Actions
- Production uses blue-green deployment
- Data refresh via `scripts/cron/refresh_data.sh` (uses Bazel)

## Related Documentation

- [NEW_INSTANCE_SETUP.md](NEW_INSTANCE_SETUP.md) - Current production setup (living document)
- [DOCKER_DEPLOYMENT.md](DOCKER_DEPLOYMENT.md) - Complete Docker guide
- [ROLLOUT_FLOW.md](ROLLOUT_FLOW.md) - Deployment process

