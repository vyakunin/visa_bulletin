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

### 2. deploy-production.yml

**Purpose**: Deploys Docker image to Lightsail production server

**Triggers**:
- Manual workflow dispatch (click button in GitHub UI)
- Automatic after successful docker-build-push (optional, currently manual only)

**What it does**:
1. Sets up SSH to Lightsail
2. Runs `deploy.sh` script on server which:
   - Pulls latest configs from git
   - Pulls new Docker image from GHCR
   - Updates Nginx configs
   - Handles SSL certificates
   - Restarts Docker services
   - Verifies deployment
3. Tests site is accessible (HTTP 200 check)
4. Cleans up SSH keys

**Required Secrets**:
- `LIGHTSAIL_SSH_KEY`: SSH private key for server access
- `LIGHTSAIL_IP`: IP address or hostname of server

**Manual Trigger (Web Interface)**:
1. Go to GitHub → Actions → Deploy to Production
2. Click "Run workflow"
3. Enter version tag (e.g., `v1.2.3` or `latest`)
4. Click "Run workflow"

**Manual Trigger (Command Line)**:
```bash
# Install GitHub CLI (one-time)
brew install gh  # macOS
# See https://cli.github.com for other platforms

# Authenticate (one-time)
gh auth login

# Trigger deployment
gh workflow run deploy-production.yml -f version=v1.2.3

# Check status
gh run list --workflow=deploy-production.yml

# Watch in real-time
gh run watch
```

**Build Time**: ~2-3 minutes

## Setting Up Secrets

### 1. LIGHTSAIL_SSH_KEY

```bash
# On your local machine
cat ~/Downloads/VisaBulletin.pem
# Copy the entire contents
```

Then:
1. Go to GitHub repository → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `LIGHTSAIL_SSH_KEY`
4. Value: Paste the entire private key
5. Click "Add secret"

### 2. LIGHTSAIL_IP

1. Go to GitHub repository → Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `LIGHTSAIL_IP`
4. Value: `3.227.71.176` (or your server's IP)
5. Click "Add secret"

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

# Then manually deploy:
# Go to GitHub → Actions → Deploy to Production → Run workflow
# Enter version: v1.2.3
```

### Deploy Latest to Production

```bash
# No code changes, just want to redeploy

# Go to GitHub → Actions → Deploy to Production → Run workflow
# Enter version: latest
```

### Rollback to Previous Version

```bash
# Go to GitHub → Actions → Deploy to Production → Run workflow
# Enter version: v1.2.2  # Previous stable version
```

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
- Build workflow: ~10 minutes per run
- Deploy workflow: ~3 minutes per run
- Typical monthly usage: ~50 minutes (5 builds + 5 deploys)

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

### Deploy Fails

**Check logs**:
1. Go to Actions → deploy-production workflow
2. Click failed run
3. Expand steps to see where it failed

**Common issues**:
- SSH connection failed: Check LIGHTSAIL_SSH_KEY secret
- Docker pull failed: Check image exists in GHCR
- Service start failed: Check server logs

### Manual Deploy Instead

If GitHub Actions deploy fails, you can always deploy manually:

```bash
# From local machine
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem v1.2.3
```

## Future Enhancements

Possible improvements:

1. **Automatic deployment**: Deploy after successful build on tags
2. **Staging environment**: Deploy to staging first, then prod
3. **Slack notifications**: Alert on deploy success/failure
4. **Automated testing**: Run tests in CI before building
5. **Multi-arch builds**: Build for ARM64 and AMD64

## References

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Docker Build Push Action](https://github.com/docker/build-push-action)
- [GHCR Documentation](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry)

