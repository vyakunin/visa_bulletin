# AWS Lightsail Deployment - Step-by-Step Guide

## 🚀 Your Deployment Plan (40 minutes)

Follow these steps in order. I'll guide you through each one.

---

## Step 1: Create AWS Lightsail Instance (5 minutes)

### 1.1 Sign in to AWS
- Go to: https://lightsail.aws.amazon.com/
- Sign in with your AWS account (or create one if you don't have it)

### 1.2 Create Instance
Click **"Create instance"** button

**Instance location:**
- Choose region closest to you (e.g., US East (N. Virginia))

**Pick your instance image:**
- Select: **"Linux/Unix"**
- Select: **"OS Only"**
- Choose: **"Ubuntu 22.04 LTS"**

**SSH key pair:**
- Click **"Change SSH key pair"**
- Either:
  - Upload your existing key, OR
  - Click **"Create new"** → Download the `.pem` file
  - **IMPORTANT:** Save this file! You'll need it to SSH

**Choose your instance plan:**
- Select: **$5 USD/month plan**
  - 1 GB RAM
  - 1 vCPU
  - 40 GB SSD
  - 2 TB transfer

**Name your instance:**
- Instance name: `visa-bulletin-prod`

Click **"Create instance"**

### 1.3 Wait for Instance to Start
- Status will change from "Pending" to "Running" (~2 minutes)
- Note down your **Public IP address** (e.g., 3.87.45.123)

---

## Step 2: Configure Firewall (2 minutes)

### 2.1 Open Networking Tab
- Click on your instance name
- Click **"Networking"** tab

### 2.2 Add Firewall Rules
Under "IPv4 Firewall", click **"Add rule"** for each:

1. **HTTP**
   - Application: Custom
   - Protocol: TCP
   - Port: 80

2. **HTTPS**
   - Application: Custom
   - Protocol: TCP
   - Port: 443

**Port 22 (SSH) should already be open by default**

Click **"Create"** for each rule

---

## Step 3: SSH into Your Instance (3 minutes)

### 3.1 Make SSH Key Executable (on your Mac)
```bash
cd ~/Downloads  # Or wherever you saved the .pem file
chmod 400 LightsailDefaultKey-*.pem
```

### 3.2 SSH In
Replace `YOUR_IP` with your actual Lightsail IP:

```bash
ssh -i ~/Downloads/LightsailDefaultKey-*.pem ubuntu@YOUR_IP
```

Type "yes" when prompted about authenticity.

You should now see:
```
ubuntu@ip-xxx-xxx-xxx-xxx:~$
```

**You're in! 🎉**

---

## Step 4: Install Docker (5 minutes)

Run these commands in your SSH session:

```bash
# Update system
sudo apt update && sudo apt upgrade -y

# Install Docker
curl -fsSL https://get.docker.com | sudo sh

# Add your user to docker group
sudo usermod -aG docker ubuntu

# Install docker-compose
sudo apt install -y docker-compose

# Verify installation
docker --version
docker-compose --version
```

**Reboot for group changes to take effect:**
```bash
sudo reboot
```

**Wait 1 minute, then SSH back in:**
```bash
ssh -i ~/Downloads/LightsailDefaultKey-*.pem ubuntu@YOUR_IP
```

---

## Step 5: Clone and Deploy Application (10 minutes)

### 5.1 Clone Repository
```bash
cd /opt
sudo git clone https://github.com/vyakunin/visa_bulletin.git
cd visa_bulletin
sudo chown -R ubuntu:ubuntu /opt/visa_bulletin
```

### 5.2 Generate Secret Key
```bash
# Generate a secure secret key
DJANGO_SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
echo "Your secret key: $DJANGO_SECRET"

# Save it to your environment
echo "export DJANGO_SECRET_KEY='$DJANGO_SECRET'" >> ~/.bashrc
echo "export DJANGO_SETTINGS_MODULE='django_config.settings_production'" >> ~/.bashrc
echo "export DEBUG='False'" >> ~/.bashrc
echo "export ALLOWED_HOSTS='YOUR_DOMAIN.com,YOUR_IP'" >> ~/.bashrc

# Load the environment
source ~/.bashrc
```

**Replace `YOUR_DOMAIN.com` and `YOUR_IP` in the command above!**

### 5.3 Deploy with Docker
```bash
cd /opt/visa_bulletin

# Start the application
docker-compose up -d

# Check if it's running
docker ps

# View logs
docker-compose logs -f
# Press Ctrl+C to exit logs
```

### 5.4 Fetch Initial Data
```bash
# This will take 5-10 minutes (fetches 20+ years of data)
docker-compose exec web python manage.py migrate
docker-compose exec web python refresh_data.py --save-to-db
```

---

## Step 6: Install and Configure Nginx (5 minutes)

### 6.1 Install Nginx
```bash
sudo apt install -y nginx
```

### 6.2 Create Nginx Configuration
Replace `YOUR_IP` with your actual Lightsail IP:

```bash
sudo tee /etc/nginx/sites-available/visa-bulletin << 'NGINXCONF'
server {
    listen 80;
    server_name YOUR_IP;

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
NGINXCONF
```

**IMPORTANT:** Edit the file and replace `YOUR_IP`:
```bash
sudo nano /etc/nginx/sites-available/visa-bulletin
# Replace YOUR_IP with your actual IP
# Press Ctrl+X, then Y, then Enter to save
```

### 6.3 Enable the Site
```bash
# Create symlink
sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/

# Remove default site
sudo rm /etc/nginx/sites-enabled/default

# Test configuration
sudo nginx -t

# Reload Nginx
sudo systemctl reload nginx
```

---

## Step 7: Test Your Site! (2 minutes)

### 7.1 Test via IP
Open your browser and visit:
```
http://YOUR_IP
```

**You should see your Visa Bulletin Dashboard! 🎉**

If you see the site, congratulations! Your app is live!

---

## Step 8: Setup SSL (HTTPS) - OPTIONAL BUT RECOMMENDED (5 minutes)

**NOTE:** You need a domain name for SSL. If you don't have one yet, skip this step.

### 8.1 Install Certbot
```bash
sudo apt install -y certbot python3-certbot-nginx
```

### 8.2 Get SSL Certificate
Replace `YOUR_DOMAIN.com` with your actual domain:

```bash
sudo certbot --nginx -d YOUR_DOMAIN.com
```

Follow the prompts:
- Enter your email
- Agree to terms
- Choose: Redirect HTTP to HTTPS (option 2)

**That's it! Your site now has HTTPS! 🔒**

Visit: `https://YOUR_DOMAIN.com`

---

## Step 9: Setup Daily Data Refresh (3 minutes)

### 9.1 Create Cron Job
```bash
# Create logs directory
mkdir -p /opt/visa_bulletin/logs

# Edit crontab
crontab -e
```

Choose nano as editor (usually option 1).

Add this line at the bottom:
```
0 9 * * * cd /opt/visa_bulletin && docker-compose exec web python refresh_data_incremental.py --save-to-db >> /opt/visa_bulletin/logs/cron.log 2>&1
```

Press Ctrl+X, then Y, then Enter to save.

**Data will now refresh daily at 9 AM UTC!**

---

## Step 10: Setup Monitoring (OPTIONAL - 5 minutes)

### 10.1 Sign up for UptimeRobot (Free)
- Go to: https://uptimerobot.com/
- Create free account

### 10.2 Add Monitor
- Click "Add New Monitor"
- Monitor Type: HTTP(s)
- Friendly Name: Visa Bulletin
- URL: http://YOUR_IP (or https://YOUR_DOMAIN.com)
- Monitoring Interval: 5 minutes

**You'll get email alerts if your site goes down!**

---

## ✅ Deployment Complete!

### Your Site is Now:
- ✅ Live at: http://YOUR_IP (or https://YOUR_DOMAIN.com)
- ✅ Running on AWS Lightsail ($5/month)
- ✅ Secured with HTTPS (if you have domain)
- ✅ Auto-updating daily
- ✅ Monitored for uptime

### Monthly Cost:
- AWS Lightsail: $5.00
- Domain (optional): $0.67/month ($8/year)
- **Total: $5-6/month**

---

## 🔧 Useful Commands

### View Application Logs
```bash
docker-compose logs -f
```

### Restart Application
```bash
cd /opt/visa_bulletin
docker-compose restart
```

### Update Application (when you push new code)
```bash
cd /opt/visa_bulletin
git pull
docker-compose down
docker-compose up -d --build
```

### Check Application Status
```bash
docker ps
curl http://localhost:8000
```

### View Nginx Logs
```bash
sudo tail -f /var/log/nginx/access.log
sudo tail -f /var/log/nginx/error.log
```

---

## 🆘 Troubleshooting

### Site not loading?
```bash
# Check if Docker is running
docker ps

# Check if Nginx is running
sudo systemctl status nginx

# Check logs
docker-compose logs
```

### Database locked error?
```bash
# Check WAL mode
docker-compose exec web sqlite3 visa_bulletin.db "PRAGMA journal_mode;"
# Should output: wal
```

### Out of memory?
```bash
# Add swap space
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## 🎯 Next Steps

1. **Get a domain name** (if you haven't):
   - visabulletin.us (~$8/year)
   - visa-bulletin.com (~$10/year)

2. **Point domain to your Lightsail IP:**
   - In Namecheap/registrar: Add A record → YOUR_IP

3. **Setup SSL:**
   - Run Step 8 with your domain

4. **Share your site:**
   - Reddit: r/immigration
   - Track My Visa Journey forums
   - Immigration Facebook groups

---

## 🎊 Congratulations!

You've successfully deployed a production-grade web application!

**Your Visa Bulletin Dashboard is now helping track immigration priority dates! 🇺🇸**

Need help? Issues? Let me know!

