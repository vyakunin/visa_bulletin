# Cloudflare in front of visa-bulletin.us

> **⚠️ HISTORICAL — describes the retired AWS-Lightsail + Cloudflare-proxy setup.**
> Production migrated off Lightsail on 2026-05-08 and now sits behind a **Cloudflare
> Tunnel** (the `vb_cloudflared` connector in the prod Docker Compose stack). There
> is **no public origin IP** anymore, so the origin-firewall lock-down below
> (Step 7 — Lightsail firewall, `aws lightsail` CLI, IP allowlisting) **no longer applies** —
> the tunnel makes the origin unreachable except through Cloudflare by construction.
> The generic CF concepts here (edge cache, real-client-IP headers, WAF) still
> apply, but the Lightsail/AWS-CLI-specific mechanics are dead. For the current
> topology see `.claude/rules/deployment.md`.

Goal: put the Cloudflare free tier in front of the Lightsail origin to offload
bot traffic, absorb spikes, and serve cached HTML/static assets from the edge.

This is **additive** to the existing nginx rate-limiting stack
(`deployment/nginx/gptbot-rate-limit.conf`, `default-server.conf`, and the
adaptive switcher in `deployment/scripts/nginx_bot_adaptive.sh`). Cloudflare
handles the bulk traffic; nginx stays as defense-in-depth for anything that
reaches the origin (same-AZ attacks, origin-IP leaks, CF-authenticated bots).

---

## Why (short version)

| Problem today                                                        | What Cloudflare adds                                                      |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| Every bot request hits the box — TLS + parsing burns burst credits.  | Bots get challenged at edge; origin sees a tiny fraction.                 |
| Rate limits key on `User-Agent` — spoofable.                         | Bot Fight Mode uses TLS/JA4 fingerprint + behavioural signals.            |
| Adaptive strict mode fires *after* burst drops below 50%.            | Edge absorbs spikes before they reach the instance.                       |
| Bulletin/prediction/ranking HTML is cached in Django only.           | Edge cache across ~300 POPs turns repeat hits into zero origin load.     |
| No geographic shaping.                                               | Cheap country-based challenges / blocks in WAF.                           |
| No L7 DDoS protection on a 2 GB instance.                            | Free L3/L4/L7 DDoS mitigation.                                            |

---

## Prereqs

- Registrar access for `visa-bulletin.us` (to change nameservers).
- Free Cloudflare account.
- Current Let's Encrypt cert on origin is fine to keep during migration —
  Cloudflare `Full (strict)` mode validates against it.
- Access to the Lightsail console (for networking and firewall rules later).

---

## Step 1 — Inventory existing DNS

Before changing anything, dump every record so nothing is lost in the import.

```bash
# Authoritative records at the current provider
dig +short NS visa-bulletin.us

# Common record types to audit manually in the registrar UI:
#   A, AAAA, CNAME, MX, TXT (SPF, DKIM, DMARC, site-verification), CAA
dig visa-bulletin.us     A    +short
dig visa-bulletin.us     AAAA +short
dig www.visa-bulletin.us CNAME +short
dig visa-bulletin.us     MX   +short
dig visa-bulletin.us     TXT  +short
dig visa-bulletin.us     CAA  +short
```

Save the output somewhere — Cloudflare's auto-import catches most but not all
records (CAA and some TXT rows are the usual miss).

---

## Step 2 — Add site to Cloudflare (Free plan)

1. Dashboard → **Add a site** → `visa-bulletin.us` → Free plan.
2. Cloudflare scans DNS. Review imported records against Step 1 inventory.
   Add anything missing manually.
3. Decide proxy status per record:
   - **Proxied (orange cloud):** `@` (apex), `www`, anything serving web traffic.
   - **DNS-only (grey cloud):** `MX` records, any `_dmarc` / `_acme-challenge`
     TXT, and — during migration — the origin's direct A record if you keep
     one under a subdomain (e.g. `origin.visa-bulletin.us`) to bypass CF for
     debugging.
4. Copy the two Cloudflare nameservers. At the registrar, replace the current
   NS records with Cloudflare's. Propagation: usually minutes, up to 24 h.

Do **not** take the origin down during this step. Cloudflare starts proxying
the moment DNS resolves; the origin keeps serving as before.

---

## Step 3 — SSL/TLS mode

SSL/TLS → Overview → **Full (strict)**.

- `Flexible` is insecure (CF ↔ origin is plaintext).
- `Full` accepts any cert.
- `Full (strict)` requires a valid cert at origin — Let's Encrypt qualifies.

Edge certificates: leave "Always Use HTTPS" **ON** and "Automatic HTTPS
Rewrites" ON. HSTS: leave OFF until you're confident the site will stay on
HTTPS for >6 months (HSTS preload is hard to reverse).

### Optional but recommended: Cloudflare Origin CA cert

This lets you stop exposing the LE cert to the world and eventually lock the
origin to only accept CF-issued client certs.

1. SSL/TLS → Origin Server → **Create Certificate** (15 year, ECC).
2. Save the cert + key. Install at origin (e.g. `/etc/ssl/cloudflare/`).
3. Swap nginx `ssl_certificate` / `ssl_certificate_key` to the CF-issued pair.
4. Reload nginx; verify `curl --resolve visa-bulletin.us:443:<origin-ip> https://visa-bulletin.us/ -vI` still works via CF edge.
5. Later: enable **Authenticated Origin Pulls** (CF sends a client cert; nginx
   requires it). Blocks origin-IP scrapers completely.

---

## Step 4 — Restore real client IP at the origin

**Critical** — otherwise every request looks like it comes from a CF IP, which
breaks nginx rate limiting, application logs, and the subnet-level bot limit
key (`$remote_addr_slash16`).

Add to `deployment/nginx/visa-bulletin-nginx.conf` (inside `http {}` or at
file top-level — then propagate to `/etc/nginx/conf.d/`):

```nginx
# Cloudflare edge networks — trust X-Forwarded-For only from these.
# Pull latest from https://www.cloudflare.com/ips/ and refresh quarterly.
set_real_ip_from 173.245.48.0/20;
set_real_ip_from 103.21.244.0/22;
set_real_ip_from 103.22.200.0/22;
set_real_ip_from 103.31.4.0/22;
set_real_ip_from 141.101.64.0/18;
set_real_ip_from 108.162.192.0/18;
set_real_ip_from 190.93.240.0/20;
set_real_ip_from 188.114.96.0/20;
set_real_ip_from 197.234.240.0/22;
set_real_ip_from 198.41.128.0/17;
set_real_ip_from 162.158.0.0/15;
set_real_ip_from 104.16.0.0/13;
set_real_ip_from 104.24.0.0/14;
set_real_ip_from 172.64.0.0/13;
set_real_ip_from 131.0.72.0/22;
set_real_ip_from 2400:cb00::/32;
set_real_ip_from 2606:4700::/32;
set_real_ip_from 2803:f800::/32;
set_real_ip_from 2405:b500::/32;
set_real_ip_from 2405:8100::/32;
set_real_ip_from 2a06:98c0::/29;
set_real_ip_from 2c0f:f248::/32;

real_ip_header CF-Connecting-IP;
real_ip_recursive on;
```

Verify after reload:

```bash
tail -f /var/log/nginx/access.log
# Real client IPs should reappear; not 104.16.x.x etc.
```

**Refresh source:** keep a script to pull `https://www.cloudflare.com/ips-v4`
and `.../ips-v6`, regenerate the block, `nginx -t`, reload. Quarterly is fine.

---

## Step 5 — Cache rules

Free plan: use **Cache Rules** (Rules → Cache Rules). Caching edge-side is
where most of the origin-CPU win comes from.

### 5.1 Cache HTML for bulletin / predictions / rankings

The Django view-level cache already produces cacheable HTML. Just let CF keep
it at the edge.

Rule — "Cache bulletin + predictions + rankings HTML":
- **When:**
  `(http.request.uri.path in {"/"} or starts_with(http.request.uri.path, "/bulletin/") or starts_with(http.request.uri.path, "/predictions/") or starts_with(http.request.uri.path, "/rankings/") or starts_with(http.request.uri.path, "/employers/"))`
- **Then:**
  - Cache eligibility: **Eligible for cache**
  - Edge TTL: **Override origin — 1 hour** (matches Django's 3 h page cache;
    pick whichever is tighter).
  - Browser TTL: **1 hour**.
  - Cache key: default (host + path + query) — but **Ignore query string** if
    the page doesn't actually vary on query (test first).

### 5.2 Never cache authenticated / dynamic endpoints

Rule — "Bypass cache for admin + API":
- **When:**
  `(starts_with(http.request.uri.path, "/admin/") or starts_with(http.request.uri.path, "/api/") or http.cookie contains "sessionid")`
- **Then:** Cache eligibility: **Bypass cache**.

Place **above** rule 5.1 (rules evaluate top-to-bottom).

### 5.3 Long-cache static assets

CF already caches `.css`/`.js`/`.woff2` aggressively by default, but make it
explicit:

- **When:** `http.request.uri.path matches "\.(css|js|woff2?|png|jpg|jpeg|svg|ico)$"`
- **Then:** Edge TTL override — **30 days**, Browser TTL — **1 day**.

### 5.4 Verify cache behaviour

```bash
curl -sI https://visa-bulletin.us/ | grep -i 'cf-cache\|cache-control'
# First hit: cf-cache-status: MISS    (then DYNAMIC until origin responds)
# Second hit: cf-cache-status: HIT    ← this is the win
```

If `cf-cache-status: BYPASS`: a cookie or `Cache-Control: private` from origin
is blocking caching. Check the Django response headers.

---

## Step 6 — Bot & WAF settings

Security → **Bots**:
- **Bot Fight Mode:** ON (free).
  - Challenges obviously-automated traffic with JS/Managed Challenge.
  - Logs: Security → Events, filter by `Bot Score`.
- (Paid: Super Bot Fight Mode adds per-category controls — out of scope for free plan.)

Security → **WAF → Managed Rules**:
- **Cloudflare Managed Ruleset:** ON (free tier gets a reduced set).

Security → **WAF → Custom Rules** (free tier: 5 rules):

1. **Block known-bad bot UAs that don't respect rate limits** (belt-and-braces
   with the nginx blacklist in `gptbot-rate-limit.conf`):
   ```
   (http.user_agent contains "SemrushBot") or
   (http.user_agent contains "YandexBot") or
   (http.user_agent contains "Amazonbot") or
   (http.user_agent contains "SERankingBacklinksBot")
   ```
   Action: **Block**.

2. **Challenge high-risk countries** (only if analytics show abuse — don't do
   this blind; it hurts legitimate users with VPNs):
   ```
   (ip.geoip.country in {"CN" "RU" "KP"}) and
   not (http.request.uri.path starts_with "/static/")
   ```
   Action: **Managed Challenge**.

3. **Rate-limit /api/ by IP** (free tier includes basic rate limiting):
   - Rules → Rate limiting rules.
   - Match: `starts_with(http.request.uri.path, "/api/")`
   - Rate: 60 req / 1 min per IP.
   - Action: Block for 10 min.

Keep the nginx rate limits in place — they cover the origin-IP-direct path
(Step 7) and anything that authenticates past CF.

---

## Step 7 — Lock origin to Cloudflare (after CF is confirmed working)

> **⚠️ RETIRED — no longer applicable.** This entire step assumed a public origin
> IP (the Lightsail VM) that bots could reach directly. Prod now runs behind a
> Cloudflare Tunnel (`vb_cloudflared`), so the origin has no public IP to firewall
> and there is nothing to "lock down" — the tunnel is the lock. The `aws lightsail`
> CLI below targets a VM that no longer exists. Kept for historical reference only.

Until this step, bots can still reach the origin by IP, bypassing CF entirely.
The existing `default-server.conf` exists precisely for that scenario; now we
close it.

**Do this AFTER verifying CF → origin is healthy for ≥48 h.**

### Option A — Lightsail firewall (simplest) — RETIRED (no public origin under the tunnel)

Lightsail → instance → Networking → Firewall:

1. Remove `Allow TCP 80 from 0.0.0.0/0`.
2. Remove `Allow TCP 443 from 0.0.0.0/0`.
3. Add entries allowing TCP 80 and TCP 443 only from Cloudflare IPv4 ranges
   (same list as Step 4). Lightsail doesn't currently support IPv6 rules per
   CIDR, so either leave IPv6 open or disable IPv6 on the instance.
4. Keep SSH (port 22) restricted to your IP as today.

Caveat: Lightsail UI only allows one rule per port per source, and ranges are
tedious to enter. Script it via the AWS CLI:

```bash
aws lightsail put-instance-public-ports \
  --instance-name VisaBulletin2GB \
  --region us-east-1 \
  --port-infos file://lightsail-cf-only-ports.json
```

Where `lightsail-cf-only-ports.json` is a list of `{fromPort, toPort, protocol, cidrs}` objects — one port entry per CF CIDR group.

> **Gotcha:** `put-instance-public-ports` **replaces** every rule on the instance
> — it is not a merge. You must include port 22 (SSH) in the same payload or
> you will lock yourself out. `cloudflare_setup.py lockdown` always re-declares
> `22/tcp 0.0.0.0/0` before the CF ranges.

### Option B — Authenticated Origin Pulls

More robust than IP allowlisting (CF's IP ranges change; client certs don't):

1. SSL/TLS → Origin Server → **Authenticated Origin Pulls** → enable.
2. Install `origin-pull-ca.pem` on origin (from Cloudflare docs).
3. In nginx HTTPS server block:
   ```nginx
   ssl_client_certificate /etc/ssl/cloudflare/origin-pull-ca.pem;
   ssl_verify_client on;
   ```
4. Keep the Lightsail firewall open but now any non-CF request fails TLS.

---

## Step 8 — Adjust nginx for the new reality

With CF absorbing bulk traffic, some existing knobs can be loosened — but
don't remove them, since the origin-direct and CF-authenticated paths still
need protection.

- **Rate limits (`gptbot-rate-limit.conf`):** keep as-is. These now only fire
  for requests that CF lets through *or* requests hitting the origin IP
  directly. Numbers (7 r/m per-bot, 15 r/m shared) are fine.
- **Adaptive switcher (`nginx_bot_adaptive.sh`):** keep running. If CF does
  its job, you'll rarely see burst drop below 75%. If you *do*, something is
  chewing through CF — worth investigating, not silencing.
- **Default-server (`default-server.conf`):** once Step 7 is in place,
  direct-IP traffic can't reach port 80/443 anymore. The rate limits there
  become dead code but harmless. Leave in place — cheap belt-and-braces in
  case firewall rules get reverted.
- **Page cache in Django:** can be shortened once CF is caching. Be careful:
  Django's cache avoids re-rendering; CF's cache avoids re-requesting. Both
  are worth keeping.

---

## Step 9 — Monitoring & verification

After the cutover:

```bash
# Origin request rate — should drop noticeably for cached paths.
tail -n 1000 /var/log/nginx/access.log | awk '{print $7}' | sort | uniq -c | sort -rn | head

# Burst capacity — should trend upward.
aws lightsail get-instance-metric-data \
  --instance-name VisaBulletin2GB --region us-east-1 \
  --metric-name BurstCapacityPercentage \
  --period 300 --start-time $(date -u -d '1 day ago' +%s) --end-time $(date -u +%s) \
  --unit Percent --statistics Average --output table

# CF analytics
# Dashboard → Analytics → Traffic: requests, cached %, bandwidth saved.
# Dashboard → Security → Events: challenged / blocked requests.
```

Sanity checks:

- `cf-cache-status: HIT` on repeat requests to `/`, `/bulletin/`, etc.
- Access logs show real client IPs (Step 4 verification).
- `/admin/` still requires login, never cached.
- Predictions page gets fresh data when a new bulletin is published (bust CF
  cache manually: Caching → Configuration → **Purge Everything** after a
  bulletin release, or purge by URL).

---

## Rollback

Fast revert path if CF breaks something:

1. **DNS-only (grey cloud) toggle** — easiest. Dashboard → DNS → click orange
   cloud to grey on affected records. Traffic bypasses CF; TLS terminates at
   origin with LE cert as before. Takes effect in seconds (CF's DNS TTL is 5 min).
2. **Pause Cloudflare on Site** — Overview → **Pause Cloudflare on Site**.
   CF becomes a dumb proxy for a few hours. Useful for debugging without
   touching DNS.
3. **Nuclear:** at the registrar, swap NS records back to the previous DNS
   host. Propagation 5 min – 24 h depending on old TTL.

---

## Known gotchas

- **`$host` vs `$http_host` in nginx:** `default-server.conf` uses
  `$http_host` for `proxy_set_header Host` — keep that. CF sets `Host` to the
  original requested hostname, which is what Django expects for
  `ALLOWED_HOSTS`.
- **DEBUG + CF cache:** we hard-fail on prod hostname with DEBUG=True (commit
  72f7427). If you ever turn DEBUG on temporarily, purge CF cache first or
  edge will serve the Django debug page to everyone.
- **Bulletin release day (15th):** CF cache at `edge TTL = 1h` may serve
  stale predictions for up to an hour after publish. Either:
  - Purge CF after `publish_predictions.py` runs, or
  - Tighten edge TTL to 15 min for `/predictions/*`, or
  - Add a cache-busting query param (`?v=<publish-timestamp>`) from the loader.
- **CAA record:** if you had one restricting to Let's Encrypt and later adopt
  CF Origin CA, add `cloudflare.com` to CAA or drop the record. Otherwise
  Origin CA issuance can be blocked.
- **Cloudflare IP list drift:** set a quarterly reminder to refresh the IP
  ranges in `set_real_ip_from` and (if using Option A in Step 7) the Lightsail
  firewall.

---

## Appendix — Granting the agent access to CF analytics

Our stored API token (`~/tokens/cloudflare_api_token`) has
`Zone Read`, `Cache Settings Write`, `Zone WAF Write`, `Zone Settings Write`,
`Zone Write`, `DNS Read/Write`, `SSL and Certificates Write`, plus account-level
`Registrar Domains Admin` and DNS View permissions.

**What it does NOT have:** `Analytics` (account-scoped, group id
`9ac5632ae4f449938fc2ed64a20af22c`). Without it, every analytics call fails
with 10000/`Authentication error` or the GraphQL message
`Actor does not have permission 'com.cloudflare.api.account.zone.analytics.read'`.

### Why the agent can't add it itself

The token is authorised to edit itself (it has `API Tokens Write`), and did so
to add zone-scoped permissions during the original bootstrap. But CF refuses
to let it attach the `Analytics` group via `PUT /accounts/{id}/tokens/{id}`:

```
400 { "code": 1001, "message": "Permission group \"9ac5632ae4f449938fc2ed64a20af22c\" not found" }
```

This is a CF-enforced rule: a handful of sensitive permission groups (Analytics,
Logs, Billing, etc.) cannot be granted through token self-edit. Same-token
privilege escalation is blocked by design — makes sense, otherwise any
compromised write token could grant itself telemetry/log read.

### What to do (no new token needed)

**You do not need to rotate the token or give the agent a new value.** Just add
the permission to the existing token via the dashboard. **You need TWO rows —
this is the trap:** Account → Analytics : Read grants account-wide analytics
(Workers, Billing, CASB, etc.) but does NOT grant zone HTTP analytics. Zone
HTTP analytics is a separate row under the **Zone** scope.

1. Cloudflare dashboard → profile icon (top right) → **API Tokens**.
2. Find the token (most recent; the name is auto-generated, e.g.
   `misty-salad-9f5f`, issued 2026-04-21).
3. Click **Edit**.
4. Under **Permissions**, add both rows (order doesn't matter):
   - Row A (optional but harmless):
     - Scope: **Account**
     - Resource: the one account we own
     - Permission: **Analytics — Read**
   - Row B (**this is the one that actually enables zone HTTP analytics**):
     - Scope: **Zone**
     - Resource: `visa-bulletin.us` (or "All zones from an account")
     - Permission: **Analytics — Read**
5. Save. The token string itself does not change; the agent keeps using
   `~/tokens/cloudflare_api_token` as-is.

The error message `Actor does not have permission 'com.cloudflare.api.account.zone.analytics.read' for zone <id>`
means Row B is missing — CF is asking for zone-scoped analytics read. The word
"account" in the permission identifier is misleading: it's just part of CF's
internal naming convention (everything lives under `com.cloudflare.api.account.*`).

Verify from the shell:

```bash
TOKEN=$(cat ~/tokens/cloudflare_api_token)
ZONE_ID=$(python3 -c "import json; print(json.load(open('/Users/vyakunin/.cloudflare_setup_state.json'))['zone_id'])")
curl -s "https://api.cloudflare.com/client/v4/zones/$ZONE_ID/analytics/dashboard?since=-1440&continuous=true" \
  -H "Authorization: Bearer $TOKEN" | head -c 200
```

A JSON payload with `totals` / `timeseries` = success. Any `Authentication error`
= permission didn't take (most often because the dashboard edit wasn't saved
or the account scope wasn't ticked).

After that, GraphQL Analytics works for everything the dashboard shows:

```graphql
{
  viewer {
    zones(filter: { zoneTag: "<ZONE_ID>" }) {
      httpRequests1hGroups(limit: 24, filter: { datetime_geq: "..." }, orderBy: [datetime_DESC]) {
        dimensions { datetime }
        sum { requests cachedRequests bytes cachedBytes threats }
        uniq { uniques }
      }
    }
  }
}
```

### Related permissions worth considering

- **Logpush** (`2b3124552acd4fe390a35883e20745c2` *Log Share Reader* / Logpush Read)
  — only needed if we push Enterprise-tier logs somewhere. Free plan doesn't
  get this data; skip.
- **Cache Purge** (zone-scoped) — our token doesn't have it, which is why the
  `verify` phase couldn't purge cache programmatically. Add it if we want the
  bulletin-release-day purge automated (see `## Known gotchas` above).
