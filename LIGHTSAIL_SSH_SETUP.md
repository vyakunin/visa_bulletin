# Lightsail SSH Key Setup

## ✅ Step 1: Key Generated

A new SSH key has been generated:
- **Private key**: `~/.ssh/lightsail_visa_bulletin`
- **Public key**: `~/.ssh/lightsail_visa_bulletin.pub`
- **Fingerprint**: `SHA256:lBsLdH1B5thgyohCbfo5jqfadCXjIHhi/UMdyoXwHao`

## 📋 Step 2: Add Public Key to Lightsail

You need to add the public key to your Lightsail instance. Choose one method:

### Method A: Via AWS Lightsail Console (Easiest)

1. Go to: https://lightsail.aws.amazon.com/
2. Click on your instance (e.g., `visa-bulletin-prod`)
3. Click **"Connect using SSH"** (opens browser-based terminal)
4. Run these commands in the browser terminal:

```bash
mkdir -p ~/.ssh
chmod 700 ~/.ssh
echo 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIIHUhxqP1pAIvm8jMq/lCDwFBPJhTedyXRKCSARmyBtX lightsail-visa-bulletin-20251204' >> ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys
```

### Method B: Via Existing SSH Access (if you have old key)

If you have the old `.pem` key file, run:

```bash
./scripts/add_ssh_key_to_lightsail.sh
```

The script will prompt for the old key path and automatically add the new key.

### Method C: Manual SSH (if you have old key)

```bash
# Replace OLD_KEY.pem with your actual key file
OLD_KEY="~/Downloads/YourOldKey.pem"
PUBLIC_KEY=$(cat ~/.ssh/lightsail_visa_bulletin.pub)

ssh -i "$OLD_KEY" ubuntu@3.227.71.176 "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '$PUBLIC_KEY' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"
```

## 🧪 Step 3: Test Connection

After adding the key, test the connection:

```bash
ssh lightsail
```

Or with explicit key:

```bash
ssh -i ~/.ssh/lightsail_visa_bulletin ubuntu@3.227.71.176
```

You should see:
```
ubuntu@ip-xxx-xxx-xxx-xxx:~$
```

## 📝 SSH Config

SSH config has been set up at `~/.ssh/config`. You can now use:

- `ssh lightsail` - Short alias
- `ssh lightsail-visa-bulletin` - Alternative alias

Both connect to: `ubuntu@3.227.71.176`

## 🔐 Security Notes

- Private key (`lightsail_visa_bulletin`) should never be shared or committed to git
- Public key (`lightsail_visa_bulletin.pub`) is safe to share
- Key permissions are set correctly (600 for private, 644 for public)

## 🆘 Troubleshooting

### "Permission denied (publickey)"
- Verify the public key was added correctly: `cat ~/.ssh/authorized_keys` on the server
- Check key permissions: `chmod 600 ~/.ssh/lightsail_visa_bulletin`
- Ensure the instance is running in Lightsail console

### "Connection refused"
- Check if instance is running
- Verify port 22 is open in Lightsail firewall
- Check if IP address changed: `3.227.71.176`

### "Host key verification failed"
- The SSH config uses `StrictHostKeyChecking no` to avoid this
- Or manually accept: `ssh-keyscan 3.227.71.176 >> ~/.ssh/known_hosts`

## ✅ Quick Reference

```bash
# Connect to Lightsail
ssh lightsail

# Copy file to Lightsail
scp file.txt lightsail:/opt/visa_bulletin/

# Run command on Lightsail
ssh lightsail "cd /opt/visa_bulletin && git pull"

# View public key (to add to server)
cat ~/.ssh/lightsail_visa_bulletin.pub
```

