# Rollout Flow

This document describes the complete process for deploying changes to production.

## Overview

**Standard rollout (production):**
```
Code Changes → Tag Version → Build Image → Deploy → Monitor
```

**Staging / dev cycle / urgent fix:** Deploy from source without building an image — copy changed files with `scp` to staging, then reload gunicorn (`pkill -HUP gunicorn`). See [Deploy from source (staging / dev cycle or urgent fix)](#deploy-from-source-staging--dev-cycle-or-urgent-fix).

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
./scripts/deploy-zero-downtime.sh ~/Downloads/VisaBulletin.pem v1.2.3
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
ssh prod_0.5Gb_vm << 'ENDSSH'
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
ssh prod_0.5Gb_vm 'sudo docker-compose -f /opt/visa_bulletin/docker-compose.test.yml images'

# Check logs
ssh prod_0.5Gb_vm 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs --tail=50'
```

### Step 8: Monitor (15-30 minutes)

Watch for issues:

```bash
# Monitor logs
ssh prod_0.5Gb_vm 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs -f'

# Check error logs
ssh prod_0.5Gb_vm 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs | grep -i error'

# Monitor resource usage
ssh prod_0.5Gb_vm 'free -h && df -h'
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
./scripts/deploy-zero-downtime.sh ~/Downloads/VisaBulletin.pem v1.2.2

# Or via GitHub Actions
source ~/.shrc && gh workflow run deploy-production.yml -f version=v1.2.2
```

### Emergency Rollback to Systemd

If Docker is completely broken:

```bash
ssh prod_0.5Gb_vm << 'ENDSSH'
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
- [ ] **Optional:** If deploy changed cached payload structure or you ran a major data refresh, clear cache: `bazel run //scripts:clear_cache` (or on server: `cd /opt/visa_bulletin && set -a && source .env && set +a && bazel run //scripts:clear_cache`). See *Cache cleansing* in `docs/EMPLOYER_PROFILE_QUERIES_AND_OPTIMIZATION.md`.
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
./scripts/deploy-zero-downtime.sh ~/ssh-key.pem v1.0.1

# 4. Monitor closely
ssh prod_0.5Gb_vm 'cd /opt/visa_bulletin && sudo docker-compose -f docker-compose.test.yml logs -f'
```

### Scenario 2: Feature Deployment

```bash
# 1. Complete feature
git commit -m "Add user dashboard feature"

# 2. Create minor version
git tag -a v1.1.0 -m "Release 1.1.0: User dashboard"
git push origin v1.1.0

# 3. Deploy during low traffic time
./scripts/deploy-zero-downtime.sh ~/ssh-key.pem v1.1.0

# 4. Extended monitoring (30+ minutes)
```

### Scenario 3: Deploy Latest (No Version)

```bash
# Deploy whatever is currently tagged as 'latest'
./scripts/deploy-zero-downtime.sh ~/ssh-key.pem latest

# Note: This is less traceable, use versions when possible
```

## Deploy from source (staging / dev cycle or urgent fix)

Use this flow when you want to run **uncommitted or branch changes on staging** without building a Docker image. Staging runs **gunicorn** from the code on disk at `/opt/visa_bulletin`; updating files and reloading workers picks up changes immediately.

**When to use:**
- Dev cycle: iterate on UI or backend and verify on staging before committing.
- Urgent fix: push a small fix to staging for validation before full tag/deploy.

**Requirements:**
- SSH alias `staging_2Gb_vm` (or use `ubuntu@44.209.204.255` with your key).
- Staging app running under gunicorn (not Docker for the web process).

### 1. Copy changed files to staging

From the project root, `scp` only the files you changed (or a small set of dirs). Example for a single script and model:

```bash
cd /path/to/visa_bulletin

# Example: one script + one model
scp scripts/salary/update_job_title_cluster_stats.py staging_2Gb_vm:/opt/visa_bulletin/scripts/salary/
scp models/job_title.py staging_2Gb_vm:/opt/visa_bulletin/models/
```

Example for webapp UI changes (templates, views, static):

```bash
cd /path/to/visa_bulletin

scp webapp/views/job_titles/profile.py staging_2Gb_vm:/opt/visa_bulletin/webapp/views/job_titles/
scp webapp/templates/webapp/job_title_profile.html staging_2Gb_vm:/opt/visa_bulletin/webapp/templates/webapp/
scp webapp/templates/webapp/base.html staging_2Gb_vm:/opt/visa_bulletin/webapp/templates/webapp/
scp webapp/templates/webapp/employer_profile.html staging_2Gb_vm:/opt/visa_bulletin/webapp/templates/webapp/
scp webapp/templates/webapp/includes/chart_loading_container.html staging_2Gb_vm:/opt/visa_bulletin/webapp/templates/webapp/includes/
scp webapp/templates/webapp/includes/yoy_trends_table.html staging_2Gb_vm:/opt/visa_bulletin/webapp/templates/webapp/includes/
scp webapp/static/js/sortable_tables.js staging_2Gb_vm:/opt/visa_bulletin/webapp/static/js/
```

### 2. Reload gunicorn (pick up new code)

```bash
# See running gunicorn processes
ssh staging_2Gb_vm "pgrep -af gunicorn"

# Graceful reload (workers restart, no dropped connections)
ssh staging_2Gb_vm "pkill -HUP gunicorn && echo 'Gunicorn workers reloaded (cache cleared)'"
```

If gunicorn is run via a wrapper (e.g. `django_config.wsgi`):

```bash
ssh staging_2Gb_vm "pkill -HUP -f 'gunicorn.*django_config' 2>/dev/null; sleep 1; ps aux | grep gunicorn | grep -v grep | head -3"
```

### 3. Verify

```bash
# Check app responds
curl -s -o /dev/null -w "%{http_code}" http://44.209.204.255/job-title/software-engineer-161543223/
curl -sI http://44.209.204.255/salaries/ | head -1
```

**Notes:**
- No Docker image build or tag; changes are only on the staging server.
- For production, use the normal flow: commit → tag → build image → deploy with `deploy-zero-downtime.sh`.
- Staging `.env` and DB are unchanged; only code and static files are updated.

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
./scripts/deploy-zero-downtime.sh ~/ssh-key.pem v1.2.3

# Check SSH access
ssh prod_0.5Gb_vm 'uptime'

# Check Docker status
ssh prod_0.5Gb_vm 'sudo docker ps'
```

### Site Down After Deployment

```bash
# Quick rollback
./scripts/deploy-zero-downtime.sh ~/ssh-key.pem v1.2.2

# Or emergency rollback to systemd
ssh prod_0.5Gb_vm 'sudo systemctl start visa-bulletin'
```

## Version History

Track deployed versions:

```bash
# View all releases
git tag -l -n

# View on GitHub
# https://github.com/vyakunin/visa_bulletin/releases

# Check what's deployed
ssh prod_0.5Gb_vm 'sudo docker-compose -f /opt/visa_bulletin/docker-compose.test.yml images'
```

## Additional Resources

- **New Instance Setup**: `NEW_INSTANCE_SETUP.md`
- **Deployment Scripts**: `scripts/deploy-zero-downtime.sh`
- **GitHub Actions**: `.github/workflows/`

---

**Remember**: When in doubt, create a version tag. It's easier to have too many versions than too few!

