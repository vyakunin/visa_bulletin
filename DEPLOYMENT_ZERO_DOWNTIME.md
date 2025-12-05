# Zero-Downtime Blue-Green Deployment

This document explains the zero-downtime deployment strategy for visa-bulletin.

## Overview

The blue-green deployment approach eliminates downtime by running two separate environments and switching between them atomically.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                         Nginx (Port 443)                     │
│                   proxy_pass to :8000 or :8001               │
└────────────────────────┬────────────────────────────────────┘
                         │
          ┌──────────────┴──────────────┐
          │                             │
┌─────────▼────────┐          ┌─────────▼────────┐
│ Blue Environment │          │ Green Environment │
│   Port 8000      │          │   Port 8001       │
│                  │          │                   │
│ web-blue         │          │ web-green         │
│ refresh-blue     │          │ refresh-green     │
└──────────────────┘          └───────────────────┘
          │                             │
          └──────────────┬──────────────┘
                         │
               ┌─────────▼─────────┐
               │ Shared Resources  │
               │                   │
               │ visa_bulletin.db  │
               │ saved_pages/      │
               │ logs/             │
               └───────────────────┘
```

## Files

### Docker Compose Configurations

**`docker-compose.blue.yml`**
- Runs on port 8000
- Container names: `visa_bulletin_web_blue`, `visa_bulletin_refresh_blue`
- Health checks enabled

**`docker-compose.green.yml`**
- Runs on port 8001
- Container names: `visa_bulletin_web_green`, `visa_bulletin_refresh_green`
- Health checks enabled

### Deployment Script

**`scripts/deploy-zero-downtime.sh`**
- Orchestrates blue-green deployment
- Automatic active environment detection
- Health check validation
- Atomic Nginx switching
- Automatic rollback on failure

## Deployment Flow

### Step-by-Step Process

1. **Detect Active Environment**
   ```bash
   # Script checks Nginx config
   grep proxy_pass nginx/visa-bulletin-locations.conf
   # → 8000 = blue active, 8001 = green active
   ```

2. **Deploy to Inactive Environment**
   ```bash
   # If blue is active (8000), deploy to green (8001)
   IMAGE_TAG=1.2.3 docker-compose -f docker-compose.green.yml up -d
   ```

3. **Wait for Health Checks**
   ```bash
   # Waits up to 60 seconds for healthy status
   # Checks: docker-compose ps | grep healthy
   ```

4. **Switch Nginx Proxy**
   ```bash
   # Update proxy from :8000 → :8001 (or vice versa)
   sed -i 's/:8000/:8001/' nginx/visa-bulletin-locations.conf
   systemctl reload nginx  # Zero-downtime reload
   ```

5. **Stop Old Environment**
   ```bash
   # After 10 seconds of traffic validation
   docker-compose -f docker-compose.blue.yml down
   ```

### Timeline

```
Time    Blue (8000)         Green (8001)        Nginx       Traffic
────────────────────────────────────────────────────────────────────
0:00    Running v1.0.0      Stopped             →8000       100% → Blue
0:01    Running v1.0.0      Starting v1.0.1     →8000       100% → Blue
0:15    Running v1.0.0      Healthy v1.0.1      →8000       100% → Blue
0:16    Running v1.0.0      Healthy v1.0.1      →8001       100% → Green ⚡
0:26    Stopping            Healthy v1.0.1      →8001       100% → Green
0:27    Stopped             Running v1.0.1      →8001       100% → Green

Next deployment will go: Green → Blue (8001 → 8000)
```

## Usage

### Basic Deployment

```bash
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin 1.2.3
```

### Full Deployment Example

```bash
# 1. Tag release
git tag -a v1.2.3 -m "Release 1.2.3: New feature"
git push origin v1.2.3

# 2. Wait for GitHub Actions to build image

# 3. Deploy with zero downtime
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin 1.2.3
```

## Health Checks

Each container has a health check that validates:

```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/dashboard/"]
  interval: 10s
  timeout: 5s
  retries: 3
  start_period: 10s
```

**What's Validated:**
- Container is running
- Gunicorn is serving requests
- Django app is responding
- Database connection works
- Dashboard route is accessible

## Rollback

### Automatic Rollback

If health checks fail, the script automatically:
1. Stops the new environment
2. Keeps the old environment running
3. No changes to Nginx (still pointing to old version)
4. Exit with error code

### Manual Rollback

To switch back to the other environment:

```bash
# Check which is currently active
ssh lightsail "grep proxy_pass /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf"

# Switch back
ssh lightsail "sudo sed -i 's/:8001/:8000/' /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf"
ssh lightsail "sudo systemctl reload nginx"
```

## Troubleshooting

### Issue: Both environments running

```bash
# Check status
docker ps | grep visa_bulletin

# Stop one environment
docker-compose -f docker-compose.blue.yml down
# OR
docker-compose -f docker-compose.green.yml down
```

### Issue: Health checks not passing

```bash
# Check container logs
docker-compose -f docker-compose.green.yml logs web-green

# Check container status
docker-compose -f docker-compose.green.yml ps

# Test health check manually
curl http://localhost:8001/dashboard/
```

### Issue: Can't determine active environment

```bash
# Check Nginx config
cat /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf | grep proxy_pass

# Manually set active
sudo sed -i 's/proxy_pass .*/proxy_pass http:\/\/127.0.0.1:8000;/' \
  /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf
sudo systemctl reload nginx
```

## Resource Usage

### During Deployment (Brief)
- **Web containers:** 2 (both blue and green)
- **Refresh containers:** 2 (both blue and green)
- **Memory:** ~400MB total (200MB × 2)
- **Duration:** ~15-30 seconds

### Normal Operation
- **Web containers:** 1 (blue or green)
- **Refresh containers:** 1 (blue or green)
- **Memory:** ~200MB total

### Shared Resources (No Duplication)
- Database: `visa_bulletin.db` (shared volume)
- Cached pages: `saved_pages/` (shared volume)
- Logs: `logs/` (shared volume)

## Benefits

✅ **Zero Downtime**
- No service interruption
- No dropped connections
- No failed requests

✅ **Safe Deployments**
- New version validated before switch
- Automatic rollback on failure
- Old version keeps running if issues

✅ **Fast Rollback**
- Just switch Nginx back
- No need to rebuild/restart
- Both versions remain available briefly

✅ **Confidence**
- Health checks ensure readiness
- Traffic validation before cleanup
- Clear success/failure feedback

## First-Time Setup

If this is your first blue-green deployment:

1. **Initial deployment:**
   ```bash
   # Will detect no active environment and deploy to blue (8000)
   ./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin latest
   ```

2. **Stop any old containers (if they exist):**
   ```bash
   ssh lightsail "cd /opt/visa_bulletin && docker-compose down"
   ```

3. **All future deployments:**
   ```bash
   # Will alternate between blue and green automatically
   ./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin <version>
   ```

## Why Blue-Green?

**Benefits:**
- ✅ **Zero downtime** - No service interruption
- ✅ **Lower risk** - Automatic rollback on failure
- ✅ **Health validation** - New version tested before switch
- ✅ **Fast rollback** - Just switch Nginx back
- ✅ **Production-ready** - Safe for live traffic

**Resource Usage:**
- During deployment: 2x containers (~400MB RAM) for 15-30 seconds
- Normal operation: 1x container (~200MB RAM)
- Database shared (no duplication)
