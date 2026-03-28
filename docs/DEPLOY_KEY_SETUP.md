# Deploy Key Setup (one-time per instance)

Required for `git push origin staging:prod` during graduation (step 10). Both instances need the same key since they swap roles.

## Setup (run once per instance)

```bash
# 1. Generate key on prod (one-time)
ssh prod_2Gb_vm "ssh-keygen -t ed25519 -f /home/ubuntu/.ssh/github_deploy_key -N '' -C 'visa-bulletin-deploy-key'"
ssh prod_2Gb_vm "cat /home/ubuntu/.ssh/github_deploy_key.pub"

# 2. Add public key to GitHub: https://github.com/vyakunin/visa_bulletin/settings/keys/new
#    Title: "Lightsail instance deploy key", check "Allow write access"

# 3. Configure SSH on prod
ssh prod_2Gb_vm "cat >> /home/ubuntu/.ssh/config << 'EOF'

Host github.com
  IdentityFile /home/ubuntu/.ssh/github_deploy_key
  IdentitiesOnly yes
EOF
cd /opt/visa_bulletin && git remote set-url origin git@github.com:vyakunin/visa_bulletin.git"

# 4. Copy key to staging and configure (start it first if stopped)
ssh prod_2Gb_vm "cat /home/ubuntu/.ssh/github_deploy_key" | ssh staging_2Gb_vm "cat > /home/ubuntu/.ssh/github_deploy_key && chmod 600 /home/ubuntu/.ssh/github_deploy_key"
ssh prod_2Gb_vm "cat /home/ubuntu/.ssh/github_deploy_key.pub" | ssh staging_2Gb_vm "cat > /home/ubuntu/.ssh/github_deploy_key.pub"
ssh staging_2Gb_vm "cat >> /home/ubuntu/.ssh/config << 'EOF'

Host github.com
  IdentityFile /home/ubuntu/.ssh/github_deploy_key
  IdentitiesOnly yes
EOF
cd /opt/visa_bulletin && git remote set-url origin git@github.com:vyakunin/visa_bulletin.git"

# 5. Verify auth on both
ssh prod_2Gb_vm "ssh -o StrictHostKeyChecking=no -T git@github.com 2>&1"
ssh staging_2Gb_vm "ssh -o StrictHostKeyChecking=no -T git@github.com 2>&1"
```

## Key Details

- Path: `/home/ubuntu/.ssh/github_deploy_key` (same on both instances)
- Both instances use the **same key** — copy from prod to staging, don't generate separately
- Survives graduation rotation (key is on the instance, not the IP)
- If graduation fails with "git push staging:prod failed": check key exists, remote is SSH (`git remote -v`), GitHub auth works (`ssh -T git@github.com`)

## Verify Key Exists

Before graduation, run:

```bash
ssh prod_2Gb_vm "test -f /home/ubuntu/.ssh/github_deploy_key && echo ok"
ssh staging_2Gb_vm "test -f /home/ubuntu/.ssh/github_deploy_key && echo ok"
```
