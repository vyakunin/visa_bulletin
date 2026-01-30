# Deployment Configuration Files

This directory contains production deployment configurations for the Visa Bulletin Dashboard.

## 🎉 Production Status

**LIVE:** https://visa-bulletin.us  
**Platform:** AWS Lightsail (2GB RAM)  
**Database:** PostgreSQL with blue-green deployment  
**Container:** Docker with Gunicorn  

## 📁 Directory Structure

```
deployment/
├── docker-compose.blue.yml    # Blue environment (port 8000)
├── docker-compose.green.yml   # Green environment (port 8001)
├── nginx/                     # Nginx reverse proxy configs
│   ├── visa-bulletin-nginx.conf
│   └── visa-bulletin-locations.conf
├── cron/                      # Cron job setup
│   └── setup-ingest-cron.sh
└── README.md                  # This file
```

## 🚀 Production Architecture

### Components

1. **Application Server**: Docker + Gunicorn
2. **Reverse Proxy**: Nginx with SSL
3. **Database**: PostgreSQL (blue-green)
4. **Data Refresh**: Cron (weekly, pre-built binaries)
5. **Caching**: Django LocMemCache

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
3. **`/etc/postgresql/14/main/conf.d/custom.conf`** - PostgreSQL tuning

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
