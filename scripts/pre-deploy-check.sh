#!/bin/bash
#
# Pre-deployment health check script
# Verifies production environment is ready for Docker deployment
#
# Usage: ./scripts/pre-deploy-check.sh [ssh-key-path]
#

set -e

# Configuration
AWS_HOST="3.227.71.176"
AWS_USER="ubuntu"
DEFAULT_KEY="$HOME/.ssh/lightsail_visa_bulletin"

# Use provided SSH key or default
SSH_KEY="${1:-$DEFAULT_KEY}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    exit 1
fi

echo "🔍 PRE-DEPLOYMENT HEALTH CHECK"
echo "═══════════════════════════════════════"
echo ""

# Run all checks on remote server
ssh -i "$SSH_KEY" "${AWS_USER}@${AWS_HOST}" 'bash -s' << 'ENDSSH'
set -e

ISSUES=0

echo "1️⃣  Checking for port conflicts..."
if lsof -i :8000 >/dev/null 2>&1; then
    echo "⚠️  Port 8000 is in use:"
    lsof -i :8000 | head -5
    
    # Check if it's an old systemd service
    if systemctl is-active --quiet visa-bulletin 2>/dev/null; then
        echo "   → Old systemd service 'visa-bulletin' is running"
        echo "   → Will need to stop: sudo systemctl stop visa-bulletin"
        ISSUES=$((ISSUES + 1))
    fi
    
    # Check if it's a non-Docker gunicorn
    if ps aux | grep -v grep | grep -q "gunicorn.*8000"; then
        echo "   → Non-Docker gunicorn process found"
        echo "   → Will need to kill: sudo pkill -f gunicorn"
        ISSUES=$((ISSUES + 1))
    fi
else
    echo "✅ Port 8000 is free"
fi

echo ""
echo "2️⃣  Checking Docker installation..."
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ Docker not installed!"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ Docker installed: $(docker --version)"
fi

if ! command -v docker-compose >/dev/null 2>&1; then
    echo "❌ docker-compose not installed!"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ docker-compose installed: $(docker-compose --version)"
fi

echo ""
echo "3️⃣  Checking nginx configuration..."
if [ -f /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf ]; then
    PROXY_PORT=$(grep -oP 'proxy_pass.*127\.0\.0\.1:\K\d+' /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf | head -1)
    if [ "$PROXY_PORT" != "8000" ]; then
        echo "⚠️  Nginx proxying to port $PROXY_PORT (should be 8000)"
        echo "   → Will need to update nginx config"
        ISSUES=$((ISSUES + 1))
    else
        echo "✅ Nginx configured for port 8000"
    fi
else
    echo "⚠️  Nginx location config not found"
    ISSUES=$((ISSUES + 1))
fi

echo ""
echo "4️⃣  Checking SSL certificates..."
if sudo [ -f /etc/letsencrypt/live/visa-bulletin.us/fullchain.pem ]; then
    echo "✅ SSL certificates exist"
else
    echo "⚠️  SSL certificates not found"
    echo "   → Will attempt to obtain during deployment"
fi

echo ""
echo "5️⃣  Checking disk space..."
DISK_USAGE=$(df -h /opt | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -gt 85 ]; then
    echo "⚠️  Disk usage high: ${DISK_USAGE}%"
    echo "   → Consider cleanup: sudo docker system prune"
    ISSUES=$((ISSUES + 1))
else
    echo "✅ Disk usage OK: ${DISK_USAGE}%"
fi

echo ""
echo "6️⃣  Checking Docker service..."
if systemctl is-active --quiet docker; then
    echo "✅ Docker service running"
else
    echo "❌ Docker service not running"
    ISSUES=$((ISSUES + 1))
fi

echo ""
echo "7️⃣  Checking for stale containers..."
if docker ps -a | grep -q visa_bulletin; then
    echo "⚠️  Found existing visa_bulletin containers:"
    docker ps -a | grep visa_bulletin | awk '{print "   -", $1, $2, $7}'
    echo "   → Will be recreated during deployment"
else
    echo "✅ No stale containers"
fi

echo ""
echo "═══════════════════════════════════════"
if [ $ISSUES -eq 0 ]; then
    echo "✅ ALL CHECKS PASSED - Ready to deploy"
    exit 0
else
    echo "⚠️  FOUND $ISSUES ISSUE(S) - Review before deploying"
    echo ""
    echo "Suggested fixes:"
    echo "  ssh ${AWS_USER}@${AWS_HOST}"
    echo "  sudo systemctl stop visa-bulletin  # If running"
    echo "  sudo pkill -f gunicorn             # If needed"
    echo "  cd /opt/visa_bulletin && sudo docker-compose down  # Clean slate"
    exit 1
fi
ENDSSH

if [ $? -eq 0 ]; then
    echo ""
    echo "🎉 Environment ready for deployment!"
    echo ""
    echo "Next steps:"
    echo "  ./scripts/deploy.sh $SSH_KEY <version>"
    echo ""
else
    echo ""
    echo "⚠️  Fix issues above before deploying"
    echo ""
fi
