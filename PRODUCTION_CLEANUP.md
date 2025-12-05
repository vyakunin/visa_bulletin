# Production Cleanup Guide

This document outlines cleanup tasks for the production environment.

## Current Status

**Docker Resources:**
- Images: 7 total, 1 active, 2.521GB total, 683.3MB reclaimable (27%)
- Containers: 2 active (web-green, data-refresh-green)
- Build Cache: 302.4MB reclaimable

**Old Images to Remove:**
- `ghcr.io/vyakunin/visa_bulletin:v1.0.0` (old)
- `ghcr.io/vyakunin/visa_bulletin:v1.0.1` (old)
- `ghcr.io/vyakunin/visa_bulletin:v1.0.2` (old)
- `ghcr.io/vyakunin/visa_bulletin:v1.0.3` (old)

**Keep:**
- `ghcr.io/vyakunin/visa_bulletin:v1.0.5` (current)
- `ghcr.io/vyakunin/visa_bulletin:latest` (current)

## Cleanup Scripts

### Automated Cleanup

Run the cleanup script to remove old images and unused resources:

```bash
./scripts/cleanup-docker.sh ~/.ssh/lightsail_visa_bulletin
```

This script:
- Keeps the latest 3 versioned images
- Removes dangling images
- Removes stopped containers
- Removes unused networks
- Removes unused volumes
- Removes build cache

### Manual Cleanup

If you need to clean up manually:

```bash
# Remove old versioned images (keep latest 3)
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176 \
  "cd /opt/visa_bulletin && \
   sudo docker images ghcr.io/vyakunin/visa_bulletin --format '{{.Tag}}' | \
   grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | head -n -3 | \
   xargs -r -I {} sudo docker rmi ghcr.io/vyakunin/visa_bulletin:{}"

# Remove dangling images
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176 \
  "sudo docker image prune -f"

# Remove build cache
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176 \
  "sudo docker builder prune -f"
```

## Regular Maintenance

**Recommended schedule:**
- After each deployment: Run cleanup script to remove old images
- Monthly: Check disk usage and clean up logs if needed
- Quarterly: Review and remove very old images (keep last 6 months)

## Disk Space Monitoring

Check disk usage:
```bash
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176 "df -h /"
```

Check Docker disk usage:
```bash
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176 "sudo docker system df"
```

## What NOT to Clean

**Never remove:**
- Active containers (web-green, data-refresh-green)
- Current image version (v1.0.5)
- Database files (`visa_bulletin.db`)
- Saved pages directory (`saved_pages/`)
- Logs directory (`logs/`) - unless very old

## Troubleshooting

If cleanup fails:
1. Check which containers are using the images: `sudo docker ps -a`
2. Stop containers first if needed: `sudo docker-compose -f docker-compose.green.yml down`
3. Force remove if necessary: `sudo docker rmi -f <image-id>`
