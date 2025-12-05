# Rollout Flow

This document describes the complete process for deploying changes to production.

## Overview

```
Code Changes → Tag Version → Build Image → Deploy → Monitor
```

## Step-by-Step Rollout Process

### Step 1: Make Changes Locally

```bash
# Make your changes
vim some_file.py

# Test with Bazel
bazel test //tests:...

# Test locally if needed
bazel run //:runserver
```

### Step 2: Commit Changes

```bash
git add .
git commit -m "Descriptive commit message

- Explain what changed
- Why it changed
- Any important notes"
```

### Step 3: Decide on Version

**Version Numbering:**
- **Major (v2.0.0)**: Breaking changes, incompatible updates
- **Minor (v1.3.0)**: New features, backward compatible
- **Patch (v1.2.4)**: Bug fixes, small improvements

**Example:**
```bash
# For a bug fix
git tag -a v1.0.1 -m "Release 1.0.1: Fix date parsing bug"

# For a new feature
git tag -a v1.1.0 -m "Release 1.1.0: Add user dashboard"

# For breaking changes
git tag -a v2.0.0 -m "Release 2.0.0: New database schema"
```

### Step 4: Push Code and Tag

```bash
# Push commits
git push origin main

# Push tag (triggers Docker build)
git push origin v1.2.3
```

### Step 5: Monitor Build

```bash
# Watch build progress
source ~/.shrc && gh run watch

# Or check status
source ~/.shrc && gh run list --workflow=docker-build-push.yml --limit 1
```

**Expected time**: 10-15 minutes for first build, ~5 minutes for cached builds

### Step 6: Deploy to Production

#### Option A: Using deploy.sh (Recommended)

```bash
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem v1.2.3
```

This script:
- Pulls latest configs from GitHub
- Pulls Docker image from GHCR
- Updates nginx configs
- Handles SSL certificates
- Restarts Docker services
- Checks health

#### Option B: Using GitHub Actions

```bash
source ~/.shrc && gh workflow run deploy-production.yml -f version=v1.2.3
```

#### Option C: Manual Deployment

```bash
ssh lightsail << 'ENDSSH'
cd /opt/visa_bulletin
git pull origin main
export IMAGE_TAG=v1.2.3
sudo docker-compose -f docker-compose.test.yml pull
sudo docker-compose -f docker-compose.test.yml up -d
ENDSSH
```

### Step 7: Verify Deployment

```bash
# Test main pages
curl -I https://visa-bulletin.us
curl -I https://visa-bulletin.us/about/
curl -I https://visa-bulletin.us/faq/

# Check deployed version
ssh lightsail 'sudo docker-compose -f /opt/visa_bulletin/docker-compose.test.yml images'

# Check logs
ssh lightsail 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs --tail=50'
```

### Step 8: Monitor (15-30 minutes)

Watch for issues:

```bash
# Monitor logs
ssh lightsail 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs -f'

# Check error logs
ssh lightsail 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs | grep -i error'

# Monitor resource usage
ssh lightsail 'free -h && df -h'
```

### Step 9: Document (If Major Release)

For significant releases, update:
- `README.md` - If user-facing changes
- `CHANGELOG.md` - If you maintain one
- GitHub Release notes

## Rollback Procedure

If issues are detected:

### Rollback to Previous Version

```bash
# Deploy previous version
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem v1.2.2

# Or via GitHub Actions
source ~/.shrc && gh workflow run deploy-production.yml -f version=v1.2.2
```

### Emergency Rollback to Systemd

If Docker is completely broken:

```bash
ssh lightsail << 'ENDSSH'
cd /opt/visa_bulletin
# Stop Docker
sudo docker-compose -f docker-compose.test.yml down

# Switch nginx back to systemd (port 8000)
sudo sed -i "s/127\.0\.0\.1:8001/127.0.0.1:8000/g" deployment/nginx/visa-bulletin-locations.conf
sudo nginx -t
sudo systemctl reload nginx

# Verify systemd is running
sudo systemctl status visa-bulletin
ENDSSH
```

## Pre-Rollout Checklist

Before deploying to production:

- [ ] All tests pass locally (`bazel test //tests:...`)
- [ ] Code reviewed (if team project)
- [ ] Version tag created
- [ ] Docker image built successfully in CI
- [ ] Decided on rollback plan
- [ ] Have SSH access to production ready
- [ ] Monitoring tools ready (terminal, browser)

## Post-Rollout Checklist

After deployment:

- [ ] Site responds (HTTP 200)
- [ ] Main pages load correctly
- [ ] No errors in logs
- [ ] Resource usage normal
- [ ] Monitored for 15+ minutes
- [ ] Version tag noted in deployment log

## Common Scenarios

### Scenario 1: Hotfix Deployment

```bash
# 1. Fix the bug
git commit -m "Fix critical bug X"

# 2. Create patch version
git tag -a v1.0.1 -m "Hotfix: Fix critical bug X"
git push origin v1.0.1

# 3. Fast deploy
./scripts/deploy.sh ~/ssh-key.pem v1.0.1

# 4. Monitor closely
ssh lightsail 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs -f'
```

### Scenario 2: Feature Deployment

```bash
# 1. Complete feature
git commit -m "Add user dashboard feature"

# 2. Create minor version
git tag -a v1.1.0 -m "Release 1.1.0: User dashboard"
git push origin v1.1.0

# 3. Deploy during low traffic time
./scripts/deploy.sh ~/ssh-key.pem v1.1.0

# 4. Extended monitoring (30+ minutes)
```

### Scenario 3: Deploy Latest (No Version)

```bash
# Deploy whatever is currently tagged as 'latest'
./scripts/deploy.sh ~/ssh-key.pem latest

# Note: This is less traceable, use versions when possible
```

## Deployment Windows

**Recommended deployment times:**
- **Best**: Late evening or early morning (low traffic)
- **Avoid**: Business hours (9 AM - 5 PM users' time)
- **Never**: During known high-traffic events

## Troubleshooting

### Build Fails

```bash
# Check build logs
source ~/.shrc && gh run view <run-id> --log

# Test locally first
source ~/.shrc && act -W .github/workflows/docker-build-push.yml
```

### Deployment Fails

```bash
# Check deploy.sh output
./scripts/deploy.sh ~/ssh-key.pem v1.2.3

# Check SSH access
ssh lightsail 'uptime'

# Check Docker status
ssh lightsail 'sudo docker ps'
```

### Site Down After Deployment

```bash
# Quick rollback
./scripts/deploy.sh ~/ssh-key.pem v1.2.2

# Or emergency rollback to systemd
ssh lightsail 'sudo systemctl start visa-bulletin'
```

## Version History

Track deployed versions:

```bash
# View all releases
git tag -l -n

# View on GitHub
# https://github.com/vyakunin/visa_bulletin/releases

# Check what's deployed
ssh lightsail 'sudo docker-compose -f /opt/visa_bulletin/docker-compose.test.yml images'
```

## Additional Resources

- **Docker Deployment Guide**: `DOCKER_DEPLOYMENT.md`
- **Migration Guide**: `MIGRATION_TO_DOCKER.md`
- **Quick Reference**: `DOCKER_QUICKSTART.md`
- **Deployment Scripts**: `scripts/deploy.sh`
- **GitHub Actions**: `.github/workflows/`

---

**Remember**: When in doubt, create a version tag. It's easier to have too many versions than too few!

