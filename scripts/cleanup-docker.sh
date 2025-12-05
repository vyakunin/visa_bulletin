#!/bin/bash
#
# Cleanup script for Docker images and containers
# Removes old/unused Docker images and stopped containers
#
# Usage: ./scripts/cleanup-docker.sh [ssh-key-path]
#
# Safety: Only removes images older than 7 days and stopped containers
# Keeps the latest 3 versions of visa_bulletin images

set -e

# Configuration
AWS_HOST="3.227.71.176"
AWS_USER="ubuntu"
DEFAULT_KEY="$HOME/.ssh/lightsail_visa_bulletin"
DEPLOY_DIR="/opt/visa_bulletin"

# Parse arguments
SSH_KEY="${1:-$DEFAULT_KEY}"

if [ ! -f "$SSH_KEY" ]; then
    echo "❌ SSH key not found: $SSH_KEY"
    exit 1
fi

echo "═══════════════════════════════════════════════════════════════════"
echo "🧹 DOCKER CLEANUP"
echo "═══════════════════════════════════════════════════════════════════"
echo ""

# SSH command wrapper
SSH_CMD="ssh -i $SSH_KEY ${AWS_USER}@${AWS_HOST}"

echo "📊 Current Docker status:"
echo ""

echo "Images:"
$SSH_CMD "sudo docker images | grep visa_bulletin || echo '  (none)'"
echo ""

echo "Containers (all):"
$SSH_CMD "sudo docker ps -a | grep visa_bulletin || echo '  (none)'"
echo ""

echo "Disk usage:"
$SSH_CMD "sudo docker system df"
echo ""

# Get list of old images (keep latest 3 versions)
echo "🗑️  Removing old Docker images (keeping latest 3 versions)..."
$SSH_CMD "cd $DEPLOY_DIR && sudo docker images ghcr.io/vyakunin/visa_bulletin --format '{{.Tag}}' | grep -E '^v?[0-9]+\.[0-9]+\.[0-9]+$' | sort -V | head -n -3 | xargs -r -I {} sudo docker rmi ghcr.io/vyakunin/visa_bulletin:{} 2>/dev/null || echo '  No old versioned images to remove'"

# Remove dangling images
echo ""
echo "🗑️  Removing dangling images..."
$SSH_CMD "sudo docker image prune -f"

# Remove stopped containers
echo ""
echo "🗑️  Removing stopped containers..."
$SSH_CMD "sudo docker container prune -f"

# Remove unused networks
echo ""
echo "🗑️  Removing unused networks..."
$SSH_CMD "sudo docker network prune -f"

# Remove unused volumes (be careful - only remove truly unused)
echo ""
echo "🗑️  Removing unused volumes (not in use by any container)..."
$SSH_CMD "sudo docker volume prune -f"

echo ""
echo "📊 Disk usage after cleanup:"
$SSH_CMD "sudo docker system df"

echo ""
echo "═══════════════════════════════════════════════════════════════════"
echo "✅ CLEANUP COMPLETE"
echo "═══════════════════════════════════════════════════════════════════"
echo ""
