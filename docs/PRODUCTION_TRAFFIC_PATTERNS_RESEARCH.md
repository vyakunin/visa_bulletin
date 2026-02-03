# Production Traffic Patterns Research

**Source:** Nginx access logs on prod_2Gb_vm (44.209.204.255)  
**Log path:** `/var/log/nginx/access.log`  
**Analysis date:** 2026-02-03  
**Data window:** Current log file (~131.8k requests since midnight UTC) + previous day (~23k requests)

---

## 1. Volume Summary

| Metric | Today (since 00:00 UTC) | Yesterday (access.log.1) |
|--------|--------------------------|---------------------------|
| **Total requests** | ~131,800 | ~23,100 |
| **Unique IPs** | 1,141 | 1,022 |
| **200 responses** | 128,939 (97.8%) | 18,266 (79.2%) |

Today’s volume is ~5.7× yesterday’s; the current log file covers a full day so far, while `.1` is a partial day after rotation.

---

## 2. Path / Section Distribution (real users only)

*Excludes known bots: GPTBot, Googlebot, GoogleOther, bingbot, UptimeRobot, ChatGPT-User, AhrefsBot, got.*

| Section | Requests | % of human | Notes |
|---------|----------|------------|--------|
| **Employment-based** (`/employment-based/...`) | 1,053 | 17.9% | India, All, etc. |
| **Homepage** (`/`) | 862 | 14.6% | |
| **Salary search** (`/salaries/`) | 648 | 11.0% | Filtered salary results |
| **Employer pages** (`/employer/<slug>/`) | 337 | 5.7% | |
| **API job-title autocomplete** | 70 | 1.2% | |
| **API company autocomplete** | 48 | 0.8% | |
| **Job title pages** (`/job-title/<slug>/`) | 35 | 0.6% | |
| **Employers directory** | 35 | 0.6% | |
| **Job titles directory** | 27 | 0.5% | |
| *Other (probes, 404s, etc.)* | ~2,780 | ~47% | Non-app paths, scanners |

**Human total (app + other):** ~5,895 requests in sample day.

**Takeaway (real users):** Employment-based and homepage dominate; then salary search and employer profiles. Job-title profile traffic in this window is mostly bots; human share of job-title/employer pages is small relative to employment-based and homepage.

**GoatCounter vs Nginx:** Nginx counts every HTTP request (including HEAD, API calls, bots we didn’t filter, and clients that block JS). GoatCounter only counts page views where the browser loads the script and sends a hit (JS enabled, script not blocked). So GoatCounter will usually show fewer “page views” than Nginx “human” requests. If GoatCounter shows much less than expected (e.g. almost no employment-based or homepage), check that **ANALYTICS_SCRIPT** is set in production: deployment Docker Compose (blue/green) now sets it explicitly; if you run without that, add it to `.env` on the server or set it in the compose `environment` section. Verify with: `curl -s https://visa-bulletin.us/ | grep -o goatcounter` (should output `goatcounter`). *(Verified 2026-02-03: script present in production HTML.)*

---

## 3. Bot vs Human Traffic

**Identified bots (by User-Agent substring):**

| Bot | Requests | % of total |
|-----|----------|------------|
| **GPTBot** (OpenAI) | 124,172 | **94.2%** |
| GoogleOther | 930 | 0.7% |
| bingbot | 364 | 0.3% |
| UptimeRobot | 241 | 0.2% |
| ChatGPT-User | 219 | 0.2% |
| AhrefsBot | 92 | 0.1% |
| Googlebot | 91 | 0.1% |
| got (HTTP client) | 3 | |

**Takeaway:** GPTBot dominates. The vast majority of requests in this window are crawler traffic, not end users. Real user traffic is on the order of a few thousand requests per day (roughly total minus GPTBot/ChatGPT-User).

---

## 4. HTTP Status Codes

**Today:**

| Code | Count | % | Meaning |
|------|-------|---|---------|
| 200 | 128,939 | 97.8 | OK |
| 404 | 2,294 | 1.7 | Not found |
| 301 | 346 | 0.3 | Redirect |
| 499 | 79 | 0.1 | Client closed before response |
| 502 | 71 | 0.1 | Bad gateway |
| 400 | 26 | | Bad request |
| 166 | 20 | | (likely malformed log) |
| 504 | 1 | | Gateway timeout |

**Yesterday:** Higher share of 404 (3,785), 499 (508), 504 (131), and 500 (4), suggesting more errors or timeouts on that day.

---

## 5. Referrer / Traffic Source

| Referrer domain | Requests |
|-----------------|----------|
| visa-bulletin.us (internal) | 124,133 |
| www.visa-bulletin.us (internal) | 1,874 |
| www.google.com | 318 |
| www.bing.com | 21 |
| www.reddit.com, linkedin.com | 2 each |
| yandex, facebook, yahoo, duckduckgo, chatgpt.com | 1 each |

Most requests have an internal referrer (same site), consistent with bots following in-site links. Organic search referrers are relatively small in this sample.

---

## 6. Hourly Distribution (UTC, 200s only)

Peak hours (today): 01 and 04 UTC (~7k each). Lowest: 08 UTC (~4.4k), then 12–14 UTC (~5–5.2k). Distribution is fairly flat (roughly 4.4k–7k per hour), which fits bot crawling more than a strong human peak.

---

## 7. Large Responses (bandwidth / slow risk)

- **Sitemap:** `/sitemap.xml` ~1.5–1.56 MB per request.
- **Homepage:** `/` often 260–330 KB (e.g. cache miss or first hit).
- **Employment-based India (with params):** 298–436 KB (e.g. filing/date filters).
- **Job title / employer profiles:** typically 10–20 KB.

Large payloads are sitemap, homepage, and employment-based India pages. These are the main candidates for caching and size/query optimization.

---

## 8. Security / Noise

- Probes to `/wp-admin`, `/.git`, `/api/.env`, `/admin`, `/actuator`, etc. (many single-digit counts).
- **We do not have any handlers for these paths.** The app only serves routes defined in `django_config/urls.py` and `webapp/urls.py` (dashboard, salaries, employer/job-title profiles, employment-based/family-sponsored, autocomplete APIs, static pages). All probe paths return 404 from Django; there are no backdoor or admin endpoints exposed.
- 404s (2,294 today) include both invalid slugs and probe paths.
- No evidence of successful exploitation in the analyzed lines; probes are expected for a public site.

---

## 9. Recommendations

1. **Response-time in Nginx logs**  
   Implemented: `main_timed` format with `$request_time`; see [Response time logging](#response-time-logging) below.

2. **Bot policy**  
   We want to allow GPTBot; to reduce load, throttle it (e.g. to 0.5 qps). See [§ Throttling GPTBot to 0.5 qps](#throttling-gptbot-to-05-qps) below.

3. **Cache and optimize large responses**  
   - Sitemap: ensure it’s cached and/or generated efficiently.  
   - Homepage and employment-based India: ensure cache headers and cache hit rates are good.

4. **Monitor 4xx/5xx**  
   Track 404, 499, 502, 504 over time; yesterday’s higher error counts are worth watching.

5. **Optional: separate bot vs user metrics**  
   If you add a small log post-processor or metrics (e.g. by User-Agent), you can report “human” vs “crawler” traffic separately.

---

## 10. How to Re-run / Update This

```bash
# On production
ssh prod_2Gb_vm "sudo wc -l /var/log/nginx/access.log"
# Human-only path distribution (exclude known bots)
ssh prod_2Gb_vm "sudo grep -v -E 'GPTBot|Googlebot|GoogleOther|bingbot|UptimeRobot|ChatGPT-User|AhrefsBot|got \(https' /var/log/nginx/access.log | awk '{print \$7}' | sed 's/?.*//' | grep -E '^/(job-title|employer|salaries|employment-based|employers|job-titles|api|$)' | sed 's#^/job-title/[^/]*#/job-title/#' | sed 's#^/employer/[^/]*#/employer/#' | sed 's#^/salaries.*#/salaries/#' | sed 's#^/employment-based/[^/]*.*#/employment-based/#' | sort | uniq -c | sort -rn"
ssh prod_2Gb_vm "sudo grep -oE 'GPTBot|Googlebot|ChatGPT-User|AhrefsBot|UptimeRobot' /var/log/nginx/access.log | sort | uniq -c | sort -rn"
ssh prod_2Gb_vm "sudo awk '{print \$9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn"
```

Nginx default log format: `$remote_addr - $remote_user [$time_local] "$request" $status $body_bytes_sent "$http_referer" "$http_user_agent"`. With response-time logging, the format adds `$request_time` after `$body_bytes_sent`.

---

## Response time logging

Response time is added to access logs so slow requests can be analyzed.

**Files:** `deployment/nginx/visa-bulletin-log-format.conf` defines log format `main_timed` with `$request_time`. `deployment/nginx/visa-bulletin-nginx.conf` uses `access_log ... main_timed`.

**New instances:** `scripts/setup_new_instance.sh` copies the log-format file to `/etc/nginx/conf.d/`.

**Existing production (one-time):** Copy the log-format and GPTBot rate-limit files into `http` context, update the site config to use `main_timed` and the new locations (with limit_req), then reload:

```bash
sudo cp /opt/visa_bulletin/deployment/nginx/visa-bulletin-log-format.conf /etc/nginx/conf.d/
sudo cp /opt/visa_bulletin/deployment/nginx/gptbot-rate-limit.conf /etc/nginx/conf.d/
sudo cp /opt/visa_bulletin/deployment/nginx/visa-bulletin-nginx.conf /etc/nginx/sites-available/visa-bulletin
sudo cp /opt/visa_bulletin/deployment/nginx/visa-bulletin-locations.conf /opt/visa_bulletin/deployment/nginx/
sudo nginx -t && sudo systemctl reload nginx
```

**Parse:** The timed log line has request time as the field after `$body_bytes_sent` (before referer). Example:  
`74.7.243.242 - - [03/Feb/2026:20:11:30 +0000] "GET /employer/foo/ HTTP/1.1" 200 10144 0.234 "https://..." "Mozilla/..."`

---

## Throttling GPTBot to 0.5 qps

**Goal:** Allow GPTBot but cap at 0.5 requests per second per IP (~1 request every 2 seconds per IP) to reduce load while staying crawlable.

**Effort: low.** Implemented with Nginx:

- **`deployment/nginx/gptbot-rate-limit.conf`:** `map` sets zone key to `$binary_remote_addr` when User-Agent contains `GPTBot`, else empty. Nginx docs: *"Requests with an empty key value are not accounted."* So only GPTBot traffic is limited. `limit_req_zone $gptbot_key zone=gptbot:10m rate=1r/2s` → 0.5 qps per IP for GPTBot.
- **`deployment/nginx/visa-bulletin-locations.conf`:** `location /` has `limit_req zone=gptbot burst=1 nodelay; limit_req_status 429;`. When over limit, GPTBot gets 429.

**New instances:** `scripts/setup_new_instance.sh` copies `gptbot-rate-limit.conf` to `/etc/nginx/conf.d/`.

**Existing production:** Same one-time steps as [Response time logging](#response-time-logging) (copy both conf.d files and updated site/locations).

**Effect:** GPTBot IPs are limited to 0.5 qps each; other traffic is unchanged. Throttled requests receive 429.
