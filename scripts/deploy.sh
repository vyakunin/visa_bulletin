#!/bin/bash
#
# Docker-based deployment script for Visa Bulletin Dashboard
# Deploys the latest Docker image from GHCR to AWS Lightsail
#
# Usage: ./scripts/deploy.sh [ssh-key-path] [image-tag]
#
# Examples:
#   ./scripts/deploy.sh ~/Downloads/VisaBulletin.pem
#   ./scripts/deploy.sh ~/Downloads/VisaBulletin.pem v1.2.3
#

set -e  # Exit on any error

# Configuration
AWS_HOST="3.227.71.176"
AWS_USER="ubuntu"
APP_DIR="/opt/visa_bulletin"
DEFAULT_KEY="$HOME/Downloads/VisaBulletin.pem"

# Use provided SSH key or default
SSH_KEY="${1:-$DEFAULT_KEY}"
IMAGE_TAG="${2:-latest}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    echo ""
    echo "Usage: $0 [ssh-key-path] [image-tag]"
    echo "Example: $0 ~/Downloads/VisaBulletin.pem v1.2.3"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🚀 DEPLOYING TO AWS LIGHTSAIL (DOCKER)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Host: $AWS_HOST"
echo "Key:  $SSH_KEY"
echo "Image tag: $IMAGE_TAG"
echo ""

# Deploy via SSH
ssh -i "$SSH_KEY" "${AWS_USER}@${AWS_HOST}" "IMAGE_TAG=$IMAGE_TAG bash -s" << 'ENDSSH'
set -e

echo "📥 Pulling latest configs from GitHub..."
cd /opt/visa_bulletin
git pull origin main

echo ""
echo "🐳 Pulling Docker image: ghcr.io/vyakunin/visa_bulletin:${IMAGE_TAG}"
docker-compose pull

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
echo "⚙️ Updating Nginx configuration..."
sudo cp deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
# Note: visa-bulletin-locations.conf stays in /opt/visa_bulletin/deployment/nginx/ (already there from git pull)
# Ensure Nginx config is linked (if not already)
if [ ! -L /etc/nginx/sites-enabled/visa-bulletin ]; then
    sudo ln -s /etc/nginx/sites-available/visa-bulletin /etc/nginx/sites-enabled/
fi

echo ""
echo "🔐 Ensuring SSL configuration is applied..."
# Re-apply SSL configuration after copying base config
# This ensures Certbot's SSL config is always present even if we overwrote it

# First, check if SSL certificates exist
if sudo [ -f /etc/letsencrypt/live/visa-bulletin.us/fullchain.pem ]; then
    echo "✅ SSL certificates found"
    
    # Check if Nginx config already has SSL configured
    if sudo nginx -T 2>/dev/null | grep -q "ssl_certificate.*visa-bulletin.us"; then
        echo "✅ SSL already configured in Nginx"
        
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
        # SSL certs exist but not in Nginx config - add manually
        echo "⚙️  Adding SSL configuration to Nginx (certs already exist)..."
        sudo tee -a /etc/nginx/sites-available/visa-bulletin > /dev/null << 'EOF'

# SSL Configuration
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
        echo "✅ SSL configuration added to Nginx"
    fi
else
    # No SSL certificates exist - need to obtain them
    echo "⚠️  No SSL certificates found. Attempting to obtain certificates with Certbot..."
    
    # Use certbot to obtain and configure SSL
    if sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us --cert-name visa-bulletin.us --non-interactive --redirect 2>&1 | grep -q "Successfully"; then
        echo "✅ SSL certificates obtained and configured by Certbot"
        
        # Update the Certbot-generated SSL block to use includes instead of duplicating locations
        echo "⚙️  Optimizing SSL block to use shared location includes..."
        sudo sed -i '/listen 443 ssl/,/^}/ {
            /location/,/^    }/d
            /server_name/a\    \n    # Include shared location blocks\n    include /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf;
        }' /etc/nginx/sites-available/visa-bulletin
        echo "✅ SSL block optimized"
    else
        echo "❌ Certbot failed to obtain SSL certificates!"
        echo "   This may be due to:"
        echo "   - Domain not pointing to this server"
        echo "   - Port 80/443 blocked"
        echo "   - Rate limiting from Let's Encrypt"
        echo ""
        echo "   Manual fix: sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us"
        echo "   For now, site will run on HTTP only"
    fi
fi

sudo nginx -t || { echo "❌ Nginx config test failed!"; exit 1; }
sudo systemctl reload nginx

echo ""
echo "🔄 Restarting Docker services..."
docker-compose up -d

echo ""
echo "⏳ Waiting for services to start..."
sleep 10

echo ""
echo "✅ Checking Docker service status..."
docker-compose ps

echo ""
echo "🧪 Testing site..."
curl -s -o /dev/null -w "HTTP %{http_code}\n" https://visa-bulletin.us || echo "❌ Site unreachable!"

echo ""
echo "📋 Recent logs (last 20 lines)..."
docker-compose logs --tail=20 web

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
    echo "  cd /opt/visa_bulletin && docker-compose logs -f"
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

