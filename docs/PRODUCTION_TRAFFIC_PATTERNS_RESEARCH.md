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
   We want to allow bots; to reduce load, throttle them to 0.1 qps per IP. See [§ Throttling bots to 0.1 qps](#throttling-bots-to-01-qps) below.

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

**Existing production (one-time):** Copy the log-format and bot rate-limit files into `http` context, update the site config to use `main_timed` and the new locations (with limit_req), then reload:

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

## Throttling bots to 0.1 qps

**Goal:** Allow bots but cap at 0.1 requests per second per IP (6 req/min) to reduce load while staying crawlable.

**Effort: low.** Implemented with Nginx:

- **`deployment/nginx/gptbot-rate-limit.conf`:** `map` sets zone key to `$binary_remote_addr` when User-Agent matches a known bot (GPTBot, Googlebot, Bingbot, DuckDuckBot, Slurp, Baiduspider, YandexBot, facebookexternalhit), else empty. Nginx docs: *"Requests with an empty key value are not accounted."* So only bot traffic is limited. `limit_req_zone $gptbot_key zone=gptbot:10m rate=6r/m` → 0.1 qps per IP for bots.
- **`deployment/nginx/visa-bulletin-locations.conf`:** `location /` has `limit_req zone=gptbot burst=1 nodelay; limit_req_status 429;`. When over limit, bots get 429.

**New instances:** `scripts/setup_new_instance.sh` copies `gptbot-rate-limit.conf` to `/etc/nginx/conf.d/`.

**Existing production:** Same one-time steps as [Response time logging](#response-time-logging) (copy both conf.d files and updated site/locations).

**Effect:** Bot IPs are limited to 0.1 qps each; other traffic is unchanged. Throttled requests receive 429.

---

## 11. 5xx and worker overload

**Can we see in logs if workers are often overwhelmed leading to 5xx?**

**What we have today (prod):**

- **Nginx access log** (`/var/log/nginx/access.log`): status, path, body_bytes_sent. On current prod the log format does **not** include `$request_time` (main_timed is in repo but may not be active on the server). So we cannot see “502 after 60s” (timeout) vs “502 immediately” (connection reset).
- **Gunicorn access log**: The image uses `--access-logformat '...(r)s %(s)s %(b)s %(L)s'` (includes request time `%(L)s`), but access lines do **not** appear in `docker logs visa_bulletin_web` (only lifecycle and Django logs). So we cannot count slow requests (e.g. L>30s) or correlate 5xx with high L from current docker logs.

**What we can do: correlate 502 with worker restarts**

Gunicorn runs with `--max-requests 1000 --max-requests-jitter 100` and 3 workers by default (see §12). When a worker hits that limit it logs “Autorestarting worker after current request” then exits; the master starts a new worker (~1–2s gap). Requests that hit during that window can get 502 (connection reset or no worker ready). So 502s often cluster in the same minute as a “Booting worker” event.

**Commands to check “502s near restarts” on prod:**

```bash
# 502 timestamps (UTC) from nginx
ssh prod_2Gb_vm "sudo awk '/ 502 /{for(i=1;i<=NF;i++) if(\$i ~ /^\[/) {gsub(/\[|\]/,\"\",\$i); split(\$i,a,\":\"); print a[1], a[2]\":\"a[3]\":\"a[4]; break}}' /var/log/nginx/access.log"

# Worker restart times (UTC) from gunicorn
ssh prod_2Gb_vm "docker logs visa_bulletin_web 2>&1 | grep 'Booting worker' | grep '+0000' | sed -nE 's/.*\[([0-9]{4}-[0-9]{2}-[0-9]{2}) ([0-9]{2}):([0-9]{2}):([0-9]{2}) \+0000\].*/\1 \2:\3:\4/p'"
```

Compare the two lists: 502s that fall in the same minute (or within ~90s before) a “Booting worker” time are likely from the n-1-workers restart window rather than from a backlog of slow requests.

**Example (2026-03-10):** 40 502s in the nginx log; many align exactly or within 1s of a Booting event (e.g. 502 at 21:01:51, Booting at 21:01:52). That supports “502 = restart window” rather than “workers chronically overloaded.”

**To see “workers overwhelmed” in the future:**

Timing is already configured in the repo; on prod it may just not be deployed yet.

1. **Nginx:** `main_timed` (with `$request_time`) is defined in `deployment/nginx/visa-bulletin-log-format.conf` and used by `visa-bulletin-locations.conf` / `visa-bulletin-nginx.conf`. To enable on prod (one-time): copy the log-format file into `http` context and reload nginx:
   ```bash
   sudo cp /opt/visa_bulletin/deployment/nginx/visa-bulletin-log-format.conf /etc/nginx/conf.d/
   sudo nginx -t && sudo systemctl reload nginx
   ```
   Then 502s with request_time ≈ 60s indicate upstream timeout (nginx gave up); 502s with request_time &lt; 1s indicate connection reset (restart window).

2. **Gunicorn:** The image already uses `--access-logformat` with `%(L)s` (request time in seconds) and logs to stdout. If access lines don’t appear in `docker logs`, the container may be capturing only stderr; otherwise they should be there. No config change needed in repo. You can then count requests with L&gt;30s or L&gt;55s and correlate with 502s.

---

## 12. Load and safety for more workers / higher max-requests

**Snapshot (2026-03-10):** Host 1.9GB RAM, ~750Mi used, ~853Mi available; load 0.05–0.54. Web container **128.9MiB / 512MiB (25%)**, CPU 14% (momentary). Nginx ~55k requests in current log (order of ~2–3 req/s average).

**Verdict:**

- **Increase max-requests:** Safe. Current 500+ jitter causes a worker restart every ~10 min and 502s cluster at those times. Raising to **1000** (or 2000) halves (or quarters) restart frequency and reduces 502 windows. No extra memory; workers still recycle, just less often.
- **Add one more worker (2 → 3):** Safe at current usage. Container has ~384MiB headroom; each worker is on the order of ~65MiB, so a third worker fits. After changing, monitor `docker stats` and host `free -h`; if the container approaches 450MiB or the host gets tight, revert to 2 workers or raise container/host memory.

**Applied in repo:** `deployment/docker-compose.yml` uses `WEB_CONCURRENCY=${WEB_CONCURRENCY:-3}` and `--max-requests 1000` (jitter 100). Override with `WEB_CONCURRENCY=2` in `.env` if you need to revert.
