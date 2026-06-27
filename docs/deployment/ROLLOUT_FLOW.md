# Rollout Flow

> **Canonical reference:** [docs/BRANCHING_AND_DEPLOYMENT.md](../BRANCHING_AND_DEPLOYMENT.md)
>
> This file is a quick-reference summary. For full details (branch strategy, separation of concerns, IP flip procedure, hotfix workflow), see the canonical doc.

## Quick Reference

### Feature Deployment to Staging

```bash
# 1. Cherry-pick from main to staging
git checkout staging && git cherry-pick <commits> && git push origin staging

# 2. Deploy to staging instance
ssh staging_2Gb_vm "cd /opt/visa_bulletin && git fetch origin staging && git checkout staging && git reset --hard origin/staging"
ssh staging_2Gb_vm "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

# 3. Verify
curl -s -o /dev/null -w "%{http_code}" http://<staging-ip>/
```

### Graduation (Staging to Prod)

```bash
# 1. Tag
git checkout staging && git tag -a v1.X.Y -m "Release 1.X.Y: ..." && git push origin v1.X.Y

# 2. IP flip (see docs/BRANCHING_AND_DEPLOYMENT.md for full procedure)
export AWS_PROFILE=visa-bulletin-deploy
aws lightsail detach-static-ip --static-ip-name <prod-ip> --region us-east-1
aws lightsail attach-static-ip --static-ip-name <prod-ip> --instance-name <staging-instance> --region us-east-1

# 3. Verify prod
curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us

# 4. Update prod branch
git checkout prod && git merge staging && git push origin prod

# 5. Bring new staging up to date
ssh <new-staging> "cd /opt/visa_bulletin && git fetch origin staging && git checkout staging && git reset --hard origin/staging"
ssh <new-staging> "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"
```

### Critical Hotfix

```bash
# 1. Fix on prod branch
git checkout prod && <fix> && git commit && git push origin prod

# 2. Deploy to prod-serving instance
ssh prod_2Gb_vm "cd /opt/visa_bulletin && git fetch origin prod && git checkout prod && git reset --hard origin/prod"
ssh prod_2Gb_vm "cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.yml restart web"

# 3. Cherry-pick to staging and main
git checkout staging && git cherry-pick <fix> && git push origin staging
git checkout main && git cherry-pick <fix> && git push origin main
```

### Rollback (After IP Flip)

```bash
# Swap IPs back to the previous instance
aws lightsail detach-static-ip --static-ip-name <prod-ip> --region us-east-1
aws lightsail attach-static-ip --static-ip-name <prod-ip> --instance-name <old-prod-instance> --region us-east-1
```

## Key Rules

- **Never scp files to servers.** All changes through git branches.
- **Code deploy and data refresh are separate.** See [BRANCHING_AND_DEPLOYMENT.md](../BRANCHING_AND_DEPLOYMENT.md).
- **Releases go through `visa_bulletin_platform/hosting/`** (zero-downtime `cutover.sh`), never a hand-rolled script in this repo. See `.claude/rules/branching.md`. (The old `scripts/deploy.sh` was deleted 2026-06-27.)
