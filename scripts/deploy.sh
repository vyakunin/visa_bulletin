#!/bin/bash
#
# Deploy visa-bulletin to a host (single stack on port 8000).
# For zero-downtime: deploy to the inactive instance, then switch traffic (DNS/static IP).
#
# Usage: ./scripts/deploy.sh [ssh-key-path] [image-tag] [host]
#   host defaults to prod_2Gb_vm
#
# Steps:
# 1. Pull latest config from git
# 2. Pull Docker image and start stack (docker-compose up -d)
# 3. Wait for health check
# 4. Verify site responds

set -e

AWS_USER="ubuntu"
DEFAULT_KEY="$HOME/.ssh/lightsail_visa_bulletin"
DEPLOY_DIR="/opt/visa_bulletin"
COMPOSE_FILE="deployment/docker-compose.yml"

SSH_KEY="${1:-$DEFAULT_KEY}"
IMAGE_TAG="${2:-latest}"
AWS_HOST="${3:-prod_2Gb_vm}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🚀 DEPLOY (instance-rotation: deploy to this host, then switch traffic)"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Host: $AWS_HOST"
echo "Key:  $SSH_KEY"
echo "Image tag: $IMAGE_TAG"
echo ""

SSH_CMD="ssh -i $SSH_KEY ${AWS_USER}@${AWS_HOST}"

echo "📥 Pulling latest configs from GitHub..."
$SSH_CMD "cd $DEPLOY_DIR && git fetch origin main && git merge --ff-only origin/main || git reset --hard origin/main"

echo ""
echo "🐳 Pulling Docker image..."
$SSH_CMD "cd $DEPLOY_DIR && IMAGE_TAG=$IMAGE_TAG docker-compose -f $COMPOSE_FILE pull"

echo ""
echo "🚀 Starting stack (web + redis on port 8000)..."
$SSH_CMD "cd $DEPLOY_DIR && IMAGE_TAG=$IMAGE_TAG docker-compose -f $COMPOSE_FILE up -d"

echo ""
echo "⏳ Waiting for health check (max 60s)..."
HEALTH_CHECK_COUNT=0
MAX_HEALTH_CHECKS=12

while [ $HEALTH_CHECK_COUNT -lt $MAX_HEALTH_CHECKS ]; do
    sleep 5
    HEALTH_CHECK_COUNT=$((HEALTH_CHECK_COUNT + 1))

    HEALTH_STATUS=$($SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE ps | grep -i healthy" || echo "")

    if [ -n "$HEALTH_STATUS" ]; then
        echo "✅ Stack is healthy!"
        break
    fi

    echo "   Attempt $HEALTH_CHECK_COUNT/$MAX_HEALTH_CHECKS - waiting for healthy status..."

    if [ $HEALTH_CHECK_COUNT -eq $MAX_HEALTH_CHECKS ]; then
        echo ""
        echo "❌ Health checks failed after ${MAX_HEALTH_CHECKS} attempts (60s)"
        echo ""
        echo "Container status:"
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE ps"
        echo ""
        echo "Recent logs:"
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE logs --tail=30"
        echo ""
        echo "Rolling back - stopping stack..."
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE down"
        exit 1
    fi
done

echo ""
echo "🔄 Ensuring nginx is running (port 80 → 8000)..."
$SSH_CMD "sudo systemctl start nginx 2>/dev/null || true; sudo systemctl reload nginx 2>/dev/null || true"

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Image deployed: ghcr.io/vyakunin/visa_bulletin:$IMAGE_TAG"
echo ""
echo "🔍 Verifying deployment..."

if [ "$AWS_HOST" = "prod_2Gb_vm" ]; then
    VERIFY_URL="https://visa-bulletin.us"
else
    VERIFY_URL="http://3.227.71.176"
fi
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" "$VERIFY_URL" || echo "000")
if [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Site is responding: $VERIFY_URL (HTTP $HTTP_STATUS)"
else
    echo "⚠️  Site returned HTTP $HTTP_STATUS at $VERIFY_URL"
fi

echo ""
echo "📊 Container status:"
$SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE ps"

echo ""
echo "📝 Recent logs:"
$SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $COMPOSE_FILE logs --tail=10 web"

echo ""
echo "🎉 Deployment successful!"
echo ""
