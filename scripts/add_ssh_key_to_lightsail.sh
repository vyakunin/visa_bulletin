#!/bin/bash
# Script to add SSH public key to Lightsail instance
# This assumes you have temporary access via the old key or Lightsail console

set -e

LIGHTSAIL_IP="3.227.71.176"
LIGHTSAIL_USER="ubuntu"
PUBLIC_KEY="$HOME/.ssh/lightsail_visa_bulletin.pub"

if [ ! -f "$PUBLIC_KEY" ]; then
    echo "❌ Public key not found: $PUBLIC_KEY"
    echo "   Run the key generation first"
    exit 1
fi

echo "🔐 Adding SSH key to Lightsail instance"
echo ""
echo "Public key to add:"
cat "$PUBLIC_KEY"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Choose method to add the key:"
echo ""
echo "Option 1: Via existing SSH access (if you have old key)"
echo "  If you have the old .pem key, provide the path:"
read -p "  Old key path (or press Enter to skip): " OLD_KEY

if [ -n "$OLD_KEY" ] && [ -f "$OLD_KEY" ]; then
    echo ""
    echo "📤 Adding key via SSH..."
    chmod 400 "$OLD_KEY"
    
    # Read public key and add to authorized_keys
    PUBLIC_KEY_CONTENT=$(cat "$PUBLIC_KEY")
    
    ssh -i "$OLD_KEY" -o StrictHostKeyChecking=no "${LIGHTSAIL_USER}@${LIGHTSAIL_IP}" << EOF
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo "$PUBLIC_KEY_CONTENT" >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
echo "✅ Key added successfully"
EOF
    
    echo ""
    echo "✅ Key added to Lightsail instance!"
    echo ""
    echo "🧪 Testing new key..."
    if ssh -i ~/.ssh/lightsail_visa_bulletin -o StrictHostKeyChecking=no "${LIGHTSAIL_USER}@${LIGHTSAIL_IP}" "echo 'Connection successful!'" 2>/dev/null; then
        echo "✅ New key works! You can now use: ssh lightsail"
    else
        echo "⚠️  Connection test failed. The key may need a moment to propagate."
    fi
    exit 0
fi

echo ""
echo "Option 2: Via AWS Lightsail Console (Browser)"
echo ""
echo "1. Go to: https://lightsail.aws.amazon.com/"
echo "2. Click on your instance: visa-bulletin-prod (or similar)"
echo "3. Click 'Connect using SSH' (browser-based terminal)"
echo "4. Run these commands in the browser terminal:"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "mkdir -p ~/.ssh"
echo "chmod 700 ~/.ssh"
echo "echo '$(cat "$PUBLIC_KEY")' >> ~/.ssh/authorized_keys"
echo "chmod 600 ~/.ssh/authorized_keys"
echo "cat ~/.ssh/authorized_keys"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "After adding the key, press Enter to test the connection..."
read -p "Press Enter when ready to test..."

echo ""
echo "🧪 Testing SSH connection with new key..."
if ssh -i ~/.ssh/lightsail_visa_bulletin -o StrictHostKeyChecking=no "${LIGHTSAIL_USER}@${LIGHTSAIL_IP}" "echo 'Connection successful!'" 2>/dev/null; then
    echo "✅ SSH connection successful with new key!"
else
    echo "⚠️  Connection failed. Please verify:"
    echo "   1. The key was added correctly to ~/.ssh/authorized_keys"
    echo "   2. The instance is running"
    echo "   3. Port 22 is open in the firewall"
fi

