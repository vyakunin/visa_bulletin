# 📊 Analytics Setup - Quick Start

Your site is ready for analytics! Choose your provider:

---

## ⭐ Option 1: GoatCounter (FREE - Recommended)

**Best for:** Free, simple, privacy-first analytics

### Setup (5 minutes):

1. **Sign up:** https://www.goatcounter.com
   - Click "Sign up"
   - Choose a code (e.g., `visabulletin`)
   - Your dashboard: `https://visabulletin.goatcounter.com`

2. **Get tracking code:**
   After signup, you'll see:
   ```html
   <script data-goatcounter="https://visabulletin.goatcounter.com/count"
           async src="//gc.zgo.at/count.js"></script>
   ```

3. **Add to your site:**
   ```bash
   # SSH to server
   ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176
   
   # Edit service file
   sudo nano /etc/systemd/system/visa-bulletin.service
   
   # Add this line in [Service] section:
   Environment="ANALYTICS_SCRIPT=<script data-goatcounter='https://visabulletin.goatcounter.com/count' async src='//gc.zgo.at/count.js'></script>"
   
   # Save (Ctrl+X, Y, Enter)
   
   # Restart
   sudo systemctl daemon-reload
   sudo systemctl restart visa-bulletin
   ```

4. **Verify:**
   - Visit https://visa-bulletin.us
   - Check dashboard: https://visabulletin.goatcounter.com

**Cost:** FREE for non-commercial use  
**Privacy:** GDPR compliant, no cookies  
**Dashboard:** Simple, functional

---

## Option 2: Umami Cloud ($9/month)

**Best for:** Beautiful dashboard, more features

### Setup (5 minutes):

1. **Sign up:** https://cloud.umami.is
   - Start free trial (then $9/month)
   - Add website: `visa-bulletin.us`

2. **Get tracking code:**
   ```html
   <script defer src="https://cloud.umami.is/script.js" 
           data-website-id="your-website-id"></script>
   ```

3. **Add to your site:**
   ```bash
   ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176
   sudo nano /etc/systemd/system/visa-bulletin.service
   
   # Add in [Service] section:
   Environment="ANALYTICS_SCRIPT=<script defer src='https://cloud.umami.is/script.js' data-website-id='your-website-id'></script>"
   
   sudo systemctl daemon-reload
   sudo systemctl restart visa-bulletin
   ```

**Cost:** $9/month (100K events)  
**Privacy:** GDPR compliant, no cookies  
**Dashboard:** Beautiful, modern

---

## Option 3: Plausible ($9/month)

**Best for:** Beautiful + privacy-focused

### Setup (5 minutes):

1. **Sign up:** https://plausible.io
   - 30-day free trial
   - Add domain: `visa-bulletin.us`

2. **Get tracking code:**
   ```html
   <script defer data-domain="visa-bulletin.us" 
           src="https://plausible.io/js/script.js"></script>
   ```

3. **Add to your site:**
   ```bash
   ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176
   sudo nano /etc/systemd/system/visa-bulletin.service
   
   # Add in [Service] section:
   Environment="ANALYTICS_SCRIPT=<script defer data-domain='visa-bulletin.us' src='https://plausible.io/js/script.js'></script>"
   
   sudo systemctl daemon-reload
   sudo systemctl restart visa-bulletin
   ```

**Cost:** $9/month (10K pageviews)  
**Privacy:** GDPR compliant, no cookies  
**Dashboard:** Beautiful, one-page

---

## 🆚 Comparison

| Feature | GoatCounter | Umami Cloud | Plausible |
|---------|-------------|-------------|-----------|
| **Cost** | FREE | $9/month | $9/month |
| **Dashboard** | Simple | Beautiful | Beautiful |
| **Privacy** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ |
| **Setup** | 5 min | 5 min | 5 min |
| **Features** | Basic | Advanced | Advanced |

---

## 🎯 My Recommendation

**Start with GoatCounter** (FREE):
- It's free forever
- Privacy-respecting
- Simple to set up
- Good enough for your needs
- You can always upgrade later

**Current traffic:** ~9,150 pageviews/month  
→ All options work perfectly

---

## 📊 What You'll See

All options show:
- **Pageviews** (today, this week, this month)
- **Top pages** (which visa categories are popular?)
- **Countries** (where visitors are from)
- **Devices** (mobile vs desktop)
- **Referrers** (how they found your site)
- **Real-time visitors**

---

## 🔧 Quick Deploy Script

Want to deploy with GoatCounter immediately?

```bash
# 1. Sign up at https://www.goatcounter.com (choose code)

# 2. Run this:
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176 << 'EOF'
sudo nano /etc/systemd/system/visa-bulletin.service
# Add this line (replace 'visabulletin' with your code):
# Environment="ANALYTICS_SCRIPT=<script data-goatcounter='https://visabulletin.goatcounter.com/count' async src='//gc.zgo.at/count.js'></script>"
# Save and exit

sudo systemctl daemon-reload
sudo systemctl restart visa-bulletin
EOF

# 3. Visit your site and check dashboard!
```

---

## 🆘 Troubleshooting

### Not seeing analytics?

**Check if script is in page:**
```bash
curl https://visa-bulletin.us | grep -E "(goatcounter|umami|plausible)"
```

**Check environment variable:**
```bash
ssh -i ~/Downloads/VisaBulletin.pem ubuntu@3.227.71.176
sudo systemctl show visa-bulletin | grep ANALYTICS
```

**Hard refresh browser:** Cmd+Shift+R (Mac) or Ctrl+Shift+R (Windows)

---

## ✅ Done!

Once you've chosen and set up your analytics provider, you'll start seeing visitor data immediately!

**Questions?** All three providers have great documentation and support.

