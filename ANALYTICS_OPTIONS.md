# 📊 Analytics Options for Visa Bulletin Dashboard

## Current Status

**Analytics Installed:** ❌ None  
**Current Traffic (Dec 1, 2025):**
- **305 HTTP requests** today
- **114 unique IPs** today
- **Most popular:** Family-Sponsored F4 visa class

**Data Source:** Nginx access logs (basic, not stored long-term)

---

## 🎯 Why Add Analytics?

### What You'll Learn:
1. **Traffic Patterns:**
   - Daily/weekly/monthly visitors
   - Peak usage times
   - Geographic distribution

2. **User Behavior:**
   - Which visa categories are most searched (F4? EB-2?)
   - Which countries users check most (China? India? Philippines?)
   - Average time on site
   - Bounce rate

3. **Technical Insights:**
   - Mobile vs desktop usage (currently unknown)
   - Browser/OS distribution
   - Page load performance
   - Error rates

4. **Growth Metrics:**
   - User retention
   - Traffic sources (organic, direct, referral)
   - Goal conversions (if you add goals)

---

## 📊 Analytics Option 1: Plausible Analytics ⭐ (Recommended)

**Best for:** Privacy-focused, simple, beautiful dashboards

### Pros:
- ✅ **Privacy-first** (GDPR, CCPA compliant by design)
- ✅ **No cookie banner needed** (doesn't use cookies)
- ✅ **Lightweight** (< 1KB script)
- ✅ **Simple, clean dashboard** (one-page overview)
- ✅ **Open source** (can self-host)
- ✅ **Real-time data**
- ✅ **EU-owned** (not subject to US surveillance laws)
- ✅ **No user tracking** (privacy-respecting)

### Cons:
- ❌ **Paid** ($9/month for 10K pageviews, $19/month for 100K)
- ❌ **Less detailed** than Google Analytics
- ❌ **No funnel analysis** (basic events only)

### Pricing:
```
10K pageviews/month:   $9/month
100K pageviews/month:  $19/month
200K pageviews/month:  $29/month
```

### Implementation (5 minutes):
```html
<!-- Add to webapp/templates/webapp/base.html <head> -->
<script defer data-domain="visa-bulletin.us" src="https://plausible.io/js/script.js"></script>
```

### What You See:
- Top pages
- Traffic sources (Google, Direct, etc.)
- Countries & devices
- Simple events (button clicks, form submissions)

**Website:** https://plausible.io  
**Demo:** https://plausible.io/plausible.io (see their own analytics)

---

## 📊 Analytics Option 2: GoatCounter

**Best for:** Free, privacy-focused, minimal

### Pros:
- ✅ **100% FREE** for non-commercial use
- ✅ **Privacy-first** (GDPR compliant, no cookies)
- ✅ **Lightweight** (< 3.5KB script)
- ✅ **Open source** (can self-host)
- ✅ **No account limits**
- ✅ **Real-time data**
- ✅ **Very simple setup**

### Cons:
- ❌ **Basic features** (simpler than Plausible)
- ❌ **UI is functional, not beautiful**
- ❌ **Limited event tracking**
- ❌ **Smaller community/ecosystem**

### Pricing:
```
Non-commercial: FREE
Commercial:     €15/month (~$16)
```

### Implementation (5 minutes):
```html
<!-- Add to webapp/templates/webapp/base.html before </body> -->
<script data-goatcounter="https://visabulletin.goatcounter.com/count"
        async src="//gc.zgo.at/count.js"></script>
```

### What You See:
- Pageviews by path
- Referrers
- Browser & screen size
- Countries & regions

**Website:** https://www.goatcounter.com  
**Demo:** https://stats.arp242.net (creator's own site)

---

## 📊 Analytics Option 3: Umami

**Best for:** Self-hosted, full control, open source

### Pros:
- ✅ **Free & open source** (self-hosted)
- ✅ **Privacy-focused** (GDPR compliant)
- ✅ **Beautiful dashboard** (modern UI)
- ✅ **Unlimited websites**
- ✅ **Event tracking**
- ✅ **Real-time data**
- ✅ **Lightweight** (< 2KB script)
- ✅ **PostgreSQL or MySQL**

### Cons:
- ❌ **Self-hosting required** (unless you pay)
- ❌ **Setup time** (30-60 minutes)
- ❌ **Database storage** (SQLite on Lightsail would work)
- ❌ **Maintenance** (updates, backups)

### Pricing:
```
Self-hosted:      FREE (database storage only)
Umami Cloud:      $9/month (100K events)
```

### Implementation (self-hosted on Lightsail):
1. Deploy Umami on your Lightsail instance
2. Add tracking script to base.html
3. Use SQLite database (fits on same server)

**Estimated Resources:**
- Disk: ~50-100MB (for months of data)
- RAM: ~50-100MB additional
- CPU: Minimal impact

**Website:** https://umami.is  
**Demo:** https://app.umami.is/share/8rmHaheU/umami.is

---

## 📊 Analytics Option 4: Google Analytics 4 (GA4)

**Best for:** Maximum data, free, industry standard

### Pros:
- ✅ **100% FREE** (for < 10M hits/month)
- ✅ **Most powerful analytics** (unlimited reports)
- ✅ **Funnel analysis** (conversion tracking)
- ✅ **Demographic data** (age, gender, interests)
- ✅ **Industry standard** (everyone knows it)
- ✅ **Integration with Google Ads**
- ✅ **Machine learning insights**

### Cons:
- ❌ **Privacy concerns** (tracks users extensively)
- ❌ **Cookie banner required** (GDPR compliance)
- ❌ **Complex setup** (learning curve)
- ❌ **Heavy script** (~45KB compressed)
- ❌ **Data ownership** (Google owns your data)
- ❌ **Overkill** for small sites

### Implementation (15 minutes):
```html
<!-- Add to webapp/templates/webapp/base.html <head> -->
<!-- Google tag (gtag.js) -->
<script async src="https://www.googletagmanager.com/gtag/js?id=G-XXXXXXXXXX"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){dataLayer.push(arguments);}
  gtag('js', new Date());
  gtag('config', 'G-XXXXXXXXXX');
</script>
```

### Cookie Banner Required:
You'll need to add a cookie consent banner (GDPR/CCPA requirement).

**Website:** https://analytics.google.com

---

## 📊 Analytics Option 5: Simple Analytics

**Best for:** Privacy + simplicity + EU-based

### Pros:
- ✅ **Privacy-first** (GDPR compliant, no cookies)
- ✅ **Beautiful UI** (clean, modern)
- ✅ **Lightweight** (< 3KB script)
- ✅ **Event tracking**
- ✅ **Goals & funnels**
- ✅ **EU-owned company**
- ✅ **No sampling** (all data, always)

### Cons:
- ❌ **Paid** ($9/month for 10K pageviews)
- ❌ **More expensive** than Plausible at scale
- ❌ **Smaller ecosystem** than GA

### Pricing:
```
10K pageviews/month:   $9/month
100K pageviews/month:  $29/month
1M pageviews/month:    $79/month
```

**Website:** https://www.simpleanalytics.com  
**Demo:** https://simpleanalytics.com/simpleanalytics.com

---

## 🆚 Comparison Matrix

| Feature | Plausible | GoatCounter | Umami | GA4 | Simple Analytics |
|---------|-----------|-------------|-------|-----|------------------|
| **Price** | $9/mo | FREE | FREE/host | FREE | $9/mo |
| **Privacy** | ★★★★★ | ★★★★★ | ★★★★★ | ★☆☆☆☆ | ★★★★★ |
| **Ease of Use** | ★★★★★ | ★★★★☆ | ★★★☆☆ | ★★☆☆☆ | ★★★★★ |
| **Features** | ★★★★☆ | ★★★☆☆ | ★★★★☆ | ★★★★★ | ★★★★☆ |
| **Speed** | ★★★★★ | ★★★★★ | ★★★★★ | ★★★☆☆ | ★★★★★ |
| **Self-host** | ✅ | ✅ | ✅ | ❌ | ❌ |
| **Cookie Banner** | ❌ | ❌ | ❌ | ✅ | ❌ |
| **Real-time** | ✅ | ✅ | ✅ | ~1hr delay | ✅ |
| **Event Tracking** | ✅ | Limited | ✅ | ✅ Advanced | ✅ |

---

## 🎯 Recommendation

### Best Overall: **Plausible Analytics** ($9/month)

**Why:**
1. ✅ Perfect balance of **privacy** and **features**
2. ✅ **Beautiful dashboard** (you'll actually use it)
3. ✅ **No cookie banner** needed (saves dev time)
4. ✅ **< 1KB script** (doesn't slow your site)
5. ✅ **Privacy-respecting** (good for your brand)
6. ✅ **Simple setup** (5 minutes)
7. ✅ **Professional** (looks legitimate)

**For $9/month you get:**
- 10,000 pageviews/month (plenty for your traffic)
- Unlimited websites
- Real-time stats
- Event tracking
- Email reports

**Current traffic estimate:** 305 requests/day × 30 = ~9,150 pageviews/month  
→ Fits the $9/month tier perfectly!

### Best Free Option: **GoatCounter**

If you want to avoid the $9/month cost and don't need a fancy dashboard:
- ✅ Completely free for non-commercial
- ✅ Privacy-respecting
- ✅ Simple setup
- ❌ Basic UI

### Best for Privacy + Control: **Umami (self-hosted)**

If you want maximum control and don't mind 30 minutes of setup:
- ✅ Free forever
- ✅ Beautiful UI
- ✅ Your data stays on your server
- ✅ Fits on Lightsail ($5/month, no extra cost)

---

## 🚀 Implementation Guide: Plausible (Recommended)

### Step 1: Sign Up (2 minutes)
1. Go to https://plausible.io
2. Start 30-day free trial
3. Add site: `visa-bulletin.us`
4. Get your tracking code

### Step 2: Add Script (1 minute)
Edit `webapp/templates/webapp/base.html`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{% block title %}Visa Bulletin Dashboard{% endblock %}</title>
    <link rel="icon" type="image/svg+xml" href="{% static 'favicon.svg' %}">
    
    <!-- Plausible Analytics -->
    <script defer data-domain="visa-bulletin.us" src="https://plausible.io/js/script.js"></script>
    
    <!-- Bootstrap 5 CSS -->
    ...
```

### Step 3: Deploy (1 minute)
```bash
./scripts/deploy.sh ~/Downloads/VisaBulletin.pem
```

### Step 4: Verify (1 minute)
1. Visit https://visa-bulletin.us
2. Check Plausible dashboard
3. See real-time visitor (you!)

**Total Time: 5 minutes** ⏱️

---

## 📈 Advanced Tracking (Optional)

### Track Button Clicks
Add `plausible-event-name` attribute:

```html
<button class="btn btn-primary" plausible-event-name="Filter+Applied">
    Update
</button>
```

### Track Filter Usage
Add custom events in JavaScript:

```javascript
// Track visa class selections
document.getElementById('category').addEventListener('change', function() {
    plausible('Category Selected', {props: {category: this.value}})
});
```

### Track Chart Interactions
```javascript
// When user clicks a data point
plausible('Chart Point Clicked', {props: {visa_class: 'F4', country: 'china'}})
```

---

## 💾 Server-Side Analytics (Alternative)

If you don't want ANY third-party service:

### Option: Parse Nginx Logs with GoAccess

**What is GoAccess?**
- Open source log analyzer
- Generates beautiful HTML reports
- Runs on your server
- 100% private (no external service)

**Setup:**
```bash
# On AWS Lightsail
sudo apt install goaccess

# Generate report
sudo goaccess /var/log/nginx/access.log \
  -o /opt/visa_bulletin/webapp/static/analytics.html \
  --log-format=COMBINED \
  --real-time-html \
  --ws-url=wss://visa-bulletin.us

# Password protect the analytics page
# Add to Nginx config
```

**Pros:**
- ✅ 100% free
- ✅ 100% private
- ✅ Real-time dashboard
- ✅ Beautiful reports

**Cons:**
- ❌ Nginx logs only (no JS events)
- ❌ Can't track user interactions
- ❌ No demographic data
- ❌ Setup complexity

---

## 🔒 Privacy Considerations

### If Using Google Analytics:
- ⚠️ **Cookie banner required** (GDPR/CCPA)
- ⚠️ **Privacy policy update needed**
- ⚠️ **Data shared with Google**
- ⚠️ **May affect user trust**

### If Using Privacy-First Analytics:
- ✅ **No cookie banner** (Plausible, GoatCounter, Umami)
- ✅ **Minimal privacy policy update**
- ✅ **User data stays anonymous**
- ✅ **Good for brand/trust**

---

## 💰 Cost Analysis (Annual)

| Solution | Year 1 Cost | Notes |
|----------|-------------|-------|
| **Plausible** | $108/year | Clean, simple, recommended |
| **GoatCounter** | $0/year | Free, basic features |
| **Umami (self-host)** | $0/year | Uses existing server |
| **GA4** | $0/year | Free but privacy concerns |
| **Simple Analytics** | $108/year | Similar to Plausible |
| **GoAccess** | $0/year | Server logs only |

**Current Budget:** $5/month Lightsail + $12/year domain = $72/year  
**With Plausible:** $72 + $108 = **$180/year total** (~$15/month)

---

## 🎯 Quick Decision Guide

**Choose Plausible if:**
- You want simple, beautiful analytics
- Privacy matters to your brand
- $9/month is reasonable
- You want it "just working"

**Choose GoatCounter if:**
- You want free
- You don't need fancy UI
- Basic stats are enough

**Choose Umami if:**
- You want beautiful + free
- You're comfortable self-hosting
- You have 30 minutes for setup

**Choose GA4 if:**
- You need advanced features
- You're okay with privacy trade-offs
- You want industry-standard tool

**Choose GoAccess if:**
- You want 100% privacy
- Server logs are sufficient
- No external services allowed

---

## ✅ My Recommendation

**Start with Plausible's 30-day free trial.**

Why:
1. Test it risk-free for 30 days
2. See if $9/month is worth it for your use case
3. If not, switch to GoatCounter (free) after trial
4. No commitment, easy to change

**Next steps:**
1. Sign up: https://plausible.io
2. Add 1 line of code to base.html
3. Deploy with `./scripts/deploy.sh`
4. Check dashboard in 5 minutes

After 30 days, decide:
- **Keep Plausible?** Great analytics for $9/month
- **Switch to GoatCounter?** Free, good enough
- **Self-host Umami?** Best of both worlds

---

**Last Updated:** December 2025  
**Current Traffic:** ~300 requests/day from 114 unique IPs

