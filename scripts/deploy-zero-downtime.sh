#!/bin/bash
#
# Zero-downtime blue-green deployment script for visa-bulletin
#
# Usage: ./scripts/deploy-zero-downtime.sh [ssh-key-path] [image-tag]
#
# How it works:
# 1. Detect which environment (blue/green) is currently active
# 2. Deploy new version to inactive environment
# 3. Wait for health checks to pass
# 4. Switch Nginx proxy atomically
# 5. Stop old environment
#
# No downtime because:
# - New containers start before old ones stop
# - Nginx switches only after new containers are healthy
# - Atomic Nginx reload (no dropped connections)

set -e

# Configuration
AWS_HOST="3.227.71.176"
AWS_USER="ubuntu"
DEFAULT_KEY="$HOME/.ssh/lightsail_visa_bulletin"
DEPLOY_DIR="/opt/visa_bulletin"

# Parse arguments
SSH_KEY="${1:-$DEFAULT_KEY}"
IMAGE_TAG="${2:-latest}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🚀 ZERO-DOWNTIME BLUE-GREEN DEPLOYMENT"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Host: $AWS_HOST"
echo "Key:  $SSH_KEY"
echo "Image tag: $IMAGE_TAG"
echo ""

# SSH command wrapper
SSH_CMD="ssh -i $SSH_KEY ${AWS_USER}@${AWS_HOST}"

echo "📥 Pulling latest configs from GitHub..."
$SSH_CMD "cd $DEPLOY_DIR && git pull origin main"

echo ""
echo "🔍 Detecting active environment..."

# Detect which environment is currently active by checking Nginx config
# Extract port number from proxy_pass lines (handles semicolon)
ACTIVE_ENV=$($SSH_CMD "grep -oP '127\\.0\\.0\\.1:\\K\\d+' $DEPLOY_DIR/deployment/nginx/visa-bulletin-locations.conf | head -1")

if [ "$ACTIVE_ENV" = "8000" ]; then
    ACTIVE_COLOR="blue"
    NEW_COLOR="green"
    NEW_PORT="8001"
    OLD_PORT="8000"
    NEW_COMPOSE="docker-compose.green.yml"
    OLD_COMPOSE="docker-compose.blue.yml"
elif [ "$ACTIVE_ENV" = "8001" ]; then
    ACTIVE_COLOR="green"
    NEW_COLOR="blue"
    NEW_PORT="8000"
    OLD_PORT="8001"
    NEW_COMPOSE="docker-compose.blue.yml"
    OLD_COMPOSE="docker-compose.green.yml"
else
    # No active environment or unknown port - default to deploying blue
    echo "⚠️  No active environment detected (Nginx points to port $ACTIVE_ENV)"
    echo "   Defaulting to blue deployment on port 8000"
    ACTIVE_COLOR="none"
    NEW_COLOR="blue"
    NEW_PORT="8000"
    OLD_PORT=""
    NEW_COMPOSE="docker-compose.blue.yml"
    OLD_COMPOSE=""
fi

echo "✅ Active: $ACTIVE_COLOR ($OLD_PORT) → Deploying to: $NEW_COLOR ($NEW_PORT)"
echo ""

echo "🐳 Pulling Docker image on remote server..."
$SSH_CMD "cd $DEPLOY_DIR && IMAGE_TAG=$IMAGE_TAG docker-compose -f $NEW_COMPOSE pull"

echo ""
echo "🧹 Stopping existing $NEW_COLOR environment (if any)..."
$SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE down 2>/dev/null || true"

echo "🚀 Starting $NEW_COLOR environment on port $NEW_PORT..."
$SSH_CMD "cd $DEPLOY_DIR && IMAGE_TAG=$IMAGE_TAG docker-compose -f $NEW_COMPOSE up -d"

echo ""
echo "⏳ Waiting for health checks (max 60s)..."
HEALTH_CHECK_COUNT=0
MAX_HEALTH_CHECKS=12

while [ $HEALTH_CHECK_COUNT -lt $MAX_HEALTH_CHECKS ]; do
    sleep 5
    HEALTH_CHECK_COUNT=$((HEALTH_CHECK_COUNT + 1))
    
    # Check container health - only check web container (data-refresh doesn't have healthcheck)
    HEALTH_STATUS=$($SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE ps web-$NEW_COLOR | grep -i healthy" || echo "")
    
    if [ -n "$HEALTH_STATUS" ]; then
        echo "✅ $NEW_COLOR environment is healthy!"
        break
    fi
    
    echo "   Attempt $HEALTH_CHECK_COUNT/$MAX_HEALTH_CHECKS - waiting for healthy status..."
    
    if [ $HEALTH_CHECK_COUNT -eq $MAX_HEALTH_CHECKS ]; then
        echo ""
        echo "❌ Health checks failed after ${MAX_HEALTH_CHECKS} attempts (60s)"
        echo ""
        echo "Container status:"
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE ps"
        echo ""
        echo "Recent logs:"
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE logs --tail=30"
        echo ""
        echo "Rolling back - stopping $NEW_COLOR environment..."
        $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE down"
        exit 1
    fi
done

echo ""
echo "🔄 Switching Nginx proxy: $OLD_PORT → $NEW_PORT"

# Update Nginx configuration atomically
# Update ALL instances of the port in the locations config file (handles semicolon)
$SSH_CMD "sudo sed -i 's/127\\.0\\.0\\.1:$OLD_PORT/127.0.0.1:$NEW_PORT/g' $DEPLOY_DIR/deployment/nginx/visa-bulletin-locations.conf"

# Test Nginx configuration
echo "   Testing Nginx configuration..."
$SSH_CMD "sudo nginx -t"

# Reload Nginx (zero-downtime reload)
echo "   Reloading Nginx..."
$SSH_CMD "sudo systemctl reload nginx"

echo "✅ Nginx switched to port $NEW_PORT"

echo ""
echo "⏳ Waiting 10 seconds to ensure traffic is flowing..."
sleep 10

echo ""
echo "🧹 Stopping old $ACTIVE_COLOR environment..."
if [ "$ACTIVE_COLOR" != "none" ] && [ -n "$OLD_COMPOSE" ]; then
    $SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $OLD_COMPOSE down"
    echo "✅ Old environment stopped and removed"
else
    echo "ℹ️  No old environment to stop"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "✅ DEPLOYMENT COMPLETE - ZERO DOWNTIME"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
echo "Active environment: $NEW_COLOR (port $NEW_PORT)"
echo "Image deployed: ghcr.io/vyakunin/visa_bulletin:$IMAGE_TAG"
echo ""
echo "🔍 Verifying deployment..."

# Check site is responding
HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" https://visa-bulletin.us)
if [ "$HTTP_STATUS" = "200" ]; then
    echo "✅ Site is responding: https://visa-bulletin.us (HTTP $HTTP_STATUS)"
else
    echo "⚠️  Site returned HTTP $HTTP_STATUS"
fi

echo ""
echo "📊 Container status:"
$SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE ps"

echo ""
echo "📝 Recent logs:"
$SSH_CMD "cd $DEPLOY_DIR && docker-compose -f $NEW_COMPOSE logs --tail=10 web-$NEW_COLOR"

echo ""
echo "🎉 Deployment successful!"
echo ""
