# GitHub Actions Workflows

This directory contains CI/CD workflows for automated Docker image building and deployment.

## Workflows

### 1. docker-build-push.yml

**Purpose**: Builds Docker image with Bazel and pushes to GitHub Container Registry (GHCR)

**Triggers**:
- Push to `main` branch
- Push of tags matching `v*.*.*` (e.g., v1.2.3)

**What it does**:
1. Checks out code
2. Sets up Docker Buildx (for efficient builds)
3. Logs into GHCR using GITHUB_TOKEN
4. Builds multi-stage Docker image (Bazel → Runtime)
5. Pushes to `ghcr.io/vyakunin/visa_bulletin` with appropriate tags
6. Uses GitHub Actions cache for faster builds

**Image Tags Created**:

| Git Event | Docker Tags |
|-----------|-------------|
| Push to main | `main-<sha>` |
| Tag v1.2.3 | `v1.2.3`, `v1.2`, `v1`, `latest` |

**Example**:
```bash
# Push to main
git push origin main
# Creates: ghcr.io/vyakunin/visa_bulletin:main-abc1234

# Create release tag
git tag -a v1.2.3 -m "Release 1.2.3"
git push origin v1.2.3
# Creates:
#   ghcr.io/vyakunin/visa_bulletin:v1.2.3
#   ghcr.io/vyakunin/visa_bulletin:v1.2
#   ghcr.io/vyakunin/visa_bulletin:v1
#   ghcr.io/vyakunin/visa_bulletin:latest
```

**Build Time**: ~10-15 minutes (first build), ~5 minutes (cached)

**GitHub Actions Minutes Used**: ~10-15 minutes per build

### 2. Deploys are NOT a GitHub Actions workflow

There is no deploy workflow in this repo. The old `deploy-production.yml` (manual
`workflow_dispatch` that SSHed to AWS Lightsail and ran `scripts/deploy.sh`) was
**deleted 2026-06-27** along with `scripts/deploy.sh` — both were Lightsail-era and dead.

Production now runs on the self-hosted homeserver, and **releases go through the VB
platform repo** `visa_bulletin_platform/hosting/`: zero-downtime
`cutover.sh --code <sha>` (code) / `cutover.sh --data` (DB-level). GitHub Actions'
only job is **building + publishing the image** (docker-build-push.yml above); promotion
to prod happens from `hosting/`, off-CI. Canonical flow: `.claude/rules/branching.md`
+ `.claude/rules/deployment.md`.

## Setting Up Secrets

The build workflow needs no manual secrets — it uses the auto-provided `GITHUB_TOKEN`
(`packages: write`) to push to GHCR. The old `LIGHTSAIL_SSH_KEY` / `LIGHTSAIL_IP`
secrets were only for the deleted deploy workflow and are no longer used; remove them
from repo settings if still present.

## Usage Examples

### Release a New Version

```bash
# Ensure all changes are committed and pushed
git add .
git commit -m "Feature: Add new feature"
git push origin main

# Tag the release
git tag -a v1.2.3 -m "Release 1.2.3: Add new feature"
git push origin v1.2.3

# GitHub Actions will automatically:
# 1. Build Docker image
# 2. Push to GHCR with tags: v1.2.3, v1.2, v1, latest
```

### Deploy / Promote / Rollback to Production

Promotion to prod is NOT a GitHub Actions step — it runs from the VB platform repo
`visa_bulletin_platform/hosting/` (zero-downtime; gates on staging first):

```bash
# Promote a built image SHA to prod (code-only), zero-downtime:
cd ~/cursor_projects/visa_bulletin_platform/hosting && ./cutover.sh --code <sha>
# Roll back: cutover/promote the previous good <sha> the same way.
```

Full branching + Path-1-vs-Path-2 + rollback flow: `.claude/rules/branching.md`
+ `.claude/rules/deployment.md`.

## Monitoring Workflows

### View Workflow Runs

1. Go to GitHub repository → Actions
2. Click on workflow name
3. View recent runs and their status

### View Build Logs

1. Click on a specific workflow run
2. Click on job name
3. Expand steps to see detailed logs

### View Built Images

1. Go to GitHub repository page
2. Click "Packages" (right sidebar)
3. Click on `visa_bulletin` package
4. View all versions and tags

## Workflow Permissions

The workflows require these permissions:

- `contents: read` - Read repository code
- `packages: write` - Push to GHCR

These are granted automatically via `GITHUB_TOKEN`.

## Cost

### GitHub Actions Minutes

**Free tier**:
- Public repos: Unlimited
- Private repos: 2,000 minutes/month

**Current usage**:
- Build workflow: ~10 minutes per run (the only workflow that consumes minutes; deploys run off-CI from `hosting/`)
- Typical monthly usage: ~50 minutes

**Verdict**: Well within free tier limits

### GitHub Container Registry

**Free tier**:
- Public repos: Unlimited
- Private repos: 500 MB storage, 1 GB transfer/month

**Current usage**:
- Image size: ~500 MB per version
- Typical storage: 1-2 GB (keeping 3-4 versions)

**Verdict**: 
- Public repo: Free
- Private repo: May need paid plan ($0.008/GB/day storage)

## Troubleshooting

### Build Fails

**Check logs**:
1. Go to Actions → docker-build-push workflow
2. Click failed run
3. Expand "Build and push Docker image"

**Common issues**:
- Bazel build error: Check BUILD files
- Out of memory: GitHub runners have 7GB (should be sufficient)
- Image push failed: Check package permissions

### Deploy / Promotion Fails

Promotion runs from `visa_bulletin_platform/hosting/` (not CI). Diagnose with
`cutover.sh --code <sha> --dry` (prints the plan + preflight) and the
homeserver-side checks in `.claude/rules/deployment.md` (perf baseline, smoke,
rollback triggers). Common issues: image SHA not yet published to GHCR; minipc
below the standby RAM floor (cutover falls back to the disruptive swap); staging
diff-gate flags a phantom delta (mirror runtime config per the parity rule).

## Future Enhancements

Possible improvements:

1. **Automatic deployment**: Deploy after successful build on tags
2. **Deploy**: Deploy to prod (or backup for rollback)
3. **Slack notifications**: Alert on deploy success/failure
4. **Automated testing**: Run tests in CI before building
5. **Multi-arch builds**: Build for ARM64 and AMD64

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [GHCR Documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

