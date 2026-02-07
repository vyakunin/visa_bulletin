# Deployment Configuration Files

This directory contains production deployment configurations for the Visa Bulletin Dashboard.

## 🎉 Production Status

**LIVE:** https://visa-bulletin.us  
**Platform:** AWS Lightsail (2GB RAM)  
**Database:** PostgreSQL with blue-green deployment  
**Container:** Docker with Gunicorn  

### Instances and SSH

| Alias | IP | Purpose |
|-------|-----|---------|
| `prod_2Gb_vm` | 44.209.204.255 | Production |
| `backup_0_5Gb_vm` | 3.227.71.176 | Backup |
| `staging_2Gb_vm` | 54.196.241.197 | Staging |

Use `ssh staging_2Gb_vm` for babysitting or running refresh on staging.  

### AWS IAM (Lightsail CLI)

IAM user **`visa-bulletin-deploy`** has Lightsail full access (`lightsail:*`) for instances and static IPs. Use the named profile so you don’t rely on SSO login:

```bash
export AWS_PROFILE=visa-bulletin-deploy
aws lightsail get-instances --region us-east-1
aws lightsail get-static-ips --region us-east-1
aws lightsail get-instance-metric-data --instance-name VisaBulletin2GB --metric-name CPUUtilization ...
```

Profile is configured in `~/.aws/credentials` as `[visa-bulletin-deploy]`. Policy source: `deployment/iam-lightsail-policy.json`.

## 📁 Directory Structure

```
deployment/
├── docker-compose.blue.yml    # Blue environment (port 8000)
├── docker-compose.green.yml   # Green environment (port 8001)
├── nginx/                     # Nginx reverse proxy configs
│   ├── visa-bulletin-nginx.conf      # Site block; uses main_timed + locations
│   ├── visa-bulletin-locations.conf  # Location blocks; bot limit_req
│   ├── visa-bulletin-log-format.conf # Log format with $request_time (→ conf.d)
│   ├── gptbot-rate-limit.conf        # Bots 0.1 qps per IP (→ conf.d)
│   └── rate-limiting.conf            # Optional general rate limits
├── cron/                      # Cron job setup
│   └── setup-ingest-cron.sh
├── iam-lightsail-policy.json  # IAM policy for visa-bulletin-deploy user (lightsail:*)
└── README.md                  # This file
```

## 🚀 Production Architecture

### Components

1. **Application Server**: Docker + Gunicorn
2. **Reverse Proxy**: Nginx with SSL
3. **Database**: PostgreSQL (blue-green)
4. **Data Refresh**: Cron (weekly, pre-built binaries)
5. **Caching**: Django default cache (Redis when `REDIS_URL` is set, else LocMem). Nginx adds `Cache-Control` for HTML.

### Server Specs

- **AWS Lightsail**: 2GB RAM / 60GB SSD
- **OS**: Ubuntu 22.04 LTS
- **Static IP**: Attached (survives reboots)

### Memory Optimizations

The 2GB instance requires careful memory management:

| Component | Limit | Purpose |
|-----------|-------|---------|
| Swap | 2GB | Prevent OOM kills |
| Swappiness | 60 | Swap before OOM |
| Bazel | 1GB RAM, 2 jobs | Limit build memory |
| PostgreSQL | Tuned for bulk ops | Reduce autovacuum spikes |

## Caching (production)

### Current setup

| Layer | TTL | Where |
|-------|-----|--------|
| **Django @cache_page** | 24 h | `CACHE_TIMEOUT` in `django_config/settings.py`; backend Redis (if `REDIS_URL`) or LocMem |
| **Nginx response header** | 3 h | `Cache-Control: public, max-age=10800` in `deployment/nginx/visa-bulletin-locations.conf` for `location /` |
| **Static assets** | 30 d / 1 y | `/static/` 30d; versioned CSS/JS 1y immutable |

So for a URL like **https://visa-bulletin.us/salaries/**:
- **Client/browser** is told to cache the HTML for **3 hours** (max-age=10800).
- **Server-side** (Django) caches the rendered page for **24 hours** (Redis or LocMem).

### Seeing current state and TTL

**1. HTTP cache headers (any URL)**  
Shows what clients and CDNs see:

```bash
curl -sI "https://visa-bulletin.us/salaries/"
```

Look at `Cache-Control`, `Expires`, and optionally `Age` (if a CDN adds it).

**2. Server-side cache (Django key existence + Redis TTL)**  
For a specific path, see if the key exists and (with Redis) remaining TTL:

```bash
# Local (LocMem): key exists, no TTL shown
bazel run //scripts/cache:inspect_cache -- /salaries/

# Production: use domain so cache key matches nginx Host
SITE_DOMAIN=visa-bulletin.us bazel run //scripts/cache:inspect_cache -- /salaries/
# or
bazel run //scripts/cache:inspect_cache -- /salaries/ --domain visa-bulletin.us
```

On production over SSH (with `.env` and Redis):

```bash
ssh prod_2Gb_vm "cd /opt/visa_bulletin && set -a && source .env && set +a && \
  bazel run //scripts/cache:inspect_cache -- /salaries/ --domain visa-bulletin.us"
```

Output: backend name, key exists (yes/no), and for Redis: TTL in seconds and human-readable (e.g. `2h 15m left`).

**3. Clear cache**  
After data refresh or deploy that changes cached payloads:

```bash
bazel run //scripts:clear_cache
```

With LocMem, reload Gunicorn so workers see cleared cache; with Redis, no restart needed.

## 🐳 Building the Docker Image

The image is built in **GitHub Actions** on push to `main` or on version tags. Local build is optional.

### Option A: Build in CI (recommended)

1. **Trigger on push to main** (tag: `main-<sha>`):
   ```bash
   git push origin main
   ```
2. **Trigger on version tag** (tags: `v1.2.3`, `v1.2`, `v1`, `latest`):
   ```bash
   git tag -a v1.2.3 -m "Release 1.2.3"
   git push origin v1.2.3
   ```
3. In GitHub: **Actions** → **Build and Push Docker Image** → confirm the run and that the image was pushed to GHCR.

### Option B: Build locally

Requires Docker daemon running.

```bash
cd /opt/visa_bulletin   # or your repo root
docker build -t visa-bulletin:local .
```

To test the image locally: `docker run -p 8000:8000 -e DB_HOST=host.docker.internal -e ... visa-bulletin:local` (set required env vars or use a `.env` file).

**Note:** The Dockerfile runs Bazel inside the container; the first build can take ~10–15 minutes. Linux hosts (and CI) use a Linux Bazel build; `tools/homebrew.bzl` is skipped in Docker/CI so the image builds without Homebrew.

## 🚀 Quick Deployment

### New Instance Setup

```bash
# Clone repo and run automated setup
git clone https://github.com/vyakunin/visa_bulletin.git /opt/visa_bulletin
cd /opt/visa_bulletin
./scripts/setup_new_instance.sh
```

The setup script configures:
- System packages
- Swap (2GB, swappiness=60)
- Docker
- PostgreSQL (optimized for bulk operations)
- Blue-green databases
- Monitoring (sysstat, atop, health_check.sh)
- Bazel memory limits

### Zero-Downtime Deployment

```bash
# From your local machine
./scripts/deploy-zero-downtime.sh ~/.ssh/lightsail_visa_bulletin v1.2.3
```

This script:
1. Deploys to inactive environment (blue or green)
2. Waits for health checks
3. Atomically switches Nginx proxy
4. Stops old environment

## 📋 Manual Setup Steps

If not using the automated script, see `docs/deployment/NEW_INSTANCE_SETUP.md` for detailed manual steps.

### Key Files to Configure

1. **`.env`** - Database credentials, Django settings
2. **`.bazelrc`** - Memory limits for builds
3. **`/etc/postgresql/14/main/conf.d/custom.conf`** - PostgreSQL tuning (source: `deployment/postgres/conf.d/custom.conf`; copy then `sudo systemctl restart postgresql`)

## 🔧 Management Commands

### Service Management

```bash
# Check running containers
docker ps

# View logs
docker-compose -f deployment/docker-compose.blue.yml logs -f

# Restart service
docker-compose -f deployment/docker-compose.blue.yml restart web-blue
```

### Database Operations

```bash
# Connect to PostgreSQL
sudo -u postgres psql -d visa_bulletin_blue

# Check database size
sudo -u postgres psql -c "SELECT pg_size_pretty(pg_database_size('visa_bulletin_blue'));"

# Run VACUUM ANALYZE after bulk operations
sudo -u postgres psql -d visa_bulletin_blue -c "VACUUM ANALYZE;"
```

### Data Refresh

```bash
# Manual refresh (uses pre-built binaries)
/opt/visa_bulletin/scripts/cron/refresh_data.sh

# Pre-build binaries (run once after setup)
/opt/visa_bulletin/scripts/cron/build_all.sh
```

## 📊 Monitoring

### Health Check Log

```bash
# View health metrics (CPU, MEM, SWAP, LOAD)
cat /var/log/health_check.log | tail -20
```

### System Metrics (sar)

```bash
# Memory usage
sar -r

# CPU usage
sar -u

# Swap activity
sar -W
```

### Process Monitoring (atop)

```bash
# Replay historical data
atop -r /var/log/atop/atop_$(date +%Y%m%d)
```

### PostgreSQL

```bash
# Check active queries
sudo -u postgres psql -c "SELECT * FROM pg_stat_activity WHERE state = 'active';"

# Check autovacuum
sudo -u postgres psql -c "SELECT * FROM pg_stat_user_tables ORDER BY last_autovacuum DESC LIMIT 5;"
```

## 🐛 Troubleshooting

### External access returns 400 Bad Request (DisallowedHost)

If `curl http://<instance-ip>/` returns **400** while `curl -H 'Host: localhost' http://127.0.0.1:8000/` returns **200**, Django is rejecting the request because the instance IP is not in `ALLOWED_HOSTS`.

**Fix on existing instances:**

1. Add the instance public IP to `.env`:
   ```bash
   # On the instance (replace with your static IP)
   sed -i 's/^ALLOWED_HOSTS=.*/ALLOWED_HOSTS=localhost,127.0.0.1,54.196.241.197/' /opt/visa_bulletin/.env
   ```
2. Restart the web container so it picks up the env:
   ```bash
   cd /opt/visa_bulletin && docker-compose -f deployment/docker-compose.blue.yml up -d --force-recreate web-blue
   ```

**New setups:** `scripts/setup_new_instance.sh` now detects the instance public IP (AWS metadata or ifconfig.me) and adds it to `ALLOWED_HOSTS` when creating `.env`.

**Blue-green rotation:** If `nginx -t` fails with "zero size shared memory zone gptbot", ensure the bot rate-limit config is present: `sudo cp deployment/nginx/gptbot-rate-limit.conf /etc/nginx/conf.d/` (setup_new_instance.sh does this; older instances may need it copied manually).

### SSH Timeout / Instance Freeze

1. Check AWS CloudWatch metrics for CPU/memory spikes
2. Review `/var/log/health_check.log` for trends before freeze
3. Check `atop` logs for process-level activity
4. If OOM suspected, review `dmesg | grep -i oom`

### High Memory Usage

```bash
# Check memory
free -h

# Check swap
swapon --show

# Check PostgreSQL memory
sudo -u postgres psql -c "SHOW shared_buffers; SHOW work_mem;"
```

### Slow Performance

```bash
# Check load average
cat /proc/loadavg

# Check disk I/O
sar -d

# Check PostgreSQL locks
sudo -u postgres psql -c "SELECT * FROM pg_locks WHERE NOT granted;"
```

### Analyzing slow requests (prod logs)

**What “slow” means:** Sub-second times (e.g. 0.5–0.7s) are **not** slow. We treat **>5s** as slow and **>8s** as worth careful investigation (build_charts or stats bottleneck; see `docs/EMPLOYER_PROFILE_QUERIES_AND_OPTIMIZATION.md`).

**Which views have app-level timing:** Only the **employer profile** view (`/employer/<slug>/`) logs request timing under the `[employer_profile]` prefix (e.g. `page_total`, `build_charts`, `stats_compute_total`). Job title profile, salary search, homepage, employment-based, directories, and APIs do **not** have similar instrumentation. For those, use **Nginx** access logs (see below) if `main_timed` is enabled, or add timing logs to the view.

**Fetch app logs:**

- **Systemd (current prod):** `ssh prod_2Gb_vm "journalctl -u visa-bulletin-web.service --no-pager -n 3000"`
- **Docker (if using blue/green):** `ssh prod_2Gb_vm "docker logs visa_bulletin_web_blue --tail=3000"` or `docker-compose -f deployment/docker-compose.blue.yml logs --tail=3000 web-blue`

**Find slow requests:**

1. **Application timing (employer profile only):** Filter by `[employer_profile]` and `page_total`:
   ```bash
   ssh prod_2Gb_vm "journalctl -u visa-bulletin-web.service --no-pager -n 5000" | grep -E "\[employer_profile\] page_total"
   ```
   Lines show `slug=... cache_hit=... took X.XXXs`. Sort by time to see slowest: `grep ... | grep -oE 'took [0-9.]+s' | sort -t' ' -k2 -rn`.

2. **All views (Nginx access log with response time):** If Nginx uses `main_timed` (see `deployment/nginx/visa-bulletin-log-format.conf`), `access.log` has `$request_time` as the 6th field. Sort by it to find slow requests for any path (homepage, salary search, job-title, employment-based, etc.):
   ```bash
   ssh prod_2Gb_vm "sudo awk '{print \$6, \$0}' /var/log/nginx/access.log | sort -rn | head -50"
   ```
   Or filter by path then sort: `sudo grep 'GET /salaries/' /var/log/nginx/access.log | awk '{print $6, $0}' | sort -rn | head -20`.

3. **Gunicorn access log (if response time in format):** When gunicorn is started with `--access-log-format` including `%(L)s`, the last column is response time in seconds. Systemd prod currently uses default format (no `%(L)s`), so response time is not in app logs; use Nginx `main_timed` for per-request time for all views.

4. **Django request log:** 500s and long requests:
   ```bash
   ssh prod_2Gb_vm "journalctl -u visa-bulletin-web.service --no-pager -n 5000" | grep -E "django.request|ERROR|Exception"
   ```

**Known reasons for slow requests:**

| Cause | Where | Fix |
|-------|--------|-----|
| **Employer/job-title profile cold path** | `build_charts` 0.7–11s, `stats_compute_total` ~3–4s | Use Redis (shared cache) so second request hits cache; see `docs/EMPLOYER_PROFILE_QUERIES_AND_OPTIMIZATION.md`. |
| **LocMemCache + 2 workers** | Same URL can hit different worker → cache miss every time | Redis in docker-compose already; ensure `REDIS_URL` and `CACHES` use it. |
| **Postgres SSL closed** | 500 on views after idle; was `CONN_MAX_AGE=600` | ✅ `CONN_MAX_AGE = 60` in production settings. |
| **Large responses** | `/`, `/employment-based/india/` 300–445 KB on cache miss | Cache warming or CDN; first hit remains heavy. |

**Improvements:**

| Area | Suggestion |
|------|------------|
| **Postgres SSL errors** | ✅ Implemented: `CONN_MAX_AGE = 60` in `django_config/settings_production.py`. |
| **Gunicorn access log** | ✅ `--access-log-format` includes `%(L)s` (response time) for slow-request analysis. |
| **Nginx timing** | ✅ Implemented: `main_timed` log format with `$request_time`; see `deployment/nginx/visa-bulletin-log-format.conf`. |
| **Bot throttle** | ✅ Implemented: 0.1 qps per IP for common bots (GPTBot, Googlebot, etc.) via `gptbot-rate-limit.conf`; see `docs/PRODUCTION_TRAFFIC_PATTERNS_RESEARCH.md`. |
| **Gunicorn timeout** | `--timeout 60`; employer cold path can exceed 60s on large employers; consider Redis so cache hits are fast. |

## 🔒 Security

- **Secret Key**: Store in `.env`, never in code
- **DEBUG**: Always `False` in production
- **ALLOWED_HOSTS**: Configure specific domains + static IP
- **Firewall**: Only ports 22, 80, 443
- **SSL**: Let's Encrypt via Certbot

## 📞 Documentation

- **Setup Guide**: `docs/deployment/NEW_INSTANCE_SETUP.md`
- **Rollout Flow**: `docs/deployment/ROLLOUT_FLOW.md`
- **Data Refresh**: `docs/DATA_REFRESH_STRATEGY.md`
- **Scripts**: `scripts/README.md`
