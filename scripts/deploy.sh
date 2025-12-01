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
echo "🔄 Restarting application..."
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

