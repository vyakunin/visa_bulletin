#!/bin/bash
#
# Deployment script for Visa Bulletin Dashboard
# Deploys the latest code from GitHub main branch to AWS Lightsail
#
# Usage: ./scripts/deploy.sh [ssh-key-path]
#
# Example:
#   ./scripts/deploy.sh ~/Downloads/VisaBulletin.pem
#

set -e  # Exit on any error

# Configuration
AWS_HOST="3.227.71.176"
AWS_USER="ubuntu"
APP_DIR="/opt/visa_bulletin"
DEFAULT_KEY="$HOME/Downloads/VisaBulletin.pem"

# Use provided SSH key or default
SSH_KEY="${1:-$DEFAULT_KEY}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    echo ""
    echo "Usage: $0 [ssh-key-path]"
    echo "Example: $0 ~/Downloads/VisaBulletin.pem"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🚀 DEPLOYING TO AWS LIGHTSAIL"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Host: $AWS_HOST"
echo "Key:  $SSH_KEY"
echo ""

# Deploy via SSH
ssh -i "$SSH_KEY" "${AWS_USER}@${AWS_HOST}" << 'ENDSSH'
set -e

echo "📥 Pulling latest code from GitHub..."
cd /opt/visa_bulletin
git pull origin main

echo ""
echo "🧹 Clearing Python cache..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
find . -name "*.pyc" -delete 2>/dev/null || true

echo ""
echo "🔒 Checking security configuration..."
if [ ! -f .env ]; then
    echo "⚠️ .env file not found. Generating secure production secrets..."
    # Generate a random 50-char key
    SECRET=$(python3 -c 'import secrets; print(secrets.token_urlsafe(50))')
    echo "DJANGO_SECRET_KEY=$SECRET" > .env
    echo "DEBUG=False" >> .env
    chmod 600 .env
    echo "✅ Generated new .env file with secure key."
else
    echo "✅ .env file exists."
fi

echo ""
echo "⚙️ Updating system configuration..."
sudo cp deployment/systemd/visa-bulletin.service /etc/systemd/system/
sudo cp deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
# Note: visa-bulletin-locations.conf stays in /opt/visa_bulletin/deployment/nginx/ (already there from git pull)
sudo systemctl daemon-reload
# Ensure Nginx config is linked (if not already)
if [ ! -L /etc/nginx/sites-enabled/visa-bulletin ]; then
    sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
fi

echo ""
echo "🔐 Ensuring SSL configuration is applied..."
# Re-apply SSL configuration after copying base config
# This ensures Certbot's SSL config is always present even if we overwrote it

# First, check if SSL is already configured
if sudo nginx -T 2>/dev/null | grep -q "ssl_certificate.*visa-bulletin.us"; then
    echo "✅ SSL already configured in nginx"
    
    # Check if SSL block uses include (new style) or has inline locations (old style)
    if sudo grep -A5 "listen 443 ssl" /etc/nginx/sites-available/visa-bulletin | grep -q "include.*visa-bulletin-locations.conf"; then
        echo "✅ SSL block already uses shared location includes"
    else
        echo "⚙️  Updating SSL block to use shared location includes..."
        # Backup current config
        sudo cp /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-available/visa-bulletin.backup.$(date +%s)
        # Replace inline locations with include in HTTPS block
        sudo sed -i '/listen 443 ssl/,/^}/ {
            /location/,/^    }/d
            /server_name/a\    \n    # Include shared location blocks\n    include /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf;
        }' /etc/nginx/sites-available/visa-bulletin
        echo "✅ Updated SSL block to use includes"
    fi
else
    echo "Adding SSL configuration..."
    # Use certbot to add SSL to the base config (preserves existing cert)
    if sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us --cert-name visa-bulletin.us --non-interactive --redirect 2>&1 | grep -q "Successfully deployed"; then
        echo "✅ SSL configured successfully by Certbot"
        
        # Update the Certbot-generated SSL block to use includes instead of duplicating locations
        echo "⚙️  Optimizing SSL block to use shared location includes..."
        sudo sed -i '/listen 443 ssl/,/^}/ {
            /location/,/^    }/d
            /server_name/a\    \n    # Include shared location blocks\n    include /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf;
        }' /etc/nginx/sites-available/visa-bulletin
        echo "✅ SSL block optimized"
    else
        echo "⚠️  Certbot failed, trying manual SSL configuration..."
        # Fallback: Manually add SSL block if certs exist
        if [ -f /etc/letsencrypt/live/visa-bulletin.us/fullchain.pem ]; then
            sudo tee -a /etc/nginx/sites-available/visa-bulletin > /dev/null << 'EOF'

# SSL Configuration (manually added)
server {
    listen 443 ssl;
    server_name visa-bulletin.us www.visa-bulletin.us;
    
    ssl_certificate /etc/letsencrypt/live/visa-bulletin.us/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/visa-bulletin.us/privkey.pem;
    include /etc/letsencrypt/options-ssl-nginx.conf;
    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;

    # Include shared location blocks
    include /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf;
}
EOF
            echo "✅ SSL manually configured with shared location blocks"
        else
            echo "❌ No SSL certificates found! Run: sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us"
            exit 1
        fi
    fi
fi

sudo nginx -t || { echo "❌ Nginx config test failed!"; exit 1; }
sudo systemctl reload nginx
sudo systemctl restart visa-bulletin

echo ""
echo "⏳ Waiting for service to start..."
sleep 5

echo ""
echo "✅ Checking service status..."
sudo systemctl is-active visa-bulletin --quiet && echo "Service is active" || echo "❌ Service failed to start!"

echo ""
echo "🧪 Testing site..."
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://visa-bulletin.us || echo "❌ Site unreachable!"

echo ""
echo "📋 Recent logs (last 10 lines)..."
sudo journalctl -u visa-bulletin -n 10 --no-pager

ENDSSH

# Check exit status
if [ $? -eq 0 ]; then
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
    echo "✅ DEPLOYMENT SUCCESSFUL!"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    echo "🌐 Site: https://visa-bulletin.us"
    echo "📊 Status: Live and running"
    echo ""
    echo "To view logs:"
    echo "  ssh -i $SSH_KEY ${AWS_USER}@${AWS_HOST}"
    echo "  sudo journalctl -u visa-bulletin -f"
    echo ""
else
    echo ""
    echo "═══════════════════════════════════════════════════════════════════"
    echo "❌ DEPLOYMENT FAILED!"
    echo "═══════════════════════════════════════════════════════════════════"
    echo ""
    echo "Check the logs above for errors."
    echo ""
    exit 1
fi

