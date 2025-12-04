# Docker-Based Deployment Guide

## Overview

This guide covers the Docker-based deployment strategy for the Visa Bulletin Dashboard. Docker deployment solves the memory constraints on Lightsail by moving the Bazel build process to GitHub Actions.

## Architecture

```
┌─────────────────────┐    ┌──────────────────┐    ┌──────────────────┐
│  Local Development  │    │  GitHub Actions  │    │  Lightsail Prod  │
│  Bazel + Docker     │ →  │  GHCR Registry   │ →  │  Docker Compose  │
│  (testing)          │    │  (image storage) │    │  (runtime only)  │
└─────────────────────┘    └──────────────────┘    └──────────────────┘
```

## Why Docker?

### Problems Solved

1. **Memory constraints**: Bazel builds in CI, not on production server
2. **Reproducibility**: Immutable Docker images ensure consistent deployments
3. **Fast rollbacks**: Just run a previous image tag
4. **Faster deploys**: `docker pull` is faster than `pip install`

### Tradeoffs

**Advantages**:
- Lower memory footprint on prod (no build tools needed)
- Immutable deployments (no state drift)
- Easy rollbacks (`docker-compose up -d` with different tag)
- Faster deployment (pull pre-built image)

**Disadvantages**:
- Higher disk usage (~500MB for images vs ~100MB venv)
- More complexity (registry, image management)
- Requires Docker setup on prod

## GitHub Container Registry (GHCR)

We use GHCR because:
- **Free** for public repos (generous limits for private)
- **Integrated** with GitHub (no separate account needed)
- **Automatic** authentication via GitHub Actions
- **Semantic versioning** support

## Development Workflow

### Local Development (Without Docker)

```bash
# Use Bazel as usual
bazel test //tests:...
bazel run //:runserver
```

### Local Development (With Docker)

```bash
# Build and run locally
docker-compose -f docker-compose.dev.yml up

# Or build image locally
docker build -t visa-bulletin:local .
docker run -p 8000:8000 visa-bulletin:local
```

## Production Deployment

### Prerequisites on Lightsail

1. **Docker installed**
2. **Git configured** for pulling code
3. **Nginx configured** as reverse proxy
4. **SSL certificates** via Certbot

### Initial Setup (One-Time)

#### 1. Install Docker on Lightsail

```bash
# SSH into Lightsail
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@YOUR_IP

# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Add user to docker group
sudo usermod -aG docker ubuntu

# Install docker-compose
sudo apt install -y docker-compose

# Logout and login to apply group changes
exit
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@YOUR_IP

# Verify installation
docker --version
docker-compose --version
```

#### 2. Configure GitHub Container Registry Access

GHCR images can be:
- **Public**: Anyone can pull (recommended for open source)
- **Private**: Requires authentication token

For public repos, no authentication needed on prod.

For private repos:

```bash
# On Lightsail
# Create GitHub Personal Access Token with read:packages permission
# Then login:
echo $GITHUB_TOKEN | docker login ghcr.io -u USERNAME --password-stdin
```

#### 3. Pull Repository

```bash
# If not already done
cd /opt
sudo git clone https://github.com/vyakunin/visa_bulletin.git
cd visa_bulletin
sudo chown -R ubuntu:ubuntu /opt/visa_bulletin
```

#### 4. Setup Environment Variables

```bash
cd /opt/visa_bulletin

# Create .env file with secrets
cat > .env << EOF
DJANGO_SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
DEBUG=False
ALLOWED_HOSTS=visa-bulletin.us,www.visa-bulletin.us
EOF

chmod 600 .env
```

#### 5. Pull and Start Services

```bash
# Pull latest image
docker-compose pull

# Start services
docker-compose up -d

# Check status
docker-compose ps
docker-compose logs -f
```

#### 6. Setup Nginx Reverse Proxy

Nginx configuration should already be in place from git pull. Ensure it's active:

```bash
# Copy nginx config
sudo cp deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/

# Test and reload
sudo nginx -t
sudo systemctl reload nginx
```

#### 7. Setup SSL (HTTPS)

```bash
# Install certbot if not already
sudo apt install -y certbot python3-certbot-nginx

# Get SSL certificate
sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us
```

### Deploying Updates

#### Method 1: Using deploy.sh Script (Recommended)

```bash
# From local machine
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem

# Or deploy specific version
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem v1.2.3
```

The script automatically:
- Pulls latest configs from GitHub
- Pulls new Docker image from GHCR
- Updates Nginx configuration
- Handles SSL certificates
- Restarts services
- Checks health

#### Method 2: GitHub Actions (Automated)

Deployment can be triggered from GitHub Actions:

**Via Web Interface:**
1. Go to: GitHub → Actions → Deploy to Production → Run workflow
2. Choose version tag to deploy
3. Click "Run workflow"

**Via Command Line (using GitHub CLI):**
```bash
# Deploy specific version
gh workflow run deploy-production.yml -f version=v1.2.3

# Deploy latest
gh workflow run deploy-production.yml -f version=latest

# Watch progress
gh run watch
```

#### Method 3: Manual Deployment

```bash
# SSH into Lightsail
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@YOUR_IP

# Pull latest configs
cd /opt/visa_bulletin
git pull origin main

# Pull new image (optional: specify version)
export IMAGE_TAG=v1.2.3  # or 'latest'
docker-compose pull

# Restart services
docker-compose up -d

# Check logs
docker-compose logs -f web
```

## Building and Pushing Images

### Automatic (GitHub Actions)

Images are automatically built and pushed when:

1. **On push to main**: Creates image with tag `main-<git-sha>`
2. **On version tag**: Creates versioned images (e.g., `v1.2.3`, `v1.2`, `v1`, `latest`)

To trigger a release:

```bash
# Tag a release
git tag -a v1.2.3 -m "Release version 1.2.3"
git push origin v1.2.3

# GitHub Actions will:
# 1. Build Docker image with Bazel
# 2. Push to ghcr.io/vyakunin/visa_bulletin:v1.2.3
# 3. Also tag as v1.2, v1, and latest
```

### Triggering Deployment from Command Line

You can also trigger the deployment workflow from your terminal using GitHub CLI:

```bash
# Install GitHub CLI (one-time setup)
# macOS:
brew install gh

# Linux:
# See: https://github.com/cli/cli/blob/trunk/docs/install_linux.md

# Authenticate (one-time setup)
gh auth login

# Trigger deployment with specific version
gh workflow run deploy-production.yml -f version=v1.2.3

# Or deploy latest
gh workflow run deploy-production.yml -f version=latest

# Check workflow status
gh run list --workflow=deploy-production.yml

# Watch workflow in real-time
gh run watch
```

### Manual (Local Build)

For testing or emergency deployments:

```bash
# Build image locally
docker build -t ghcr.io/vyakunin/visa_bulletin:test .

# Login to GHCR
echo $GITHUB_TOKEN | docker login ghcr.io -u vyakunin --password-stdin

# Push to registry
docker push ghcr.io/vyakunin/visa_bulletin:test
```

## GitHub Actions Setup

### Required Secrets

Add these to GitHub repository secrets (Settings → Secrets and variables → Actions):

1. `LIGHTSAIL_SSH_KEY`: Private SSH key for Lightsail instance
2. `LIGHTSAIL_IP`: IP address of Lightsail instance (or use DNS name)

Note: `GITHUB_TOKEN` is automatically provided by GitHub Actions.

### Workflows

Two workflows are configured:

1. **docker-build-push.yml**: Builds and pushes images to GHCR
2. **deploy-production.yml**: Deploys to Lightsail (manual trigger or auto after build)

## Image Tagging Strategy

We use semantic versioning:

| Git Event | Docker Tags Created |
|-----------|-------------------|
| Push to main | `main-abc1234` (git SHA) |
| Tag v1.2.3 | `v1.2.3`, `v1.2`, `v1`, `latest` |

Examples:
- `latest`: Most recent stable release
- `v1.2.3`: Specific version
- `v1.2`: Latest patch of v1.2.x
- `v1`: Latest minor of v1.x.x
- `main-abc1234`: Specific commit from main branch

## Managing Docker Services

### Common Commands

```bash
# View running containers
docker-compose ps

# View logs
docker-compose logs -f
docker-compose logs -f web          # Just web service
docker-compose logs --tail=50 web   # Last 50 lines

# Restart services
docker-compose restart

# Stop services
docker-compose down

# Start services
docker-compose up -d

# Pull latest image
docker-compose pull

# Update to specific version
IMAGE_TAG=v1.2.3 docker-compose pull
IMAGE_TAG=v1.2.3 docker-compose up -d
```

### Monitoring

```bash
# Check Docker disk usage
docker system df

# Clean up old images (saves space)
docker system prune -a

# View resource usage
docker stats
```

## Rollback Procedure

If a deployment fails:

### Option 1: Quick Rollback (Using Previous Image)

```bash
# On Lightsail
cd /opt/visa_bulletin

# Deploy previous version
export IMAGE_TAG=v1.2.2  # Or whatever previous version
docker-compose up -d

# Verify
curl https://visa-bulletin.us
```

### Option 2: Emergency Fallback (Use Systemd + Venv)

If Docker is completely broken, you can temporarily fall back to the old systemd setup:

```bash
# Stop Docker services
docker-compose down

# Start systemd service
sudo systemctl start visa-bulletin

# Check status
sudo systemctl status visa-bulletin
```

(See MIGRATION.md for maintaining parallel deployments during transition)

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose logs web

# Check if port is in use
sudo netstat -tulpn | grep 8000

# Restart with fresh containers
docker-compose down
docker-compose up -d
```

### Image Pull Fails

```bash
# Check GHCR access
docker pull ghcr.io/vyakunin/visa_bulletin:latest

# For private repos, ensure logged in
echo $GITHUB_TOKEN | docker login ghcr.io -u vyakunin --password-stdin
```

### Database Issues

```bash
# Check if database file exists
ls -lh visa_bulletin.db*

# Verify WAL mode
docker-compose exec web sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
# Should output: wal

# Run migrations
docker-compose exec web python manage.py migrate
```

### Out of Memory

```bash
# Check container memory
docker stats

# Add swap space on Lightsail
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### Disk Space Issues

```bash
# Check disk usage
df -h
docker system df

# Clean up old images
docker system prune -a --force

# Remove specific old images
docker images
docker rmi ghcr.io/vyakunin/visa_bulletin:OLD_TAG
```

## Security Best Practices

1. **Environment Variables**: Store secrets in `.env` file, not in code
2. **Non-root User**: Docker image runs as `visabulletin` user
3. **SSL Certificates**: Always use HTTPS in production
4. **Image Signing**: Consider signing images for verification
5. **Regular Updates**: Keep Docker and base images updated

## Performance Optimization

### Image Size

Current image size: ~500MB (Debian + Python + dependencies)

To reduce:
```dockerfile
# Already using multi-stage build
# Already using slim base images
# Consider alpine for even smaller size (be careful with compatibility)
```

### Startup Time

Current startup: ~5-10 seconds

Optimizations in place:
- Pre-built images (no compilation on prod)
- Gunicorn with worker preloading
- Health checks with appropriate grace period

## Monitoring and Maintenance

### Daily Tasks

- None! Automated via cron job in `data-refresh` container

### Weekly Tasks

```bash
# Check logs for errors
docker-compose logs --tail=100 web | grep -i error

# Check disk space
docker system df
df -h /opt/visa_bulletin
```

### Monthly Tasks

```bash
# Update base system
sudo apt update && sudo apt upgrade -y

# Clean up old Docker images
docker system prune -a --volumes

# Backup database
cd /opt/visa_bulletin
sqlite3 visa_bulletin.db ".backup backups/visa_bulletin_$(date +%Y%m%d).db"
find backups/ -mtime +30 -delete  # Keep 30 days
```

## Cost Analysis

| Component | Cost |
|-----------|------|
| Lightsail $5/month instance | $5.00 |
| GHCR (public repo) | $0.00 |
| GitHub Actions (public repo) | $0.00 |
| Domain (optional) | $0.67/month |
| **Total** | **$5-6/month** |

## Next Steps

1. Complete initial Docker setup on Lightsail
2. Test deployment with `deploy.sh`
3. Monitor for 1 week alongside systemd
4. Once stable, retire systemd service
5. Setup automated monitoring (UptimeRobot, etc.)

## References

- [Dockerfile](Dockerfile) - Multi-stage build with Bazel
- [docker-compose.yml](docker-compose.yml) - Production compose file
- [docker-compose.dev.yml](docker-compose.dev.yml) - Development compose file
- [scripts/deploy.sh](scripts/deploy.sh) - Deployment script
- [.github/workflows/](..github/workflows/) - CI/CD workflows

