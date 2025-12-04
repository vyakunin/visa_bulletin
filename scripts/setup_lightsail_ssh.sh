#!/bin/bash
# Setup SSH configuration for AWS Lightsail
# This script helps configure SSH access to the Lightsail instance

set -e

LIGHTSAIL_IP="3.227.71.176"
LIGHTSAIL_USER="ubuntu"
SSH_CONFIG="$HOME/.ssh/config"
SSH_DIR="$HOME/.ssh"

echo "🔐 Setting up SSH access to AWS Lightsail"
echo ""

# Create .ssh directory if it doesn't exist
mkdir -p "$SSH_DIR"
chmod 700 "$SSH_DIR"

# Find SSH key
echo "🔍 Looking for SSH key..."
SSH_KEY=""

# Check common locations
KEY_LOCATIONS=(
    "$HOME/Downloads/VisaBulletin.pem"
    "$HOME/Downloads/LightsailDefaultKey-*.pem"
    "$HOME/.ssh/visa_bulletin.pem"
    "$HOME/.ssh/lightsail.pem"
    "$HOME/.ssh/id_rsa"
    "$HOME/.ssh/id_ed25519"
)

for key_pattern in "${KEY_LOCATIONS[@]}"; do
    # Handle wildcards
    for key in $key_pattern; do
        if [ -f "$key" ]; then
            SSH_KEY="$key"
            echo "✅ Found SSH key: $SSH_KEY"
            break 2
        fi
    done
done

if [ -z "$SSH_KEY" ]; then
    echo "⚠️  No SSH key found in common locations"
    echo ""
    echo "Please provide the path to your Lightsail SSH key (.pem file):"
    read -r SSH_KEY
    
    if [ ! -f "$SSH_KEY" ]; then
        echo "❌ SSH key not found: $SSH_KEY"
        exit 1
    fi
fi

# Make key readable only by owner
chmod 400 "$SSH_KEY" 2>/dev/null || echo "⚠️  Could not set key permissions (may need to run manually: chmod 400 $SSH_KEY)"

# Add to SSH config
echo ""
echo "📝 Adding Lightsail configuration to SSH config..."

# Backup existing config if it exists
if [ -f "$SSH_CONFIG" ]; then
    cp "$SSH_CONFIG" "$SSH_CONFIG.backup.$(date +%Y%m%d_%H%M%S)"
    echo "✅ Backed up existing SSH config"
fi

# Check if entry already exists
if grep -q "Host lightsail" "$SSH_CONFIG" 2>/dev/null; then
    echo "⚠️  Lightsail entry already exists in SSH config"
    echo "   Edit $SSH_CONFIG manually to update if needed"
else
    # Add new entry
    cat >> "$SSH_CONFIG" << EOF

# AWS Lightsail - Visa Bulletin Project
Host lightsail
    HostName $LIGHTSAIL_IP
    User $LIGHTSAIL_USER
    IdentityFile $SSH_KEY
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null

Host lightsail-visa-bulletin
    HostName $LIGHTSAIL_IP
    User $LIGHTSAIL_USER
    IdentityFile $SSH_KEY
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
EOF
    chmod 600 "$SSH_CONFIG"
    echo "✅ Added Lightsail configuration to SSH config"
fi

echo ""
echo "🧪 Testing SSH connection..."
if ssh -o ConnectTimeout=5 -o StrictHostKeyChecking=no -i "$SSH_KEY" "${LIGHTSAIL_USER}@${LIGHTSAIL_IP}" "echo 'Connection successful!'" 2>/dev/null; then
    echo "✅ SSH connection successful!"
    echo ""
    echo "You can now connect using:"
    echo "  ssh lightsail"
    echo "  or"
    echo "  ssh -i $SSH_KEY ${LIGHTSAIL_USER}@${LIGHTSAIL_IP}"
else
    echo "⚠️  Could not connect to Lightsail"
    echo ""
    echo "Possible issues:"
    echo "  1. Instance might be stopped - check AWS Lightsail console"
    echo "  2. Firewall might be blocking SSH (port 22)"
    echo "  3. IP address might have changed"
    echo "  4. SSH key might be incorrect"
    echo ""
    echo "You can still try connecting manually:"
    echo "  ssh -i $SSH_KEY ${LIGHTSAIL_USER}@${LIGHTSAIL_IP}"
fi

echo ""
echo "📋 Summary:"
echo "  Host: $LIGHTSAIL_IP"
echo "  User: $LIGHTSAIL_USER"
echo "  Key:  $SSH_KEY"
echo "  SSH Config: $SSH_CONFIG"
echo ""
echo "✅ Setup complete!"

