# Deployment Configuration Files

This directory contains production deployment configurations for the Visa Bulletin Dashboard.

## 🎉 Production Status

**LIVE:** https://visa-bulletin.us  
**Deployment Date:** December 1, 2025  
**Performance:** 0.15-0.45s page loads  
**Uptime:** 24/7 with auto-restart on failure  

## 📁 Directory Structure

```
deployment/
├── systemd/           # Systemd service files
│   └── visa-bulletin.service
├── nginx/             # Nginx reverse proxy configs
│   └── visa-bulletin-nginx.conf
├── cron/              # Cron job setup
│   └── setup-cron.sh
└── README.md          # This file
```

## 🚀 Production Deployment Stack

### Components

1. **Application Server**: Gunicorn (1 worker, 2 threads)
2. **Reverse Proxy**: Nginx
3. **Process Management**: Systemd
4. **Data Refresh**: Cron (daily at 9 AM UTC)
5. **Database**: SQLite with WAL mode
6. **Caching**: Django LocMemCache (3 hours)

### Server Specs

- **AWS Lightsail**: $5/month
- **RAM**: 416 MB (with 2GB swap)
- **CPU**: 1 vCPU
- **Disk**: 20 GB SSD
- **OS**: Ubuntu 22.04 LTS

## 📋 Installation Steps

### 1. Install System Dependencies

```bash
sudo apt update
sudo apt install -y python3.10 python3.10-venv python3-pip nginx
```

### 2. Clone Repository

```bash
sudo mkdir -p /opt/visa_bulletin
sudo chown ubuntu:ubuntu /opt/visa_bulletin
cd /opt
git clone https://github.com/your-repo/visa_bulletin.git
cd visa_bulletin
```

### 3. Setup Python Environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 4. Configure Django

```bash
# Set production secret key
export DJANGO_SECRET_KEY="your-secret-key-here"

# Run migrations
python manage.py migrate
```

### 5. Setup Systemd Service

```bash
sudo cp deployment/systemd/visa-bulletin.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable visa-bulletin
sudo systemctl start visa-bulletin
sudo systemctl status visa-bulletin
```

### 6. Configure Nginx

```bash
sudo cp deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### 7. Setup Cron Job

```bash
bash deployment/cron/setup-cron.sh
```

### 8. Initial Data Load

```bash
source venv/bin/activate
python refresh_data.py --save-to-db
```

## 🔧 Management Commands

### Service Management

```bash
# Start/Stop/Restart
sudo systemctl start visa-bulletin
sudo systemctl stop visa-bulletin
sudo systemctl restart visa-bulletin

# View status
sudo systemctl status visa-bulletin

# View logs
sudo journalctl -u visa-bulletin -f
```

### Manual Data Refresh

```bash
cd /opt/visa_bulletin
source venv/bin/activate
python refresh_data_incremental.py --save-to-db
```

### Monitor Cron Jobs

```bash
# View cron log
tail -f /opt/visa_bulletin/logs/cron.log

# List cron jobs
crontab -l
```

## 🔒 Security Notes

1. **Secret Key**: Store in environment variable, not in code
2. **DEBUG Mode**: Always `False` in production
3. **Allowed Hosts**: Configure specific domains
4. **Firewall**: Only ports 22 (SSH), 80 (HTTP), 443 (HTTPS)
5. **SSL**: Use Let's Encrypt (commented nginx config included)

## 📊 Performance Tuning

### Current Settings

- **Gunicorn Workers**: 1 (for 416 MB RAM)
- **Threads per Worker**: 2
- **Max Requests**: 100 (worker recycling)
- **Cache Duration**: 3 hours
- **Request Timeout**: 120 seconds

### For Larger Instances

If you upgrade to a larger instance (e.g., $10/month with 1GB RAM):

```bash
# Edit /etc/systemd/system/visa-bulletin.service
# Change: --workers 1 → --workers 2
# Or calculate: (2 * CPU_CORES) + 1

sudo systemctl daemon-reload
sudo systemctl restart visa-bulletin
```

## 🐛 Troubleshooting

### Site is slow

1. Check load: `cat /proc/loadavg`
2. Check memory: `free -m`
3. Check processes: `ps aux | grep -E "(gunicorn|python|bazel)"`
4. Kill Bazel if running: `pkill -9 bazel`

### Service won't start

```bash
# Check logs
sudo journalctl -u visa-bulletin -n 50

# Test manually
cd /opt/visa_bulletin
source venv/bin/activate
python manage.py check
gunicorn --check-config django_config.wsgi:application
```

### Database locked errors

```bash
# Verify WAL mode is enabled
cd /opt/visa_bulletin
source venv/bin/activate
python -c "import django; django.setup(); from django.db import connection; print(connection.cursor().execute('PRAGMA journal_mode;').fetchone())"

# Should output: ('wal',)
```

## 📈 Monitoring

### Key Metrics to Monitor

- **Page Load Time**: Should be < 1 second
- **Memory Usage**: Should stay < 350 MB
- **Load Average**: Should be < 2.0
- **Disk Usage**: Monitor `/opt/visa_bulletin/visa_bulletin.db`

### Useful Commands

```bash
# Server stats
free -m && cat /proc/loadavg && df -h

# Application stats
sudo systemctl status visa-bulletin
ps aux | grep gunicorn

# Database stats
ls -lh /opt/visa_bulletin/visa_bulletin.db
sqlite3 /opt/visa_bulletin/visa_bulletin.db "SELECT COUNT(*) FROM bulletin;"
```

## 🔄 Updates

### Deploying Code Updates

```bash
cd /opt/visa_bulletin
git pull
source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
sudo systemctl restart visa-bulletin
```

### Database Backups

```bash
# Manual backup
cp /opt/visa_bulletin/visa_bulletin.db /opt/visa_bulletin/backups/visa_bulletin_$(date +%Y%m%d).db

# Automated (add to crontab)
# 0 2 * * * cp /opt/visa_bulletin/visa_bulletin.db /opt/visa_bulletin/backups/visa_bulletin_$(date +\%Y\%m\%d).db
```

## 📞 Support

For issues or questions, see the main project README.

