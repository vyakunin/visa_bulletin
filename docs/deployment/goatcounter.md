# GoatCounter — Agent Playbook

Notes for a future agent asked to "check goatcounter / vyakunin.goatcounter.com".
Read this **before** fetching anything.

## TL;DR — Don't Scrape the Dashboard

`https://vyakunin.goatcounter.com/` is a **JS-rendered single-page app**. The HTML
shell has ~100 lines, contains only loader markup and an empty `<script>` bootstrap,
and zero statistics. `curl` / `WebFetch` on the dashboard will always look empty.
Don't retry with different user agents — there's nothing to find.

Public "counter" endpoints (`/counter/<path>.json`, `/counter/TOTAL.json`) return
**HTTP 403** unless the site owner ticked "Allow using the visitor counter" in
Settings. On this site, that toggle is **off**, so they return:

```
error 403: Need to enable the 'allow using the visitor counter' setting
```

So the public surface is effectively zero. Everything useful is behind the API.

## How to Actually Get Data: API v0

**Base URL:** `https://vyakunin.goatcounter.com/api/v0/`
**Auth:** `Authorization: Bearer <token>` (header).
**Token source:** ask the user to generate one in the dashboard:
  Settings → API → "Generate new token" → copy the string.
  Recommend they save it to `~/tokens/goatcounter.token` (mode 600) to match
  the existing file on this machine.

**Read the token in scripts** exactly like other tokens in this repo:
```bash
GC_TOKEN="${GC_TOKEN:-$(cat ~/tokens/goatcounter.token 2>/dev/null)}"
```

### Useful endpoints

| Endpoint | Purpose |
|---|---|
| `GET /api/v0/sites` | List sites — the cheapest token sanity check (no `/api/v0/me` endpoint exists on this host) |
| `GET /api/v0/stats/total?start=YYYY-MM-DD&end=YYYY-MM-DD` | Pageview + visitor totals for a range |
| `GET /api/v0/stats/hits?start=...&end=...&limit=100` | Top-100 hits by count (limit max ≈ 100) |
| `POST /api/v0/export` + `GET /api/v0/export/<id>` + `GET /api/v0/export/<id>/download` | Full CSV export — **use this for anything beyond the top ~100 paths** |

**Unique visitors are NOT exposed as a separate metric** (verified 2026-05-14). GoatCounter dropped fingerprint-based deduplication for privacy in a recent version. The `/counter/` and `/stats/total` endpoints will report a `count_unique` field but it equals `count` (pageviews) on this site (and likely all modern GC installs). If you want a real "unique humans" proxy:
- Use origin nginx logs with `$http_cf_connecting_ip` and count unique IPs per window (still includes bots; filter by UA if needed).
- Or switch to Plausible/Umami/Matomo for true uniques.

**Public counter endpoint is now enabled.** As of 2026-05-14 the site has `allow_counter: true` (flipped via PATCH `/api/v0/sites/68357`). That makes the cheap public endpoint `https://vyakunin.goatcounter.com/counter/TOTAL.json?start=YYYY-MM-DD&end=YYYY-MM-DD` work without auth — returns `{"count": "...", "count_unique": "..."}` for the date range.

Endpoints that DO NOT exist / do NOT work on this host (verified 2026-04-24):
- `/api/v0/me` → 404
- `/api/v0/site` → 404
- `/api/v0/user` → 404
- `/api/v0/paths` → 500 (internal error; don't bother)
- `/api/v0/stats/hits?offset=N` → 400 `unknown parameter: "offset"`
- `/api/v0/stats/hits?filter=/prefix/` → 400 `unknown parameter: "filter"`

Implications:
- `stats/hits` returns `{hits: [...], total, more}`. **`more: true` cannot be
  paged** — the API has no offset/cursor for this endpoint. You get the top 100
  paths by count for the window, period. Everything outside the top 100 is only
  reachable via the full CSV export.
- **No server-side path filtering.** If you need `/job-title/` vs `/employer/`
  breakdowns, you must either: (a) accept the top-100 truncation and
  bucket client-side, or (b) pull the full export and aggregate offline.

Notes:
- Dates are inclusive on both ends, UTC, `YYYY-MM-DD`.
- Rate limit: responses include `X-Rate-Limit-Remaining` / `X-Rate-Limit-Reset`.

### Minimal worked example

```bash
GC_TOKEN="$(cat ~/tokens/goatcounter.token)"
BASE="https://vyakunin.goatcounter.com/api/v0"

# 1. sanity check (use /sites, not /me — /me returns 404 here)
curl -sS -H "Authorization: Bearer $GC_TOKEN" "$BASE/sites" | python3 -m json.tool

# 2. totals for a week
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/total?start=2026-04-17&end=2026-04-24" | python3 -m json.tool

# 3. top 100 paths this week
curl -sS -H "Authorization: Bearer $GC_TOKEN" \
  "$BASE/stats/hits?start=2026-04-17&end=2026-04-24&limit=100" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); [print(h["count"], h["path_id"], h["path"]) for h in d["hits"]]'
```

### Full export (required for any deep analysis)

The export endpoint is the **only** way to get every hit — there is no
pagination on `/stats/hits` and no `paths` endpoint that works. Use this
whenever you need anything beyond the top-100 paths.

```bash
GC_TOKEN="$(cat ~/tokens/goatcounter.token)"
BASE="https://vyakunin.goatcounter.com/api/v0"

# 1. kick off the export (returns HTTP 202 + {"id": N, ...})
ID=$(curl -s -X POST "$BASE/export" -H "Authorization: Bearer $GC_TOKEN" \
     -H 'Content-Type: application/json' -d '{"start_from_hit_id": 0}' \
     | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

# 2. poll until finished_at is set (~15-30s for ~300k rows)
while :; do
  FIN=$(curl -s "$BASE/export/$ID" -H "Authorization: Bearer $GC_TOKEN" \
        | python3 -c 'import json,sys; print(json.load(sys.stdin)["finished_at"])')
  [ "$FIN" != "None" ] && break
  sleep 5
done

# 3. download the gzipped CSV
curl -s "$BASE/export/$ID/download" -H "Authorization: Bearer $GC_TOKEN" \
  -o /tmp/gc_export.csv.gz
gunzip -f /tmp/gc_export.csv.gz
```

**CSV format gotcha:** the first byte of the CSV is a format-version digit
(currently `2`), not part of the header. The actual header starts at byte 2:
`Path,Title,Event,UserAgent,Browser,System,Session,Bot,Referrer,Referrer scheme,Screen size,Location,FirstVisit,Date`.
Strip the leading digit before passing to `csv.DictReader`, e.g.:

```python
with open("/tmp/gc_export.csv") as f:
    first = f.readline()
    if first and first[0].isdigit(): first = first[1:]
    header = [h.strip() for h in first.rstrip("\n").split(",")]
    reader = csv.DictReader(f, fieldnames=header)
```

The export returns the **entire site history**, not filtered by date. Filter
client-side on the `Date` column (ISO 8601 UTC).

`Bot` column: `0` for human hits, non-zero for bot flagged (JS beacon already
filters most, so most hits are `0`). `FirstVisit=1` marks unique-ish visitors.

## What to Do If the User Won't Give You a Token

Fall back to the origin nginx logs on the homeserver — they are more granular
(real client IPs via Cloudflare `CF-Connecting-IP`, exact timestamps, status
codes, referers). Prod nginx now runs in the `vb_nginx` container and logs to
docker stdout (short retention, ~12–24h — see `.claude/rules/analytics.md`), so
read them with `docker logs`, not from `/var/log/nginx`:

```bash
ssh homeserver 'docker logs vb_nginx 2>&1 | awk "..."'
```

See `.claude/rules/deployment.md` for the current topology. The tradeoff: origin
logs include bot traffic that
GoatCounter's JS beacon strips (no JS ⇒ no hit), so numbers will be 3–5×
higher than GC. That's still the right dataset for "is traffic healthy" and
"which slugs 404" — it's only wrong for "unique humans".

## Correlating GoatCounter With Origin Logs

GoatCounter undercounts on purpose (no bots, no no-JS clients, no ad-blocked
visits). To reconcile:
- **Humans, JS enabled** → visible in both GC and nginx with a real browser UA.
- **Humans with JS/ad-blocker off** → only in nginx.
- **Bots** → only in nginx (GC beacon never fires).
- **Server-rendered API calls** (e.g. `/sitemap.xml`, `/robots.txt`) → only in nginx.

Useful comparison: take nginx requests where `$http_user_agent` matches a real
browser and the path matches a real page (no `.xml`, no `.txt`, no `/api/`),
then compare that floor to GoatCounter's "visitors" for the same window. GC
should be ≤ that floor; gap = no-JS visits.
