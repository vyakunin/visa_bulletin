# Analytics Inventory (visa-bulletin.us)

**Before claiming "we don't have X analytics data", verify against this list.** This rule exists because agents have repeatedly said "no analytics installed" when GoatCounter has been in production since the homeserver migration.

## What's Installed

| Source | What it answers | Auth / location |
|---|---|---|
| **GoatCounter** | Bot-filtered pageviews, unique-ish visits, top paths, geo (country), referrers, browser/OS — JS beacon only, no no-JS visits | API token at `~/tokens/goatcounter.token`; dashboard at `https://vyakunin.goatcounter.com/`; playbook at `docs/deployment/goatcounter.md` |
| **Origin nginx logs (homeserver `vb_nginx`)** | Every HTTP request including bots, status codes, latency, real IPs via `CF-Connecting-IP`, full UA strings | `ssh homeserver "docker logs vb_nginx 2>&1"`. **Log retention is short** (10MB × 3 files per `daemon.json`); typical span ~18-24h. |
| **Postgres (visa_bulletin DB)** | Product-side state: bulletin records, employer counts, salary record counts, ingest run history, VQS prediction cache hit rates | `docker exec vb_postgres psql -U visa_bulletin_user visa_bulletin` on homeserver |
| **Cloudflare** | Edge metrics (cache hit %, requests by country, attacks) — via CF dashboard or API. Account id stored at `~/tokens/cloudflare_account_id`, API token at `~/tokens/cloudflare_api_token`. | Not yet wired into daily_checkup MCP — manual lookup if needed. |
| **UptimeRobot** (uptime monitoring of `visa-bulletin.us`) | Synthetic uptime checks; DOWN/UP transitions; status pages. Currently emails `alert@uptimerobot.com` → `vyakunin@gmail.com` for each transition (subjects `Monitor is DOWN: visa-bulletin.us` / `Monitor is UP: visa-bulletin.us`). Verified active since pre-2026-05-08 Lightsail era. | Dashboard: `https://uptimerobot.com/dashboard`. Per-monitor history visible there. The current email path is the source of the daily_checkup MCP's `uptime` Gmail query — see `mcp/daily_checkup_server.py:GMAIL_QUERIES`. |

## What's NOT Installed (Verified Gaps)

| Missing | Workaround | Tracking ticket |
|---|---|---|
| **Google Search Console MCP** | Manual UI lookup at `https://search.google.com/search-console` for keyword/CTR/impressions data | See memory `project_gsc_mcp_setup.md`; Notion follow-up for "build GSC MCP" |
| **Outbound-click tracking** | None — no measurement of clicks to 3rd parties (e.g. lawyer affiliates) | Would need to add JS event tracking on outbound `<a>` tags; not yet built |
| **GoatCounter unique-visitor counts** | GoatCounter dropped fingerprint dedup; `count_unique` equals `count`. Use nginx `CF-Connecting-IP` unique-IP count as a proxy (still includes bots). | Documented in `docs/deployment/goatcounter.md` §"What to Do If…" |
| **Demographics beyond country** | GC only returns country-level location. No age/gender/income data. | Switch to Plausible/Umami/Matomo if needed — not currently a priority. |
| **Conversion funnel beyond pageviews** | No event tracking for "scrolled past methodology section" / "clicked predict button". | Would need GC custom events (`window.goatcounter.count({event: true, path: "..."})`) on key actions. |

## Quick Query Patterns

### GoatCounter — weekly totals + top paths
```bash
GC_TOKEN="$(cat ~/tokens/goatcounter.token)"
BASE="https://vyakunin.goatcounter.com/api/v0"

# Totals for a date range
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/total?start=2026-05-08&end=2026-05-14" | python3 -m json.tool

# Top 20 paths
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/hits?start=2026-05-08&end=2026-05-14&limit=20" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(h["count"], h["path"]) for h in d["hits"]]'

# Top countries
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/locations?start=2026-04-15&end=2026-05-14&limit=15"

# Top referrers
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/toprefs?start=2026-04-15&end=2026-05-14&limit=15"
```

For anything beyond the top-100 paths, use the export endpoint — see `docs/deployment/goatcounter.md`.

### nginx — count human (non-bot) requests on homeserver
```bash
ssh homeserver "docker logs vb_nginx 2>&1 | grep -v -E 'bot|Bot|crawler|spider' | wc -l"
ssh homeserver "docker logs vb_nginx 2>&1 | grep -v -E 'bot|Bot|crawler|spider' | awk '{print \$1}' | sort -u | wc -l"
```

### Daily checkup MCP — already aggregates GC + nginx + Postgres
The `mcp/daily_checkup_server.py` runs every morning and produces a structured report with traffic deltas, top-mover paths, and per-surface popularity vs performance. **If you need a fast snapshot of "where are we vs last week", read the latest morning digest before running ad-hoc queries.** Logs live in `~/cursor_projects/personal_projects/daily_checkup/logs/reports_*.json`.

## Auto-dispatch to Telegram bot on monitoring incidents

### Two complementary alert paths

| Watchdog | Covers | Blind to | Channel |
|---|---|---|---|
| **UptimeRobot** (external) | `visa-bulletin.us/` reachable / 200 | anything path-specific — it only pings `/`, so a 500 on `/salaries/?employer=X` is invisible | emails → `gmail_dispatcher` `uptimerobot-down` rule → visa_bulletin bot |
| **5xx-spike watchdog** (homeserver cron, every 15 min) | per-path **500s** (app bug, ≥10/window) + gateway **502/503/504** burst (≥20 & rate ≥2%) on the live origin | sub-15-min blips below threshold; non-5xx regressions (wrong content, slow-but-200) | `alert_5xx_spike.sh` → **notify_chat sink** → visa_bulletin relay (agent reacts); Telegram fallback |

The 5xx watchdog exists because UptimeRobot's `/`-only check missed the
2026-06-10 `/salaries/` EmptyResultSet 500 regression entirely (it was 0.53% of
total traffic; `/` stayed 200 throughout). Script:
`deployment/homeserver/scripts/alert_5xx_spike.sh` (deployed to
`/opt/stack/visa_bulletin/scripts/`), cron in `deployment/homeserver/crontab.sample`,
thresholds env-overridable, 60-min per-key cooldown so a sustained outage
alerts once/hour not every tick. The daily_checkup MCP's per-path 5xx RED
(≥100/24h) is the slower digest-level backstop for the same class.

**500 vs 502 split (2026-06-14):** a 500 is a Django app exception (real bug,
has a traceback); a 502/503/504 is an nginx↔upstream gateway failure — almost
always the ~10-15s deploy blip when `vb_web` restarts. Counting them together
produced two false "app exception on a query shape" alarms in one session on
pure deploy-blip 502s. **Rule 1** now fires on per-path **500s only** (the
high-signal app-bug case); **Rule 2** fires on a sustained **gateway 5xx** burst
with a *correctly-labelled* "vb_web unreachable/restarting" message, so a real
outage still pages but a deploy blip is never mislabelled as a code bug.

**Delivery (2026-06-14):** alerts now go through the shared `notify_chat` sink on
the minipc (`agent_infra/scripts/notify_chat.py`, `POST /notify` on
`192.168.1.230:8771`, bearer-auth via `/opt/stack/_shared/notify_chat.env`), which
XADDs a synthetic owner message onto the `listen_chat:visa_bulletin` relay stream —
so the **agent actually reacts** (investigate + act). The old path was a raw
`curl …/sendMessage` bot self-post, which (being from the bot) never appeared in
the bot's getUpdates and so triggered **no** listener — a passive post only,
despite the script's comment claiming "listener auto-spawns." If the sink is
unreachable the watchdog falls back to the old Telegram bot post so an alert is
never dropped. First consumer of the unified alert bus (see
`agent_infra/scripts/README.md` § notify_chat); other watchdogs should deliver via
the same sink instead of hand-rolling `curl sendMessage`.

**Active setup (free-tier UptimeRobot):** Gmail-polling dispatcher at
`~/cursor_projects/personal_projects/gmail_dispatcher/server.py`, launchd job
`com.user.gmail_dispatcher` running every 5 min. Per-project rules live in
`~/cursor_projects/personal_projects/daily_checkup/registry.yaml` under each
project's `dispatch_rules:` key. On Gmail match, the dispatcher sends a
message FROM the user's Telegram account (via telethon + the existing user
session at `~/tokens/telegram_session_string`) TO the project bot
(`vyakunin_visa_bulletin_bot` for this project). The `listen_wa_receiver`
long-polls Telegram getUpdates, sees the new user→bot message, and
auto-spawns Claude with this project's CLAUDE.md loaded — same path as if
you typed in the bot chat manually.

**Latency:** ~5 min worst case (one cron tick). Mac must be awake; on wake,
the next StartInterval tick covers any missed window within 5 min.

**Dedup:** `~/cursor_projects/personal_projects/daily_checkup/dispatcher_seen.json`
keyed by Gmail `message_id`. Each DOWN message fires exactly once, ever.
UptimeRobot sends one email per state transition, so an N-hour outage
produces one DOWN dispatch + zero on the matching UP (UP messages do not
match the rule's subject filter).

### Why NOT UptimeRobot's native Telegram channel

Sounds cleaner, but **gated to paid plans only** (Solo $7-8/mo+; verified
in the dashboard 2026-05-17). On the free tier the integrations menu shows
"Available only in Solo, Team and Enterprise. Upgrade now." for Telegram,
Webhook, Slack, MS Teams, Mattermost, Zapier, and PagerDuty. Free-tier-only
options: Discord, Google Chat, Splunk, Pushbullet, Pushover, and the mobile
apps. None of those reach the existing per-project bot listener without
extra glue, and Discord+bridge would be more code than the Gmail polling
that already works.

Yesterday's earlier version of this section said "use the native Telegram
channel"; that was wrong, since I had not verified plan tier. Corrected
2026-05-17. If donation income ever justifies $84-96/year, swap to native:
real-time vs polling, no Mac-awake dependency.

### Gmail query DSL footgun

`newer_than:30m` does NOT mean 30 minutes — Gmail's `newer_than` only
supports `d` (days), `m` (MONTH, not minutes), `y` (years). For minute-level
filtering use `after:<epoch_seconds>`. For our dispatcher, `newer_than:1d`
is fine since dedup via state catches re-runs.

Hit this on 2026-05-17 first run — `newer_than:30m` matched April history
and dispatched 4 stale DOWN alerts before I caught it. Always `--dry-run`
the dispatcher first after editing a query.

### Adding a new project to dispatch

In `daily_checkup/registry.yaml`, under that project's stanza:

```yaml
    dispatch_rules:
      - query: 'in:inbox from:<sender> subject:"<exact subject>" newer_than:1d'
        forward_to_bot: vyakunin_<project>_bot
        prefix: "🚨 <human-readable headline>"
```

Then **always** run `cd ~/cursor_projects/personal_projects/gmail_dispatcher
&& uv run python server.py --dry-run` once to verify the query matches what
you expect before the next cron tick.

## Rule: Investigating a GoatCounter Spike

When the user points at a peak in the GoatCounter UI and asks "what is this?", walk these steps **in order**. Skipping any step has cost me a wrong-first-reply at least once.

### Step 1 — Convert site-TZ to UTC before anything else

GoatCounter's site timezone is **`DE.Europe/Berlin`** (CEST = UTC+2 in summer, UTC+1 in winter). The dashboard hourly buckets AND the `hourly[24]` array returned by `/api/v0/stats/hits?daily=false` use **site TZ, not UTC**.

```bash
# Confirm site TZ any time:
curl -sS -H "Authorization: Bearer $(cat ~/tokens/goatcounter.token)" \
  "https://vyakunin.goatcounter.com/api/v0/me" | python3 -c \
  "import json,sys; print(json.load(sys.stdin)['user']['settings']['timezone'])"
```

So a peak the user sees at "02:00" in the UI is actually **00:00 UTC** in summer. Always restate the time as UTC in your reply, and use UTC when querying nginx / CF / anything else.

### Step 2 — Confirm which hour holds the peak via narrow API query

Don't trust the `hourly[]` index directly (TZ + zero-fill behavior makes it easy to misread). Spot-check by querying an explicit UTC hour window:

```bash
GC_TOKEN="$(cat ~/tokens/goatcounter.token)"
for h in 22 23 00 01 02 03; do
  d=$([ "$h" -ge 22 ] && echo "2026-05-20" || echo "2026-05-21")
  curl -sS -H "Authorization: Bearer $GC_TOKEN" \
    "https://vyakunin.goatcounter.com/api/v0/stats/hits?start=${d}T${h}:00:00Z&end=${d}T${h}:59:59Z&limit=3" \
    | python3 -c "import json,sys; d=json.load(sys.stdin); print('${h}:00 UTC', d.get('hits',[{}])[0].get('count',0), d.get('hits',[{}])[0].get('path','-'))"
done
```

The hour where the top-path count matches the suspected peak height = your investigation window.

### Step 3 — Pull nginx for the same UTC window

Nginx-side proof goes through `vb_nginx` docker stdout (per the inventory table above, retention ~12-24h):

```bash
ssh homeserver "docker logs vb_nginx --since 12h 2>&1 | grep '21/May/2026:00:' | awk -F'\"' '\$2 ~ /GET \/ HTTP/' | wc -l"

# IPs + UA distribution for the burst (use the literal date string from the log line):
ssh homeserver "docker logs vb_nginx --since 12h 2>&1 | grep '21/May/2026:00:' | awk '{print \$1\"\\t\"\$NF}' | head -30"
```

### Step 4 — Expect GoatCounter > nginx; the gap is Cloudflare edge cache

CF serves cached HTML to the browser without ever hitting origin nginx, but the user's browser still executes the GoatCounter JS pixel. So **GC count ≥ nginx origin count is normal**, and the larger the gap on a high-cache-hit path (`/`, `/salaries/`, popular employer pages), the more CF is doing its job. A small or zero gap means the path is either uncached or cache-busted.

When reporting: state both numbers + the gap, attribute the gap to CF cache.

### Step 5 — Classify the burst

Signatures to call out explicitly in your reply:

| Signature | Diagnosis |
|---|---|
| Many distinct IPs from small islands + Eastern Europe + Africa (T&T, Bonaire, Angola, Mozambique, Romania, Mauritius…) within minutes, uniform Chrome 14X UAs on Win64 | **Residential-proxy bot net.** Common, harmless, ignore — but say so explicitly so the user doesn't take the chart at face value. |
| Single hour with `referrer` ≈ `reddit.com/*` or `news.ycombinator.com/*`, US+India dominant, distributed across 5-15 different paths | **Real social traffic.** Cross-check with the active Reddit / HN post status. |
| Single IP, single path, hundreds of hits in seconds | **Scraper / single-user reload / synthetic test.** Filter out, then re-eval. |
| Server-side bot (ChatGPT-User, bingbot, GPTBot, ClaudeBot) in nginx but absent from GoatCounter | Expected — those don't execute JS. NOT the source of any GC spike. |

Always report the *referrer mix* and *country mix* explicitly when answering "what's this peak?"; that's what tells the user whether to celebrate or ignore.

### Step 6 — If GC export rate-limited, fall back to nginx + per-hour API

`/api/v0/export` is gated to **1 request per hour per token**. If you've already triggered it this hour (the response will say `try again in Xm`), you can still get every signal you need from `/api/v0/stats/hits|locations|toprefs` queried per-hour, plus nginx logs. Don't refuse to answer because export is locked.

## Rule: Check This Inventory Before Answering "Do We Have X?"

When the user (or you, internally) ask "do we have analytics on Y?":

1. Match Y against the **What's Installed** table — if it's covered, query the right source rather than guessing.
2. If Y maps to a known gap in **What's NOT Installed**, say so and reference the row (so the next reader knows the workaround / tracking ticket).
3. Only say "we don't have any analytics" if BOTH tables have been consulted. Default-deny on this claim — it's been wrong too often.

**Why this rule exists:** During a 2026-05-15 Telegram exchange about a Manifest Law partnership pitch, I claimed "no analytics installed" while GoatCounter had been in production for 7+ days, biasing the audience-size numbers low by ~1.5-2× and the geo split by guesswork. The user caught it; this rule prevents the repeat.
