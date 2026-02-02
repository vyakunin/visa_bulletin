# Domain & HTTPS Setup Guide

## Domain: visa-bulletin.us

**Production IP:** 44.209.204.255 (static, `prod_2Gb_vm`)  
**Backup IP:** 3.227.71.176 (static, `backup_0_5Gb_vm`)  
**IPv6 (backup):** 2600:1f18:7441:2700:b30b:7030:f8a3:fec1

**Analytics (GoatCounter):** No special setup on prod. The app injects `ANALYTICS_SCRIPT` from the environment; Docker Compose and systemd already set it to `https://vyakunin.goatcounter.com/count`. As long as the site is served with that env, page views appear at https://vyakunin.goatcounter.com/.

**Redis memory limit (systemd prod):** When the app runs with systemd and Redis on the host (`REDIS_URL=redis://127.0.0.1:6379/1`), set a maxmemory so Redis doesn't use unbounded RAM. Copy `deployment/redis/redis-maxmemory.conf` to the Redis config dir (e.g. `/etc/redis/redis.conf.d/99-maxmemory.conf`) and restart Redis. See `deployment/redis/redis-maxmemory.conf` for details.

---

## Flip DNS to production (44.209.204.255)

Use this when you want visa-bulletin.us to point at the production (2GB) instance.

### 1. Pre-check on prod (before DNS change)

```bash
ssh prod_2Gb_vm "grep ALLOWED_HOSTS /opt/visa_bulletin/.env"
# Must include: visa-bulletin.us, www.visa-bulletin.us, 44.209.204.255

ssh prod_2Gb_vm "curl -sI http://localhost:8000/ | head -1"
# Expect: HTTP/1.1 200

ssh prod_2Gb_vm "sudo nginx -t && curl -sI http://localhost/ | head -1"
# Nginx OK, and 200 or 302 from Nginx
```

Ensure Lightsail firewall allows 80 and 443 (Network tab → IPv4 firewall).

### 2. Update DNS at registrar

Set A records to **44.209.204.255**:

| Type | Name | Value        | TTL  |
|------|------|--------------|------|
| A    | @    | 44.209.204.255 | 300 |
| A    | www  | 44.209.204.255 | 300 |

(Optional) If you use AAAA, either point them to prod's IPv6 or remove them until prod has a static IPv6.

Verify after 5–30 min:

```bash
dig visa-bulletin.us +short   # should show 44.209.204.255
```

### 3. HTTPS on prod (after DNS points to 44.209.204.255)

```bash
ssh prod_2Gb_vm

# Install Certbot if not already
sudo snap install --classic certbot
sudo ln -sf /snap/bin/certbot /usr/bin/certbot

# Obtain certificate (Nginx must be serving the domain on port 80)
sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us
# Choose: Redirect HTTP to HTTPS (recommended)

# Verify
sudo certbot certificates
curl -I https://visa-bulletin.us
sudo certbot renew --dry-run
```

### 4. Monitoring

- **UptimeRobot** (https://uptimerobot.com): Add HTTP(S) monitor for `https://visa-bulletin.us`, interval 5 min, alert on non-200 or timeout.
- **Certificate expiry:** UptimeRobot “Keyword” monitor or a dedicated SSL monitor; alert ~30 days before expiry (Certbot auto-renews; this catches failures).
- Optional: second monitor for `https://www.visa-bulletin.us` or a key page (e.g. `/salaries/`).

### 5. Post–DNS flip verification

```bash
curl -I https://visa-bulletin.us
curl -I https://www.visa-bulletin.us
curl -I http://visa-bulletin.us
# HTTP should 301/302 to HTTPS; HTTPS should 200
```

### 6. If https://visa-bulletin.us doesn’t load in the browser

**Symptom:** Page never loads, or “connection timed out” for `https://visa-bulletin.us`.

**Cause:** Port **443** is not open in the **Lightsail firewall** (Nginx is listening on the server, but traffic is blocked before it reaches the instance).

**Fix (console):** In AWS Lightsail → your instance (44.209.204.255) → **Networking** tab → **IPv4 firewall** → **+ Add rule**:

- Application: **Custom**
- Protocol: **TCP**
- Port: **443**
- Source: **Anywhere** (0.0.0.0/0) or restrict to your IP

**Fix (AWS CLI):** After `aws login` (or with valid AWS credentials):

```bash
aws lightsail open-instance-public-ports \
  --instance-name VisaBulletin2GB \
  --port-info fromPort=443,toPort=443,protocol=tcp \
  --region us-east-1
```

This only opens 443; existing ports (e.g. 80, 22) stay open. Then retry `https://visa-bulletin.us/` in the browser.

---

## Step 1: Purchase Domain

### Recommended Registrars
- **Namecheap**: ~$8/year for `.us` domains
- **Google Domains** (Squarespace): ~$12/year
- **Porkbun**: ~$6/year

### Purchase Instructions
1. Go to registrar website
2. Search for `visa-bulletin.us`
3. Add to cart and complete purchase
4. **Important**: Disable auto-renewal of extra services (privacy protection usually included free)

---

## Step 2: Configure DNS

**Add these DNS records at your registrar:**

| Type | Name | Value | TTL |
|------|------|-------|-----|
| A | @ | 3.227.71.176 | 300 |
| A | www | 3.227.71.176 | 300 |
| AAAA | @ | 2600:1f18:7441:2700:b30b:7030:f8a3:fec1 | 300 |
| AAAA | www | 2600:1f18:7441:2700:b30b:7030:f8a3:fec1 | 300 |

### Instructions by Registrar

#### Namecheap
1. Login → Domain List → Manage
2. Advanced DNS → Add New Record
3. Add both A records and AAAA records (for IPv6) above
4. Wait 5-30 minutes for propagation

#### Porkbun
1. Login → Domain Management
2. DNS → Add → A Record
3. Add both records
4. Wait 5-30 minutes

#### Google Domains (Squarespace)
1. Domains → Manage → DNS
2. Custom Records → Create new record
3. Add both A records
4. Wait 5-30 minutes

### Verify DNS Propagation

```bash
# Check if DNS is working (run on your local machine)
nslookup visa-bulletin.us
dig visa-bulletin.us +short

# Should return: 3.227.71.176
```

**Wait until DNS resolves before proceeding to Step 3!**

---

## Step 3: Install SSL Certificate (Let's Encrypt)

Run these commands on your AWS server:

```bash
# SSH into server
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176

# Install Certbot
sudo snap install --classic certbot
sudo ln -s /snap/bin/certbot /usr/bin/certbot

# Obtain SSL certificate
sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us

# Follow prompts:
# - Enter email address (for renewal notifications)
# - Agree to Terms of Service: Y
# - Share email with EFF: N (optional)
# - Redirect HTTP to HTTPS: 2 (Yes, recommended)
```

**Certbot will automatically:**
- Obtain SSL certificate
- Configure Nginx
- Set up HTTPS redirect
- Create auto-renewal cron job

---

## Step 4: Update Django Settings

Edit `/opt/visa_bulletin/django_config/settings.py`:

```python
# Update ALLOWED_HOSTS
ALLOWED_HOSTS = ['visa-bulletin.us', 'www.visa-bulletin.us', '3.227.71.176', 'localhost']

# Add HTTPS settings (add at bottom)
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'
```

Apply changes:

```bash
cd /opt/visa_bulletin
sudo systemctl restart visa-bulletin
```

---

## Step 5: Verify HTTPS

Test your site:

```bash
# Check HTTP redirect
curl -I http://visa-bulletin.us
# Should return: 301 or 302 redirect to https://

# Check HTTPS
curl -I https://visa-bulletin.us
# Should return: 200 OK

# Test SSL certificate
openssl s_client -connect visa-bulletin.us:443 -servername visa-bulletin.us
# Should show: Verify return code: 0 (ok)
```

Visit in browser:
- https://visa-bulletin.us ✅
- https://www.visa-bulletin.us ✅
- http://visa-bulletin.us → https://visa-bulletin.us ✅

---

## Step 6: Test Auto-Renewal

Let's Encrypt certificates expire every 90 days. Certbot sets up auto-renewal.

```bash
# Test renewal (dry run)
sudo certbot renew --dry-run

# Should output: "Congratulations, all simulated renewals succeeded"
```

Auto-renewal runs twice daily via systemd timer:

```bash
# Check renewal timer status
sudo systemctl status snap.certbot.renew.timer

# View renewal logs
sudo journalctl -u snap.certbot.renew.service
```

---

## Troubleshooting

### DNS Not Resolving

```bash
# Check DNS from multiple locations
# https://www.whatsmydns.net/#A/visa-bulletin.us

# Common issues:
# - TTL too high (set to 300 for faster updates)
# - Wrong nameservers (use registrar's default)
# - Propagation delay (wait up to 48 hours, usually < 30 min)
```

### Certbot Fails

```bash
# Error: "Challenge failed"
# Solution: Ensure DNS is resolving correctly first

# Error: "Port 80 blocked"
# Solution: Check AWS firewall allows port 80
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp

# Error: "Nginx test failed"
# Solution: Fix Nginx syntax
sudo nginx -t
```

### HTTPS Not Working

```bash
# Check Nginx is running
sudo systemctl status nginx

# Check certificate files exist
sudo ls -la /etc/letsencrypt/live/visa-bulletin.us/

# Check Nginx SSL configuration
sudo cat /etc/nginx/sites-enabled/default | grep ssl

# Restart Nginx
sudo systemctl restart nginx
```

### Mixed Content Warnings

If you see "Not Secure" in browser despite HTTPS:
- Ensure all resources (CSS, JS, images) use HTTPS URLs
- Check for `http://` hardcoded links in HTML
- Use relative URLs (`/static/...`) instead of absolute

---

## Security Best Practices

### 1. Enable HSTS (HTTP Strict Transport Security)

Add to Nginx config (`/etc/nginx/sites-available/default`):

```nginx
add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
```

### 2. SSL Labs Test

Test your SSL configuration:
https://www.ssllabs.com/ssltest/analyze.html?d=visa-bulletin.us

**Target: A+ rating**

### 3. Configure Security Headers

Already added in Django settings above:
- `X-Frame-Options: DENY`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`

### 4. Set up Monitoring

Free options:
- **UptimeRobot**: https://uptimerobot.com (50 monitors free)
- **Pingdom**: https://www.pingdom.com (free tier)
- **StatusCake**: https://www.statuscake.com (free tier)

Monitor both:
- https://visa-bulletin.us (should return 200)
- Certificate expiration (should alert before 30 days)

---

## Maintenance

### Certificate Renewal

Certificates auto-renew, but you can manually renew:

```bash
sudo certbot renew
sudo systemctl reload nginx
```

### Update Domain

To add/remove domains:

```bash
# Add new domain
sudo certbot --nginx -d visa-bulletin.us -d www.visa-bulletin.us -d new.visa-bulletin.us

# Remove and reissue
sudo certbot delete --cert-name visa-bulletin.us
# Then run certbot again with desired domains
```

### Backup Certificates

```bash
# Backup Let's Encrypt directory
sudo tar -czf letsencrypt-backup-$(date +%Y%m%d).tar.gz /etc/letsencrypt/

# Store backup securely (not on same server)
```

---

## Cost Summary

| Item | Cost | Frequency |
|------|------|-----------|
| Domain (visa-bulletin.us) | $6-8 | Yearly |
| SSL Certificate (Let's Encrypt) | FREE | Auto-renew |
| AWS Lightsail | $5 | Monthly |
| **TOTAL** | **$66-76/year** | **($5.50-6.30/month)** |

---

## Post-Setup Checklist

- [x] Domain purchased ✅ (Namecheap, $8.88/year)
- [x] DNS configured (A records for @ and www) ✅
- [x] DNS propagation verified ✅ (instant)
- [x] SSL certificate installed ✅ (Let's Encrypt via Certbot)
- [x] HTTPS working for both visa-bulletin.us and www.visa-bulletin.us ✅
- [x] HTTP redirects to HTTPS ✅ (automatic via Certbot)
- [x] Django ALLOWED_HOSTS updated ✅
- [x] Auto-renewal configured ✅ (Certbot snap timer)
- [ ] Security headers configured (optional enhancement)
- [ ] SSL Labs test (optional - should be A+)
- [ ] Uptime monitoring set up (optional)
- [x] Site tested on mobile/desktop ✅

**Deployment Date:** December 1, 2025  
**Live Site:** https://visa-bulletin.us

---

## Support

If you encounter issues:
1. Check the Troubleshooting section above
2. View Nginx error logs: `sudo tail -f /var/log/nginx/error.log`
3. View Certbot logs: `sudo journalctl -u snap.certbot.renew.service -n 50`
4. Test DNS: https://www.whatsmydns.net/
5. Test SSL: https://www.ssllabs.com/ssltest/

---

**Estimated Setup Time:** 30-60 minutes (mostly waiting for DNS)

**Difficulty:** Easy (mostly copy-paste commands)

Good luck! 🚀

