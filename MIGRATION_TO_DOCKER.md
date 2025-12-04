# Migration Plan: Systemd + Venv → Docker

## Overview

This document outlines the step-by-step migration from the current systemd + virtualenv deployment to Docker-based deployment, with minimal risk and zero downtime.

## Current State (Before Migration)

```
┌─────────────────────────────────────┐
│  Lightsail Instance                 │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  Systemd Service              │ │
│  │  /opt/visa_bulletin/venv      │ │
│  │  gunicorn on port 8000        │ │
│  └───────────────────────────────┘ │
│           ▲                         │
│           │                         │
│  ┌────────┴──────────────────────┐ │
│  │  Nginx (reverse proxy)        │ │
│  │  Port 80/443 → 8000           │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘
```

## Target State (After Migration)

```
┌─────────────────────────────────────┐
│  Lightsail Instance                 │
│                                     │
│  ┌───────────────────────────────┐ │
│  │  Docker Compose               │ │
│  │  ghcr.io/vyakunin/visa_bull.. │ │
│  │  gunicorn on port 8000        │ │
│  └───────────────────────────────┘ │
│           ▲                         │
│           │                         │
│  ┌────────┴──────────────────────┐ │
│  │  Nginx (reverse proxy)        │ │
│  │  Port 80/443 → 8000           │ │
│  └───────────────────────────────┘ │
└─────────────────────────────────────┘
```

## Migration Strategy: Blue-Green with Fallback

We'll run Docker and systemd in parallel initially, allowing instant rollback if issues arise.

## Phase 1: Preparation (Day 0) - 30 minutes

### 1.1 Verify Current System is Healthy

```bash
# SSH into Lightsail
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176

# Check current service status
sudo systemctl status visa-bulletin

# Check site is accessible
curl -I https://visa-bulletin.us

# Check database
sqlite3 /opt/visa_bulletin/visa_bulletin.db "SELECT COUNT(*) FROM bulletin;"

# Note current resource usage
free -h
df -h
```

### 1.2 Backup Everything

```bash
cd /opt/visa_bulletin

# Backup database
mkdir -p backups
sqlite3 visa_bulletin.db ".backup backups/visa_bulletin_pre_docker_$(date +%Y%m%d).db"

# Backup current virtualenv state
pip freeze > backups/requirements_pre_docker.txt

# Backup systemd service file
sudo cp /etc/systemd/system/visa-bulletin.service backups/

# Backup nginx config
sudo cp /etc/nginx/sites-available/visa-bulletin backups/nginx_pre_docker.conf

# Verify backups
ls -lh backups/
```

### 1.3 Install Docker (If Not Already)

```bash
# Check if Docker is already installed
docker --version

# If not, install it
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu

# Install docker-compose
sudo apt install -y docker-compose

# IMPORTANT: Logout and login for group changes
exit
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176

# Verify Docker works
docker run hello-world
docker-compose --version
```

## Phase 2: Install Docker Alongside Current System (Day 0) - 30 minutes

### 2.1 Pull Latest Code

```bash
cd /opt/visa_bulletin
git pull origin main

# Verify docker-compose.yml exists and points to GHCR
cat docker-compose.yml | grep image
# Should show: ghcr.io/vyakunin/visa_bulletin
```

### 2.2 Configure Docker on Different Port (Temporarily)

We'll run Docker on port 8001 initially to not conflict with systemd on 8000:

```bash
# Create temporary docker-compose for parallel testing
cat > docker-compose.test.yml << 'EOF'
version: '3.8'

services:
  web:
    image: ghcr.io/vyakunin/visa_bulletin:${IMAGE_TAG:-latest}
    ports:
      - "8001:8000"  # Note: Different external port
    volumes:
      - ./visa_bulletin.db:/app/visa_bulletin.db
      - ./saved_pages:/app/saved_pages
      - ./logs:/app/logs
    environment:
      - DJANGO_SETTINGS_MODULE=django_config.settings
      - PYTHONUNBUFFERED=1
    restart: unless-stopped
EOF
```

### 2.3 Pull Docker Image

```bash
# Pull latest image from GHCR
# For public repo, no authentication needed
docker-compose -f docker-compose.test.yml pull

# Verify image is pulled
docker images | grep visa_bulletin
```

### 2.4 Start Docker Service (Port 8001)

```bash
# Start Docker service on port 8001
docker-compose -f docker-compose.test.yml up -d

# Check status
docker-compose -f docker-compose.test.yml ps

# Check logs
docker-compose -f docker-compose.test.yml logs -f web
# Press Ctrl+C after verifying startup
```

### 2.5 Test Docker Service

```bash
# Test Docker service on port 8001
curl -I http://localhost:8001

# Compare with systemd service on port 8000
curl -I http://localhost:8000

# Both should return HTTP 200
```

## Phase 3: Parallel Testing (Day 1-7) - 1 week

### 3.1 Monitor Both Services

```bash
# Check systemd service (current production)
sudo systemctl status visa-bulletin
sudo journalctl -u visa-bulletin -n 50

# Check Docker service (testing)
docker-compose -f docker-compose.test.yml ps
docker-compose -f docker-compose.test.yml logs --tail=50 web

# Compare resource usage
free -h
docker stats --no-stream
```

### 3.2 Test Deployments on Docker

```bash
# Test deployment script (will still use systemd)
# We'll manually test Docker deployment

# Pull new image
docker-compose -f docker-compose.test.yml pull

# Restart Docker service
docker-compose -f docker-compose.test.yml up -d

# Verify
curl -I http://localhost:8001
```

### 3.3 Stress Test (Optional)

```bash
# Use ab (Apache Bench) to test both
sudo apt install -y apache2-utils

# Test systemd service
ab -n 1000 -c 10 http://localhost:8000/

# Test Docker service
ab -n 1000 -c 10 http://localhost:8001/

# Compare response times and error rates
```

### 3.4 Daily Checks

For one week, check daily:

```bash
# SSH and run these checks
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176

cd /opt/visa_bulletin

# Check both are running
sudo systemctl status visa-bulletin
docker-compose -f docker-compose.test.yml ps

# Check logs for errors
sudo journalctl -u visa-bulletin --since "1 hour ago" | grep -i error
docker-compose -f docker-compose.test.yml logs --since 1h | grep -i error

# Check resource usage
free -h
df -h
docker stats --no-stream
```

## Phase 4: Cutover to Docker (Day 7) - 15 minutes

Once you're confident Docker is stable:

### 4.1 Update Nginx to Point to Docker

We'll switch traffic from systemd (port 8000) to Docker (port 8001), but keep systemd running as fallback:

```bash
# Backup current nginx config
sudo cp /etc/nginx/sites-available/visa-bulletin /opt/visa_bulletin/backups/nginx_pre_cutover.conf

# Update nginx to point to port 8001 (Docker)
sudo sed -i 's/proxy_pass http:\/\/127.0.0.1:8000;/proxy_pass http:\/\/127.0.0.1:8001;/' /etc/nginx/sites-available/visa-bulletin

# Verify change
sudo grep proxy_pass /etc/nginx/sites-available/visa-bulletin

# Test nginx config
sudo nginx -t

# Reload nginx
sudo systemctl reload nginx
```

### 4.2 Verify Traffic is Going to Docker

```bash
# Check site is working
curl -I https://visa-bulletin.us

# Check Docker logs show new requests
docker-compose -f docker-compose.test.yml logs -f web
# You should see incoming requests
```

### 4.3 Monitor for Issues (1 hour)

Watch for any issues:

```bash
# Monitor Docker logs
docker-compose -f docker-compose.test.yml logs -f web

# Check error logs
sudo tail -f /var/log/nginx/error.log

# In another terminal, check systemd (should see no new requests)
sudo journalctl -u visa-bulletin -f
```

### 4.4 Rollback Procedure (If Needed)

If you encounter issues, rollback is instant:

```bash
# Revert nginx to point back to systemd (port 8000)
sudo sed -i 's/proxy_pass http:\/\/127.0.0.1:8001;/proxy_pass http:\/\/127.0.0.1:8000;/' /etc/nginx/sites-available/visa-bulletin

# Test and reload
sudo nginx -t
sudo systemctl reload nginx

# Verify systemd is serving traffic
curl -I https://visa-bulletin.us
sudo journalctl -u visa-bulletin -f
```

## Phase 5: Switch to Production Docker Setup (Day 7) - 15 minutes

Once cutover is successful and stable:

### 5.1 Stop Docker Test Service

```bash
cd /opt/visa_bulletin

# Stop test service on port 8001
docker-compose -f docker-compose.test.yml down
```

### 5.2 Start Production Docker on Port 8000

```bash
# First, stop systemd service to free port 8000
sudo systemctl stop visa-bulletin
sudo systemctl disable visa-bulletin

# Start production Docker on port 8000
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f web
```

### 5.3 Update Nginx to Port 8000

```bash
# Update nginx back to port 8000 (now served by Docker)
sudo sed -i 's/proxy_pass http:\/\/127.0.0.1:8001;/proxy_pass http:\/\/127.0.0.1:8000;/' /etc/nginx/sites-available/visa-bulletin

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

### 5.4 Verify Everything Works

```bash
# Check site
curl -I https://visa-bulletin.us

# Check Docker logs show traffic
docker-compose logs -f web

# Check all services
docker-compose ps
```

## Phase 6: Cleanup (Day 8+) - 30 minutes

After Docker has been stable for 24+ hours:

### 6.1 Archive Old Systemd Setup

```bash
cd /opt/visa_bulletin

# Move venv to archive (don't delete yet, just in case)
sudo mkdir -p /opt/archive
sudo mv venv /opt/archive/venv_$(date +%Y%m%d)
sudo mv backups /opt/archive/backups_$(date +%Y%m%d)

# Archive systemd service file
sudo mv /etc/systemd/system/visa-bulletin.service /opt/archive/

# Reload systemd
sudo systemctl daemon-reload
```

### 6.2 Update Documentation

```bash
# Update any deployment docs to reference Docker
# The DOCKER_DEPLOYMENT.md is already created

# Add note to DEPLOYMENT.md about migration
cat >> DEPLOYMENT.md << 'EOF'

## Historical Note

As of $(date +%Y-%m-%d), this project migrated from systemd + virtualenv to Docker.
See DOCKER_DEPLOYMENT.md for current deployment instructions.
EOF
```

### 6.3 Test New Deployment Process

```bash
# From local machine, test the new deploy script
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem

# This should now use Docker instead of systemd
```

### 6.4 Update Cron Jobs

The data-refresh cron job is now handled by the `data-refresh` Docker service, but verify:

```bash
# Check cron jobs
crontab -l

# If there's still a cron job for refresh_data_incremental, you can remove it
# The docker-compose.yml has a data-refresh service that handles this

# Edit crontab
crontab -e
# Comment out or remove the old refresh_data_incremental line
```

## Phase 7: Complete Archive (Day 30+) - Optional

After a month of stable Docker operation:

### 7.1 Final Cleanup

```bash
# If Docker has been stable for 30+ days, remove archived files
sudo rm -rf /opt/archive/venv_*

# Keep backups though
# Consider moving to S3 or another backup location
```

## Rollback Plan (Emergency)

If Docker completely fails after migration:

### Emergency Rollback to Systemd

```bash
# Stop Docker
cd /opt/visa_bulletin
docker-compose down

# Restore venv from archive
sudo cp -r /opt/archive/venv_YYYYMMDD venv

# Restore systemd service
sudo cp /opt/archive/visa-bulletin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable visa-bulletin
sudo systemctl start visa-bulletin

# Update nginx to port 8000 (if needed)
sudo sed -i 's/proxy_pass http:\/\/127.0.0.1:8001;/proxy_pass http:\/\/127.0.0.1:8000;/' /etc/nginx/sites-available/visa-bulletin
sudo nginx -t
sudo systemctl reload nginx

# Verify
curl -I https://visa-bulletin.us
sudo systemctl status visa-bulletin
```

## Success Criteria

The migration is successful when:

- [ ] Docker service runs for 7+ days without issues
- [ ] Deployments using `deploy.sh` work correctly
- [ ] Memory usage is lower than systemd (no build tools on prod)
- [ ] Response times are comparable or better
- [ ] No increase in error rates
- [ ] Rollbacks are fast (< 2 minutes)

## Monitoring Checklist

During and after migration, monitor:

- [ ] HTTP response codes (should all be 200/30x)
- [ ] Response times (< 500ms for most pages)
- [ ] Memory usage (should be lower than before)
- [ ] Disk usage (Docker images ~500MB)
- [ ] Error logs (Nginx + Docker)
- [ ] Uptime monitoring (UptimeRobot, etc.)

## Key Contacts and Resources

- **Deployment Script**: `scripts/deploy.sh`
- **Docker Documentation**: `DOCKER_DEPLOYMENT.md`
- **Nginx Config**: `deployment/nginx/visa-bulletin-nginx.conf`
- **GitHub Actions**: `.github/workflows/`

## Timeline Summary

| Phase | Duration | Key Activity | Can Rollback? |
|-------|----------|--------------|---------------|
| 1: Preparation | 30 min | Backup, install Docker | N/A |
| 2: Install Parallel | 30 min | Docker on port 8001 | Yes (instant) |
| 3: Testing | 7 days | Monitor both systems | Yes (instant) |
| 4: Cutover | 15 min | Switch nginx to Docker | Yes (instant) |
| 5: Production Setup | 15 min | Docker on port 8000 | Yes (< 5 min) |
| 6: Cleanup | 30 min | Archive old setup | Yes (< 10 min) |
| 7: Final Cleanup | Optional | Delete archives | No (but low risk) |

**Total Active Work Time**: ~2 hours  
**Total Calendar Time**: 7-30 days (mostly passive monitoring)

## Risk Mitigation

1. **Parallel deployment**: Run both systems simultaneously
2. **Instant rollback**: Nginx config change takes < 30 seconds
3. **Keep systemd**: Archive but don't delete for 30 days
4. **Backups**: Database and configs backed up before migration
5. **Testing period**: 7 days of monitoring before full cutover

## Post-Migration Benefits

After successful migration:

- ✅ **Lower memory**: No build tools on production
- ✅ **Faster deploys**: Pull image instead of pip install
- ✅ **Easy rollbacks**: Just change IMAGE_TAG
- ✅ **Reproducible**: Same image everywhere
- ✅ **CI/CD**: GitHub Actions handles builds
- ✅ **Better DX**: Same environment local and prod

## Questions?

If you encounter issues during migration, refer to:
- `DOCKER_DEPLOYMENT.md` - Full Docker setup guide
- `scripts/deploy.sh` - Automated deployment
- GitHub Issues - Report problems

Good luck with the migration! 🚀

