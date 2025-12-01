# 🚀 Quick Deployment Guide

## Prerequisites

You need:
- AWS account (free tier eligible)
- Domain name (optional, ~$10/year)
- 30 minutes

## Option 1: AWS Lightsail (Recommended - $5/month)

### Step 1: Create Lightsail Instance

```bash
# Via AWS Console:
# 1. Go to https://lightsail.aws.amazon.com/
# 2. Create Instance → OS Only → Ubuntu 22.04 LTS
# 3. Choose $5/month plan (1 GB RAM)
# 4. Download SSH key
```

### Step 2: SSH and Install

```bash
# SSH into instance
ssh -i your-key.pem ubuntu@YOUR_LIGHTSAIL_IP

# Install Docker
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu

# Clone repository
cd /opt
sudo git clone https://github.com/vyakunin/visa_bulletin.git
cd visa_bulletin
sudo chown -R ubuntu:ubuntu /opt/visa_bulletin

# Generate Django secret key
export DJANGO_SECRET_KEY=$(python3 -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())')
echo "export DJANGO_SECRET_KEY='$DJANGO_SECRET_KEY'" >> ~/.bashrc

# Set production settings
export DJANGO_SETTINGS_MODULE=django_config.settings_production
export ALLOWED_HOSTS=YOUR_DOMAIN.com,YOUR_IP
echo "export DJANGO_SETTINGS_MODULE=django_config.settings_production" >> ~/.bashrc
echo "export ALLOWED_HOSTS=YOUR_DOMAIN.com,YOUR_IP" >> ~/.bashrc

# Build and run with Docker
docker-compose up -d

# Or run with Bazel
bazel run //:migrate
bazel run //:refresh_data -- --save-to-db
nohup bazel run //:runserver &
```

### Step 3: Configure Firewall

```bash
# Open ports 80, 443, 22
# In Lightsail console: Networking → Firewall
```

### Step 4: Setup Nginx (Reverse Proxy)

```bash
sudo apt install -y nginx

# Create Nginx config
sudo tee /etc/nginx/sites-available/visa-bulletin << 'EOF'
server {
    listen 80;
    server_name YOUR_DOMAIN.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /static/ {
        alias /opt/visa_bulletin/webapp/static/;
        expires 30d;
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Step 5: Setup SSL (Free with Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d YOUR_DOMAIN.com

# Auto-renewal is configured automatically
```

### Step 6: Setup Daily Data Refresh

```bash
# Add cron job
crontab -e

# Add this line (runs daily at 9 AM UTC):
0 9 * * * cd /opt/visa_bulletin && /usr/local/bin/bazel run //:refresh_data_incremental >> /opt/visa_bulletin/logs/cron.log 2>&1
```

## Option 2: Docker on Any Cloud

Works on: AWS, GCP, Azure, DigitalOcean, Linode, etc.

```bash
# 1. Install Docker
curl -fsSL https://get.docker.com | sh

# 2. Clone and deploy
git clone https://github.com/vyakunin/visa_bulletin.git
cd visa_bulletin

# 3. Generate secret key
export DJANGO_SECRET_KEY=$(openssl rand -base64 50)

# 4. Set environment
export DJANGO_SETTINGS_MODULE=django_config.settings_production
export ALLOWED_HOSTS=your-domain.com

# 5. Run
docker-compose up -d
```

## Option 3: Local Testing

```bash
# Clone repository
git clone https://github.com/vyakunin/visa_bulletin.git
cd visa_bulletin

# Setup environment
./setup.sh

# Activate virtual environment
source ~/visa-bulletin-venv/bin/activate

# Run migrations
python manage.py migrate

# Fetch data
bazel run //:refresh_data -- --save-to-db

# Start server
bazel run //:runserver

# Open browser
open http://localhost:8000
```

## Environment Variables (Production)

Create a `.env` file (or set in system):

```bash
# Required
DJANGO_SECRET_KEY='your-secret-key-here'
DJANGO_SETTINGS_MODULE='django_config.settings_production'
ALLOWED_HOSTS='yourdomain.com,www.yourdomain.com'

# Optional
DEBUG='False'
```

## Security Checklist

Before going live:

- [ ] Change `SECRET_KEY` to a random value
- [ ] Set `DEBUG=False`
- [ ] Configure `ALLOWED_HOSTS` with your domain
- [ ] Setup SSL/HTTPS (Let's Encrypt)
- [ ] Configure firewall (only ports 22, 80, 443)
- [ ] Disable password SSH (key-only)
- [ ] Setup automatic backups
- [ ] Enable automatic security updates

## Post-Deployment

1. **Test the site:**
   ```bash
   curl https://yourdomain.com
   ```

2. **Monitor logs:**
   ```bash
   sudo journalctl -u nginx -f
   docker logs visa_bulletin_web_1 -f
   ```

3. **Setup monitoring:**
   - UptimeRobot (free): https://uptimerobot.com
   - CloudWatch (if AWS)

4. **Backup database:**
   ```bash
   # Daily backup
   0 2 * * * sqlite3 /opt/visa_bulletin/visa_bulletin.db ".backup '/opt/visa_bulletin/backups/visa_bulletin_$(date +\%Y\%m\%d).db'"
   ```

## Troubleshooting

**Port 8000 not accessible:**
```bash
sudo systemctl status nginx
bazel run //:runserver
```

**Database locked:**
```bash
# Check WAL mode
sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
# Should output: wal
```

**Import errors:**
```bash
pip install -r requirements.txt
```

## Cost Summary

| Item | Monthly Cost |
|------|--------------|
| AWS Lightsail | $5.00 |
| Domain (.us) | $0.67 |
| **Total** | **$5.67** |

## Support

- Documentation: See DEPLOYMENT_AWS.md for detailed guide
- Issues: https://github.com/vyakunin/visa_bulletin/issues
- Community: Share on Reddit r/immigration

---

**That's it! Your Visa Bulletin Dashboard is live! 🎉**

