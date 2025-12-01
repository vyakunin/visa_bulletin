# AWS Deployment Guide: Visa Bulletin Dashboard

## 📊 Cost Analysis & Architecture Recommendations

### Traffic Profile: Hundreds to Thousands DAU
- **Estimated requests:** ~10-50K requests/day
- **Data transfer:** ~5-10 GB/month (mostly HTML + Plotly charts)
- **Storage:** ~2 GB (database + cached HTML pages)

---

## 🎯 Recommended Option: AWS Lightsail ($5/month)

### Why Lightsail?

**✅ Best Choice for Your Use Case:**
- **Fixed pricing:** $5/month (predictable costs)
- **Specs:** 1 GB RAM, 1 vCPU, 40 GB SSD, 2 TB transfer
- **Handles:** 5-10K+ concurrent users easily
- **Simple:** One-click setup, managed networking
- **Includes:** Static IP, DNS management, firewall

**Cost Comparison:**
| Service | Monthly Cost | Notes |
|---------|--------------|-------|
| **Lightsail** | **$5-10** | **Recommended** - Fixed price, simple |
| EC2 t4g.micro | $6-8 | Variable, more complex |
| EC2 t3.micro | $7-10 | Variable, more complex |
| ECS Fargate | $15-20 | Overkill for this app |
| Lambda + API Gateway | $0-5 | Cold starts, not ideal for Django |

---

## 🚀 Deployment Architecture

```
┌─────────────────────────────────────────────┐
│            CloudFlare (Optional CDN)        │
│         SSL/TLS + DDoS Protection           │
└─────────────────────┬───────────────────────┘
                      │
┌─────────────────────▼───────────────────────┐
│     AWS Lightsail Instance ($5/month)       │
│  ┌─────────────────────────────────────┐   │
│  │   Nginx (Reverse Proxy + SSL)       │   │
│  │   Port 443 (HTTPS) → 8000           │   │
│  └──────────────┬──────────────────────┘   │
│                 │                           │
│  ┌──────────────▼──────────────────────┐   │
│  │  Django App (Gunicorn/uWSGI)        │   │
│  │  Port 8000                          │   │
│  └──────────────┬──────────────────────┘   │
│                 │                           │
│  ┌──────────────▼──────────────────────┐   │
│  │  SQLite Database (WAL mode)         │   │
│  │  /opt/visa-bulletin/visa_bulletin.db│   │
│  └─────────────────────────────────────┘   │
│                                             │
│  ┌─────────────────────────────────────┐   │
│  │  Cron Job: Daily Data Refresh       │   │
│  │  9 AM UTC: refresh_data_incremental  │   │
│  └─────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

---

## 📋 Step-by-Step Deployment

### Option 1: Lightsail (Recommended - Simple & Cheap)

#### 1. Create Lightsail Instance

```bash
# Via AWS Console:
# 1. Go to https://lightsail.aws.amazon.com/
# 2. Create Instance → OS Only → Ubuntu 22.04 LTS
# 3. Choose $5/month plan (1 GB RAM)
# 4. Enable Auto-snapshots (backup)
# 5. Download SSH key

# Via AWS CLI:
aws lightsail create-instances \
  --instance-names visa-bulletin-prod \
  --availability-zone us-east-1a \
  --blueprint-id ubuntu_22_04 \
  --bundle-id nano_2_0 \
  --key-pair-name visa-bulletin-key
```

#### 2. Configure Firewall

```bash
# Open ports
aws lightsail put-instance-public-ports \
  --instance-name visa-bulletin-prod \
  --port-infos fromPort=22,toPort=22,protocol=tcp \
              fromPort=80,toPort=80,protocol=tcp \
              fromPort=443,toPort=443,protocol=tcp
```

#### 3. SSH and Install

```bash
# SSH into instance
ssh -i visa-bulletin-key.pem ubuntu@<LIGHTSAIL_IP>

# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker (easiest deployment method)
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker ubuntu
sudo apt install -y docker-compose

# Install Nginx
sudo apt install -y nginx certbot python3-certbot-nginx

# Reboot to apply changes
sudo reboot
```

#### 4. Deploy Application

```bash
# Clone repository
cd /opt
sudo git clone https://github.com/YOUR_USERNAME/visa_bulletin.git
cd visa_bulletin
sudo chown -R ubuntu:ubuntu /opt/visa_bulletin

# Option A: Docker Deployment (Recommended)
docker-compose up -d

# Option B: Traditional Deployment
# Install Bazel
wget https://github.com/bazelbuild/bazelisk/releases/download/v1.19.0/bazelisk-linux-amd64
chmod +x bazelisk-linux-amd64
sudo mv bazelisk-linux-amd64 /usr/local/bin/bazel

# Install Python dependencies
sudo apt install -y python3.11 python3-pip
pip install -r requirements.txt

# Run migrations
bazel run //:migrate

# Fetch initial data
bazel run //:refresh_data -- --save-to-db

# Install systemd service (see below)
```

#### 5. Configure Nginx Reverse Proxy

```bash
# Create Nginx config
sudo tee /etc/nginx/sites-available/visa-bulletin << 'EOF'
server {
    listen 80;
    server_name YOUR_DOMAIN.com;  # Replace with your domain

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

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
}
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

#### 6. Setup SSL (HTTPS)

```bash
# Get free SSL certificate from Let's Encrypt
sudo certbot --nginx -d YOUR_DOMAIN.com

# Auto-renewal is configured by default
# Test renewal:
sudo certbot renew --dry-run
```

#### 7. Configure Systemd Service

```bash
# Create service file
sudo tee /etc/systemd/system/visa-bulletin.service << 'EOF'
[Unit]
Description=Visa Bulletin Dashboard
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/visa_bulletin
Environment="DJANGO_SETTINGS_MODULE=django_config.settings"
ExecStart=/usr/local/bin/bazel run //:runserver -- 0.0.0.0:8000
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable visa-bulletin
sudo systemctl start visa-bulletin
sudo systemctl status visa-bulletin
```

#### 8. Setup Cron Job for Data Refresh

```bash
# Add to crontab
crontab -e

# Add this line (9 AM UTC daily)
0 9 * * * cd /opt/visa_bulletin && /usr/local/bin/bazel run //:refresh_data_incremental >> /opt/visa_bulletin/logs/cron_refresh.log 2>&1
```

---

### Option 2: EC2 (More Flexible)

```bash
# Launch t4g.micro (ARM, cheapest)
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \  # Ubuntu 22.04 ARM
  --instance-type t4g.micro \
  --key-name visa-bulletin-key \
  --security-group-ids sg-XXXXXXXX \
  --subnet-id subnet-XXXXXXXX \
  --tag-specifications 'ResourceType=instance,Tags=[{Key=Name,Value=visa-bulletin-prod}]'

# Follow same deployment steps as Lightsail
```

---

### Option 3: Docker on Any Cloud (Most Portable)

```bash
# Works on: AWS, GCP, Azure, DigitalOcean, Linode, etc.

# 1. Install Docker on any Linux VM
curl -fsSL https://get.docker.com | sh

# 2. Clone and deploy
git clone https://github.com/YOUR_USERNAME/visa_bulletin.git
cd visa_bulletin
docker-compose up -d

# 3. Setup Nginx reverse proxy (same as above)
```

---

## 🔒 Security Hardening

### 1. Firewall Configuration

```bash
# Using UFW (Ubuntu Firewall)
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow 22/tcp   # SSH
sudo ufw allow 80/tcp   # HTTP
sudo ufw allow 443/tcp  # HTTPS
sudo ufw enable
```

### 2. SSH Hardening

```bash
# Disable password auth, use keys only
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart sshd

# Optional: Change SSH port
sudo sed -i 's/#Port 22/Port 2222/' /etc/ssh/sshd_config
```

### 3. Django Security Settings

Add to `django_config/settings.py`:

```python
# Production settings
DEBUG = False
ALLOWED_HOSTS = ['YOUR_DOMAIN.com', 'www.YOUR_DOMAIN.com']

# Security settings
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'

# CSRF trusted origins
CSRF_TRUSTED_ORIGINS = ['https://YOUR_DOMAIN.com']
```

### 4. Database Security

```bash
# Backup database daily
0 2 * * * sqlite3 /opt/visa_bulletin/visa_bulletin.db ".backup '/opt/visa_bulletin/backups/visa_bulletin_$(date +\%Y\%m\%d).db'" && find /opt/visa_bulletin/backups -mtime +7 -delete
```

### 5. Automatic Security Updates

```bash
sudo apt install -y unattended-upgrades
sudo dpkg-reconfigure -plow unattended-upgrades
```

---

## 📊 Monitoring & Observability

### 1. Basic Monitoring (Free)

```bash
# Install and configure CloudWatch agent
wget https://s3.amazonaws.com/amazoncloudwatch-agent/ubuntu/amd64/latest/amazon-cloudwatch-agent.deb
sudo dpkg -i amazon-cloudwatch-agent.deb

# Monitor: CPU, RAM, Disk, Network
```

### 2. Application Logs

```bash
# View Django logs
sudo journalctl -u visa-bulletin -f

# View Nginx logs
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

### 3. Uptime Monitoring (Free Options)

- **UptimeRobot** (free): https://uptimerobot.com/
- **Pingdom** (free tier): https://www.pingdom.com/
- **AWS CloudWatch Alarms**: Monitor instance health

---

## 💰 Cost Optimization

### 1. Use Reserved Instance (Save 40%)

```bash
# For 1-year commitment on EC2
aws ec2 purchase-reserved-instances-offering \
  --instance-type t4g.micro \
  --instance-count 1 \
  --reserved-instances-offering-id XXXXXXXX
```

### 2. Enable Lightsail Snapshots (Backup)

```bash
# Automatic daily snapshots ($0.05/GB/month)
aws lightsail enable-add-on \
  --instance-name visa-bulletin-prod \
  --add-on-request addOnType=AutoSnapshot
```

### 3. Use CloudFlare CDN (Free)

- Free SSL
- DDoS protection
- Global CDN
- 100GB bandwidth/month free

---

## 🌍 Cloud-Agnostic Deployment

### Using Docker (Works Everywhere)

**Supported Clouds:**
- AWS (Lightsail, EC2, ECS)
- Google Cloud (Compute Engine, Cloud Run)
- Azure (VM, Container Instances)
- DigitalOcean ($6/month droplet)
- Linode ($5/month Nanode)
- Hetzner ($4.5/month)
- Vultr ($5/month)

**Deploy anywhere with:**

```bash
# 1. Provision any Ubuntu 22.04 VM
# 2. Install Docker
curl -fsSL https://get.docker.com | sh

# 3. Deploy
git clone YOUR_REPO
cd visa_bulletin
docker-compose up -d

# 4. Setup reverse proxy (Nginx/Caddy)
```

---

## 🔄 CI/CD Pipeline (Optional)

### GitHub Actions Deployment

```yaml
# .github/workflows/deploy.yml
name: Deploy to AWS

on:
  push:
    branches: [main]

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      
      - name: Deploy to Lightsail
        uses: appleboy/ssh-action@master
        with:
          host: ${{ secrets.LIGHTSAIL_IP }}
          username: ubuntu
          key: ${{ secrets.SSH_KEY }}
          script: |
            cd /opt/visa_bulletin
            git pull
            docker-compose down
            docker-compose up -d --build
```

---

## 📈 Scaling Strategy

### When Traffic Grows (10K+ DAU)

1. **Upgrade Lightsail:** $10/month plan (2 GB RAM)
2. **Add Load Balancer:** Lightsail LB ($18/month)
3. **Switch to RDS:** For database if needed
4. **Enable CloudFront:** AWS CDN for static files

### High Traffic (100K+ DAU)

- Move to EC2 Auto Scaling Group
- Use RDS for database
- CloudFront + S3 for static files
- Redis for caching

---

## 🛠️ Troubleshooting

### Common Issues

**1. Port 8000 not accessible**
```bash
# Check if service is running
sudo systemctl status visa-bulletin

# Check logs
sudo journalctl -u visa-bulletin -n 50
```

**2. Database locked errors**
```bash
# Verify WAL mode
sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
# Should output: wal
```

**3. Memory issues**
```bash
# Add swap space (helps with 1 GB RAM)
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## ✅ Final Checklist

- [ ] Domain purchased and DNS configured
- [ ] SSL certificate installed (Let's Encrypt)
- [ ] Firewall configured (only 22, 80, 443 open)
- [ ] SSH key-only authentication
- [ ] Database backups scheduled
- [ ] Automatic security updates enabled
- [ ] Monitoring/alerting configured
- [ ] Cron job for data refresh working
- [ ] Test deployment from scratch

---

## 💡 Recommendation Summary

**For your use case (hundreds to thousands DAU):**

✅ **Start with AWS Lightsail $5/month plan**

**Reasons:**
1. **Cost-effective:** Fixed $5/month (vs variable EC2 costs)
2. **Simple:** Managed networking, static IP included
3. **Sufficient:** 1 GB RAM handles 5-10K concurrent users
4. **Upgrade path:** Easy to scale up to $10-20/month plans
5. **Predictable:** No surprise bills

**When to upgrade:**
- Move to $10/month plan when hitting 80% RAM consistently
- Add load balancer at 50K+ DAU
- Consider EC2 Auto Scaling at 100K+ DAU

**Total monthly cost breakdown:**
- Lightsail instance: $5
- Domain (optional): $1/month (Namecheap)
- Backups: $0.10 (2 GB × $0.05/GB)
- **Total: ~$6/month**

**Compare to competitors:**
- Heroku: $25-50/month (hobby/basic tier)
- PythonAnywhere: $12/month
- DigitalOcean: $6/month (similar to Lightsail)

**CloudFlare (free tier) recommended for:**
- Free SSL
- DDoS protection
- Better global performance
- No additional cost

This setup will handle your traffic requirements with room to grow! 🚀

