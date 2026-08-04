# Deployment and Rollout Rules

> Concrete hosting topology (hosts, IPs, hardware, the staging/standby/cutover mechanics, backup wiring, DR) lives in the private ops repo, not in this public repository. Public docs use abstract roles (production / staging / data-pipeline server).

## Production Topology (abstract)

Production is a single Docker Compose stack at `/opt/stack/visa_bulletin/` on the **production server**. All public traffic enters via Cloudflare Tunnel — there are **no router port forwards**. TLS terminates at the Cloudflare edge.

| Container | Purpose | Image / Notes |
|---|---|---|
| `vb_postgres` | PostgreSQL 14, DB on `./postgres-data/` | `postgres:14` |
| `vb_redis` | Page cache, Django sessions | `redis:7-alpine`, 512 MB maxmemory allkeys-lru |
| `vb_web` | Django + gunicorn 23 (3 workers × 2 threads) | `ghcr.io/vyakunin/visa_bulletin:${IMAGE_TAG}` |
| `vb_nginx` | Static file serving + reverse-proxy to web | `nginx:1.27-alpine`, listens on internal `:80` |
| `vb_cloudflared` | Cloudflare Tunnel connector (QUIC to CF edge) | `cloudflare/cloudflared:latest` |

**Public hostnames** (CF Tunnel ingress):
- `visa-bulletin.us`, `www.visa-bulletin.us` — production
- `staging.visa-bulletin.us` — staging

**SSH access:** the real host alias and credentials live in the private ops repo. In public docs, "SSH to the production server" means whatever alias is configured there.

## Production Deploy Process

> **Routine promotions default to the ZERO-DOWNTIME cutover, not this in-place swap.**
> The private ops repo's `hosting/cutover.sh --code <sha>` swaps the prod image while a
> second stack serves prod traffic, so vb never 502s (see `branching.md` § "Promote via
> the ZERO-DOWNTIME cutover"). The in-place `docker compose up -d web` below is the
> **mechanics that sits under it** and the **disruptive fallback** (used only when the
> cutover is unavailable, or a true prod-down hotfix). The low-traffic-window rule below
> applies to that fallback's 502 window — the cutover has no such window.

**The in-place code deploy is `docker compose pull web && docker compose up -d web`. It has
~10-15s of customer-facing 502s** while the old container stops and the new
one boots (migrate + collectstatic + gunicorn). CF-cached pages keep serving
from the edge during the window; uncached/POST requests fail.

### Rule: check the low-traffic window before pushing to prod

Per the GSC + GoatCounter daily-checkup data, dashboard traffic is ~5-7k
views/day with a clear monthly cycle. Before doing a prod deploy, consult
the **most recent daily_checkup digest** (or pull `gsc_query_search_analytics`
+ GoatCounter directly) to find the local low-traffic hour. As of mid-2026
the rough pattern is:

| Window (UTC) | Berlin local | PDT local | Typical traffic |
|---|---|---|---|
| 22:00-06:00 | 00:00-08:00 | 15:00-23:00 | **low** (deploy-safe) |
| 06:00-12:00 | 08:00-14:00 | 23:00-05:00 | medium |
| 12:00-22:00 | 14:00-00:00 | 05:00-15:00 | **peak** (avoid) |

Re-verify these bands quarterly — the user base skews US + India so the
peak shifts seasonally. The daily_checkup MCP can be extended to surface a
"current hourly position vs cycle" line if this needs to be automated.

If a deploy genuinely cannot wait for the low-traffic window (security
patch, broken bulletin parser before publication), accept the 502 window
and proceed — but state explicitly *"deploying at peak, expected ~3-5 user
errors"* so the cost is visible.

### Deploy command

SSH to the production server and run:

```bash
cd /opt/stack/visa_bulletin
# Update IMAGE_TAG in .env if needed (default is "latest" which tracks prod branch builds)
docker compose pull web
docker compose up -d web   # recreates only web; postgres, redis, nginx, cloudflared untouched
docker compose logs --tail 30 web   # confirm migrate + collectstatic + gunicorn boot
curl -s -o /dev/null -w "%{http_code}\n" https://visa-bulletin.us/   # 200
# After deploy: flush Redis page cache so the new content is served, not the pre-deploy cache
docker exec vb_redis redis-cli -n 1 FLUSHDB
```

Then pre-warm the top cacheable pages so the next cold user doesn't pay the 2-3s
render (repopulates Django's `@cache_page` Redis entries; CF then re-caches at the
edge). **Run this from a repo checkout, NOT on the prod box** — it curls the public
URL, and neither form works there: the box has no `scripts/` checkout (`/opt/stack/
visa_bulletin/` is the stack dir, not the repo), and `vb_web` ships **no `curl` and
no `wget`**, so `docker exec vb_web bash /app/scripts/warm_cache.sh` fails every URL
with `ERR` and reports `20/20 non-200` — a failure that reads like the site being
down rather than a missing binary.

```bash
cd ~/cursor_projects/visa_bulletin
./scripts/warm_cache.sh   # see scripts/README.md § Deployment; --base for staging
```

`/predictions/<YYYY>-<M>/` answering **301** in the warmer's output is expected, not
a miss — the numeric slug redirects to the canonical word-month URL, so the run's
"1/20 non-200" line is the healthy result.

### Known issue: recreating `web` can strand nginx on the dead container's IP

`nginx/visa_bulletin.conf` uses `proxy_pass http://web:8000` with no `resolver`, so
nginx resolves `web` **once, at config load**. Recreate the web container onto a
different bridge IP and nginx keeps connecting to the dead one: **every request 502s
instantly** — `~0.000s` request_time, `connect() failed (111: Connection refused)` in
nginx's error log naming the stale IP, **nothing in `vb_web`'s own logs**, and the
container reporting `healthy`. The symptom points away from the cause, and it reads
like an app fault when it is a networking one.

It hides most of the time because a lone `docker compose up -d web` reclaims the same
IP. Recreate anything alongside it and the allocation shifts (measured 2026-07-27 on
staging: web moved `.4` → `.5` when redis was recreated in the same run, and the whole
surface 502'd).

Diagnose in two commands — if these disagree, that's the bug:
```bash
docker inspect vb_web   --format '{{range .NetworkSettings.Networks}}{{.IPAddress}} {{end}}'
docker exec   vb_nginx  getent hosts web
docker logs   vb_nginx --tail 50 2>&1 | grep upstream   # names the IP nginx is using
```
Fix: `docker compose restart nginx`, then re-check. Confirm the app itself is fine
first by hitting gunicorn directly, bypassing nginx:
`docker exec vb_web python3 -c "import urllib.request as u; print(u.urlopen('http://localhost:8000/').status)"`.

The release scripts handle this themselves since `hosting` commit `566369d` —
`promote.sh` and `cutover.sh`'s `hs_web_swap` bounce nginx after the web swap and
**assert** its upstream matches the live container before continuing. You only need the
manual recipe for a hand-run `docker compose up -d web`.

### Rule: Capture a pre-deploy perf baseline + post-deploy verification window

**Every prod deploy (code, schema, infra) MUST include a pre-deploy baseline snapshot AND a 30-minute post-deploy verification window** with the same signals. Latency / 5xx regressions after a deploy are common (planner picks a new plan after schema changes, a new view forgets to use `select_related`, a Redis cache clear cold-starts every page) and they are catastrophically cheap to detect early and expensive to detect via user reports. This rule exists because the 2026-05-17 staging-crawl incident showed that perf regressions silently degrade UX for hours unless deliberately monitored — and because that incident's own fix (trigram indexes) needed verification it wasn't trivially providing.

**Pre-deploy snapshot (T-5min, save to /tmp/predeploy_$(date +%s).txt or paste into chat).** SSH to the production server and run:

```bash
uptime
free -h | head -2
docker stats --no-stream --format '{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
echo '--- 5xx last 30 min ---'
docker logs vb_nginx --since 30m 2>&1 | grep -E '\] "[A-Z]+ [^"]+" 5' | wc -l
echo '--- gunicorn SLOW REQUEST last 30 min ---'
docker logs vb_web --since 30m 2>&1 | grep -c 'SLOW REQUEST'
echo '--- request rate last 5 min ---'
docker logs vb_nginx --since 5m 2>&1 | grep -cE '\] "[A-Z]+'
```

**During deploy:** keep `docker logs -f vb_web` open in one terminal. Expected: the ~10-15s 502 window during container swap. Anything else is a regression — abort and roll back per the rollback section.

**Post-deploy verification (T+5, T+15, T+30):** re-run the snapshot block above and compare against pre-deploy. Acceptable drift:

| Signal | Pre → Post acceptable | Investigate / roll back |
|---|---|---|
| Host load (1m) | within 1.5× of pre | >2× and sustained 5+ min |
| vb_postgres %CPU | within 1.5× of pre | >3× and sustained 5+ min |
| vb_web mem (per container) | within 1.3× of pre | >1.5× and growing |
| nginx 5xx / 30 min | ≤ pre + 5 (cold-start 502s normal) | > pre + 15, or any sustained 5xx after T+5 |
| gunicorn SLOW REQUEST / 30 min | ≤ pre + 10% | > pre + 50% — almost certainly a planner regression |
| nginx 5xx on any **single** path / 30 min | 0 sustained | any path with sustained fast 500s (not 502 cold-start) → app exception on that query shape, roll back |

**Adversarial-input smoke (run once at T+5, on any deploy that touches a view/query/filter).** A 200-status smoke on canonical URLs does NOT exercise empty/zero-result paths — the exact shape that 500'd on 2026-06-10 (`/salaries/?employer=<name-that-matches-no-cluster>` → `records.none()` → uncaught `EmptyResultSet`). Probe the zero-result + degenerate branches explicitly:

```bash
BASE="https://visa-bulletin.us"
for u in \
  "/salaries/?employer=ZZZNONEXISTENTEMPLOYER999" \
  "/salaries/?q=ZZZNONEXISTENTTITLE999" \
  "/salaries/?employer=ZZZNONEXISTENT&q=ZZZNONEXISTENT&state=NY" \
  "/salaries/?employer=GOOGLE+LLC&page=99999" \
  "/employers/?q=ZZZNONEXISTENT" \
  "/job-titles/?q=ZZZNONEXISTENT" ; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 20 "$BASE$u")
  printf "%-60s %s\n" "$u" "$code"   # every line MUST be 200 (empty result page), never 5xx
done
```
Any 5xx here = an uncaught exception on the empty/degenerate branch → roll back, don't fix forward. Add the analogous zero-result URL for any new filterable list view you ship.

**For DB-touching deploys** (schema changes, new indexes, query rewrites): also EXPLAIN ANALYZE the affected query path **inside Django** (parameterized) — not just literal psql, because Django's `__icontains` emits `UPPER(field) LIKE UPPER(%s)` and the planner gives different plans for parameterized vs literal strings. SSH to the production server and run:

```bash
docker exec vb_web python3 -c "
import django, os, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'django_config.settings')
django.setup()
from django.db import connection
from django.conf import settings
settings.DEBUG = True
from models.salary import SalaryRecord
from django.db.models import Q
qs = SalaryRecord.objects.filter(Q(job_title__icontains='CASHIER') | Q(soc_title__icontains='CASHIER')).exclude(is_worksite=True).exclude(employer_name='Unknown').filter(wage_annual__isnull=False, wage_annual__gt=0).order_by('-wage_annual','-fiscal_year')
t0=time.time(); list(qs[:50]); print(f'{(time.time()-t0)*1000:.0f}ms')
print(connection.queries[-1]['sql'][:300])
"
```

A query that's <100ms via literal psql but >1s via this Django path is a planner-LIMIT-pessimization signature: the index exists but the planner picks Index Scan Backward on `wage_annual` instead. Trigram indexes alone do not fix this — needs a code-level subquery rewrite (force a Bitmap path). **Implemented** for the salary / worksite list views by `lib/utils/filter_utils.py:fenced_page_ids` (an `OFFSET 0` fence resolves the ordered page of pks via a Bitmap Heap Scan, then the ≤50 rows are fetched by pk with `select_related`). Measured on prod: `ENGINEERS` p4 5959→1614ms, `Architect` 2444→479ms, `CASHIER` 39→6ms. If you reintroduce a `.order_by('-wage_annual','-fiscal_year')[slice]` over a trigram-filtered queryset anywhere, route it through `fenced_page_ids` or it will pessimize again. Since 2026-07-04 the COLD `/salaries/` filtered-search path uses `fenced_page_and_aggregate` instead — one `AS MATERIALIZED` fenced scan yields both the ordered page and the count/avg/min/max (the old `fenced_aggregate` + `fenced_page_ids` pair scanned the 55k-391k-row match set twice; prod ENGINEERS 3196→1965ms). A view needing page + aggregate over the same filter should use the combined resolver, not the pair.

**Heavy mutations (CREATE INDEX, ALTER TABLE, schema migrations) MUST use the CONCURRENTLY form so reads + writes continue.** A non-concurrent ALTER on `salary_record` (1.5M rows) acquires AccessExclusiveLock and blocks every reader for the duration → effective outage. See migrations 0044, 0046, 0047 for examples of the `RunSQL(... atomic=False)` pattern.

**Rollback triggers — if any of these fire in the verification window, roll back immediately, don't try to fix forward in prod:**
- Sustained 5xx > 5/min for 5 consecutive min.
- p95 request latency >5× pre-deploy.
- vb_postgres CPU saturated (>80%) for 5+ min without an obvious upstream cause (cron, ANALYZE).
- Bot/scraper crawl that the deploy was supposed to mitigate is *worse* afterward.

Rollback is just `IMAGE_TAG=<previous_sha>` in .env + `docker compose pull web && docker compose up -d web` + flush Redis. No fancy orchestrator needed since the registry keeps the prior image.

### Rule: Regenerate stored content after a generator/narrator change

**A change to a content GENERATOR (`lib/business/blog/bulletin_narrator.py`, the
blog-post builders, anything that writes `BlogPost.body_html`, predictions copy,
baked HTML) only affects NEWLY-generated content. Already-published rows keep
their old stored HTML until explicitly regenerated.** The `refresh_bulletin` run
(now driven by the minipc bridge, see "Weekly DB Refresh Pattern") **skips
already-published posts** (`if BlogPost.objects.filter(slug=…, is_published=True)
.exists(): return`) — it only creates NEW posts. So shipping a narrator fix is
inert on existing pages until you regenerate.

After deploying such a change, regenerate the affected published posts (the
mechanical follow-up — do it, don't wait to be asked; cf. `vqs.md` "Run
Mechanical Follow-Up Steps Automatically"):

**Call the builder for the post you actually mean. They are different functions, and
one of them deletes.**

| Post | Function |
|---|---|
| `/analysis/how-my-prediction-model-works/` (Methodology) | `create_methodology_post()` |
| `/analysis/visa-bulletin-analysis-<month>/` (the monthly narrator set) | `create_analysis_posts(n=…)` |
| the i129 data stories | `create_i129_story_posts(only_slug="…")` |

```bash
# Methodology post — regenerates one row, deletes nothing.
docker exec -w /app vb_stg_web python3 -c \
  "from scripts.oneoff.generate_initial_blog_posts import create_methodology_post; create_methodology_post()"
docker exec vb_stg_redis redis-cli -n 1 FLUSHDB
# verify the rendered page reflects the change, then repeat on prod (vb_web / vb_redis)
# + CF-purge the /analysis/<slug>/ URLs (cloudflare.md).
```

🚨 **`create_analysis_posts(n)` PRUNES: it deletes every `category="Analysis"` post
outside the newest `n` it just built.** So `n` is not a "how many to refresh" knob — it
is the number that SURVIVES. Never hardcode it (this rule said "currently 9" while prod
had 10, i.e. following it would have deleted `visa-bulletin-analysis-november-2025`).
Read the live count and pass it:

```bash
docker exec -w /app vb_web python3 -c \
  "import django; django.setup(); from models.blog import BlogPost; \
   print(BlogPost.objects.filter(category='Analysis').count())"
# then pass that number (or more) as n
```

Note the `django.setup()`: importing a builder from `generate_initial_blog_posts` does
it for you (the module calls it at import), but a bare `from models.blog import …` does
not and dies with `AppRegistryNotReady`.

🚨 **Never run the module with `-m` / as a script.** Its `main()` calls
`create_analysis_posts(n=2)`, which on a 10-post prod deletes eight published pages.
Always import the specific builder with `python3 -c`, as above. The module calls
`django.setup()` at import, so no extra bootstrap is needed.

Then **verify the rendered page actually changed** (`verify_end_state.md`) — a
200 isn't enough; grep the rendered HTML for the expected delta. Origin:
2026-06-18 — the `01f750b` surprise-card gating shipped to prod as code but the
EB-4/EB-5 cards stayed live for hours because the 5 published posts were never
regenerated; caught only when the user screenshotted staging.

### Rule: Diff staging vs prod HTML for top properties before graduation

**Before promoting `staging-<sha>` to prod, diff a handful of top URLs between `https://staging.visa-bulletin.us/` and `https://visa-bulletin.us/` and read the diff manually.** Smoke tests confirm the page is HTTP 200; this confirms the page is *correct*. Code deploys can silently change content (template tweaks, view-context shifts, regenerated blog narrator output, new feature flags) in ways that no individual unit test covers but a side-by-side diff makes obvious.

**When to run:** after staging is up on the new image, before `git merge --ff-only staging` on the prod branch. Treat it as the last gate.

**URL set (covers ~80% of risk surface):**
- `/` — homepage (top traffic, lots of dynamic widgets)
- `/employment-based/india/` — top per-country dashboard
- `/predictions/employment_based/<latest-month>/` — current EB predictions (data-heavy + template-heavy)
- `/predictions/family_sponsored/<latest-month>/` — current FS predictions
- 2-3 **historical** prediction months (e.g. `/predictions/2024-1/`, `/predictions/2020-1/`, `/predictions/2005-1/`) — these should be *invariant* once published; any diff here is a regression
- The methodology blog post `/analysis/how-my-prediction-model-works/` — narrator output + manual edits, easy to drift between DBs
- The latest monthly blog post (whichever `/analysis/visa-bulletin-analysis-<latest-month>/` is freshest)

**Helper — the committed script `scripts/staging_prod_diff.sh`** (run from the repo root; documented in `scripts/README.md` § Deployment):

```bash
./scripts/staging_prod_diff.sh                 # summary table (filtered difflines per URL)
./scripts/staging_prod_diff.sh --show          # + dump the filtered diff for URLs that differ
./scripts/staging_prod_diff.sh --show /         # one specific path
PROD_BASE=... STAGING_BASE=... PRED_MONTH=2026-7 ./scripts/staging_prod_diff.sh   # env overrides
```

It curls the URL set above on both stacks, saves artifacts to `/tmp/vb_diff/{prod,stg}_<slug>.html`, and prints the **filtered** diffline count per URL (exit 1 if any URL differs). `PRED_MONTH` defaults to the current year-month.

The script's `sed` rewrite of `staging.visa-bulletin.us → visa-bulletin.us` is **load-bearing** — without it every canonical_url, og:url, og:image, twitter:url, and schema.org Dataset URL shows as a diff and drowns out real signal. Its `grep -vE` filter strips known-cosmetic noise: the rotating Cloudflare email-obfuscation tokens (`data-cfemail=...`) which differ on every request, and any GoatCounter / `data-gc-event` content that's been merged to staging but not yet on prod (which IS the deploy you're about to do — those diffs are *expected*).

**Then inspect each URL with non-zero difflines and classify the block** (`--show` dumps the filtered diff; or hand-run `diff /tmp/vb_diff/prod_<slug>.html /tmp/vb_diff/stg_<slug>.html | grep -vE '(goatcounter|data-cfemail|cdn-cgi/l/email-protection|window\.goatcounter|data-gc-event)' | head -80`):

**Classify what's left:**

| Diff kind | What it means | Action |
|---|---|---|
| Different `<link rel="canonical">` host (other than the substituted hostname) | Origin is generating wrong canonical — typically a stale Redis cache populated by a non-CF probe (Docker healthcheck hits `http://localhost:8000/`). | Investigate; usually `docker exec vb_stg_redis redis-cli -n 1 FLUSHDB` and re-test. Block graduation until canonical is right. |
| Historical prediction (`/predictions/<YYYY-M>/` for past months) HTML body differs | `PredictedCutoff` rows differ between staging DB and prod DB — staging has a regenerated model snapshot that never published to prod, OR prod has manual edits. | Pure data divergence. Code-only deploy doesn't sync DB, so prod stays as-is. Decide separately whether to `publish_predictions` on prod with the staging model output, or to leave both DBs as-is and accept the preview is misleading. **Does NOT block code graduation** unless the user wants the model output to ship too. |
| Latest prediction month (`/predictions/employment_based/<latest>/`) differs in cells, badges, CI widths | Same as above — data divergence. Inspect: if changes are template-driven (new badge class never seen on prod), check the diff prod..staging on `webapp/templates/` to confirm. If pure data, classify as data-only. |
| Methodology / latest-month analysis blog post body differs (paragraph present in one, missing in the other) | `BlogPost.body_html` divergence in the DB. Often staging was regenerated without manual prod-side edits. | Surface to user: "If you regenerate <post> on prod after this deploy, you will lose <description of paragraph>." Block graduation only if user wants prod to match staging exactly. |
| Different view-context numbers (filing counts, employer counts, top-N lists) | Different underlying data — staging DB is a different snapshot than prod DB. | Expected. Don't block on this. |
| New template structure (added/removed `<div>`, new CSS class, different element order) where the diff aligns with files touched in the `prod..staging` range | Intentional code change. | Expected for this deploy. ✓ |
| Template/data difference NOT aligned with any commit in `prod..staging` | Mystery. Investigate before graduating. | **Block** until root cause found. |

**Quick "what code differs prod..staging" cheat-sheet:**

```bash
cd ~/cursor_projects/visa_bulletin_staging
git log --oneline origin/prod..origin/staging
git diff --name-only origin/prod..origin/staging | grep -E '(webapp/views|webapp/templates|models)' | head -20
```

Cross-reference unexplained HTML diffs against this list. If the diff is in `webapp/templates/webapp/blog_post.html` and that file is in `git diff`, you know which commit to read. If it isn't in `git diff`, the divergence is data.

**Why this rule exists:** 2026-05-27 — after a cherry-pick chain to staging, smoke tests passed but a manual diff against prod surfaced (1) a 9-line "Scope of accuracy claims" paragraph missing from staging's methodology BlogPost (DB drift), (2) substantively different EB prediction values + confidence intervals (data drift in `PredictedCutoff`), and (3) `<link rel="canonical" href="http://localhost:8000/">` on staging's homepage cache (Docker healthcheck populating cache with no Host header). None of those would have failed a 200-status smoke test. The diff caught all three in ~5 minutes.

### Zero-downtime promotion — BUILT, in the VB platform repo (default path)

The zero-downtime promotion this section once speculated about **is built** and is now the
**default** for routine prod promotions: `visa_bulletin_platform/hosting/cutover.sh --code <sha>`
(code) / `--data` (DB-level). It gates on staging then swaps the homeserver image while a second
stack serves prod traffic, so vb never 502s. See `branching.md` §"Promote via the ZERO-DOWNTIME
cutover" for the policy and `hosting/RELEASE_PATHS.md` for the engine. Do NOT build a parallel
`tools/blue_green_deploy.sh` in this public repo — all release tooling lives in `hosting/`
(`branching.md` §"Two-repo split"). The in-place `docker compose up -d web` below is only the
under-the-hood mechanics + the `--accept-502` disruptive fallback.

**Building images** still happens via the GitHub Actions workflow on push to `staging`/`prod` branches — see "Docker Image Strategy" below. Nothing about the build/registry side changed; only the runtime moved.

## Weekly DB Refresh Pattern (spec — not yet implemented)

The weekly visa-bulletin + salary refresh is a heavy job (millions of rows, index drop/rebuild, ~30 min) that would lock the prod DB during ingest. The pattern keeps prod read-only throughout: reset the staging DB from a prod snapshot, run the refresh pipeline against staging, smoke staging, then atomically promote (postgres-data volume swap or pg_dump → restore), then re-seed staging for the next cycle.

> The concrete staging/cutover mechanics — exact host moves, volume paths, and DR — live in the private ops repo, not in this public repository.

**Bulletin refresh** is light (one HTML fetch + ~1 row insert) but no longer runs *from* prod. `travel.state.gov` sits behind Akamai Bot Manager and `vb_web` has no browser, so the old hourly prod cron 403'd on discover for every run — and did so **silently**, exiting 0 with "No pending bulletins to ingest" (a green-looking no-op that ingested nothing). It was **retired 2026-07-16**; do not re-add it.

Ingest is now the **minipc → prod bridge**, `scripts/sync_bulletin_to_prod.sh`, cronned on the **minipc**: it browser-fetches via the debug Chrome on `:9222`, streams the HTML into `vb_web`, and runs the unchanged `scripts.cron.refresh_bulletin` there with `BULLETIN_HTML_CACHE_DIR` set, so parse/load/predict still happen prod-side. Idempotent (dedup by `DataSource`).

```bash
# on the MINIPC (not prod) — cadence: */30 while awaiting a bulletin, 0 */4 otherwise
*/30 * * * * .../visa_bulletin/scripts/sync_bulletin_to_prod.sh >> .../logs/sync_bulletin_to_prod.log 2>&1
```

**Wedged debug Chrome (self-healing since 2026-07-27):** Chrome can wedge while still
looking alive — `/json/version` answers, the CDP websocket connects, and then
`connect_over_cdp` hangs to its 180s timeout because no page target responds. A naive
"is :9222 up?" check passes throughout, so this reads as the Akamai wall failing. Seen
after Chrome had been up 10 days with 8 leaked heavy-SPA tabs (one renderer alive for
eight page targets); every run failed for ~12h. The bridge now detects that exact
signature (ws connected + `connect_over_cdp` timeout — which proves the browser is
unusable by *any* agent, so restarting the shared service is safe), restarts
`debug_chrome_cdp.service` once, retries the fetch, and reports passively. Kill switch:
`BULLETIN_CDP_AUTOHEAL=0`. A browser that stays wedged still falls through to the normal
failure streak + alert. Diagnose by hand with a per-target `Runtime.evaluate` probe — if
every target times out the browser is wedged, not the wall. Pinned by
`//tests:test_bulletin_sync_alerting`.

**Monitoring:** the bridge is the only bulletin ingest path and self-alerts to the visa_bulletin bot via `notify_chat` — a fetch-failure *streak* (single misses are transient: the Akamai challenge fails ~1 run in 6 and the next recovers), an immediate alert on never-transient breaks (refresh non-zero, discovered-but-unignested, stream-to-vb_web failure), and an `inject` when a new bulletin lands. Its one structural blind spot — the cron never firing at all — is backstopped by the daily_checkup MCP, which grades the age of `~/.local/state/visa_bulletin/last_success`. `//tests:test_bulletin_sync_alerting` pins that state-file contract; the prod-side `logs/cron/bulletin_refresh.log` is frozen by design and its staleness is **not** an ingest failure.

## Docker Image Strategy

Images built by GitHub Actions on pushes to `staging`/`prod` branches or version tags.

- `:latest` — prod branch builds only. Used by `docker-compose.yml` default.
- `staging-<sha>` / `prod-<sha>` — branch-specific SHA tags.

**Image contains:** Python runtime, system deps (libpq5), pip packages, gunicorn, baked-in app code.

**Prod and staging both run baked-in image code** (no `../:/app` volume mount). To deploy code changes: push to branch → wait for CI to publish the image → swap the image tag on the target stack. **For prod that swap is the zero-downtime `hosting/cutover.sh --code <sha>`** (`branching.md`); the bare `docker pull` + `docker-compose up -d web` on the server is the staging path / disruptive prod fallback only.

**⚠️ CRITICAL:** `docker restart` does NOT update the image. To deploy a new image you MUST recreate the container via `docker-compose up -d` with the correct `IMAGE_TAG`. Verify: `docker inspect <name> --format '{{.Config.Image}}'`.

**Transient CI failures:** Bazel builds inside Docker can fail due to transient network errors (502 from GitHub). These are not code bugs — retry via GitHub Actions UI or re-push.

## Rule: Never Edit Files Directly on the Server

**🚨 CRITICAL: NEVER SSH into the server and edit files (sed, vi, echo >>, etc.) as a fix. ALL changes go through git branches.**

Workflow: fix on `main` → commit → cherry-pick to target branch via worktree → push → `git fetch && git reset --hard origin/<branch>` on the server → restart container.

**❌ BAD:** SSH to the server and `sed -i 's/200m/512m/' deployment/docker-compose.yml` (lost on next `git reset --hard`)
**✅ GOOD:** Fix in main → commit → cherry-pick to staging → push → pull on the server

## Rule: Never Restart or Recreate Prod Containers Without Explicit User Instruction

**🚨 CRITICAL: NEVER run `docker-compose up/restart`, `docker restart`, or any container lifecycle command on the production server unless the user explicitly asks you to.**

- "Graduate staging to prod" means updating the git branch (merge/fast-forward), NOT restarting containers.

**What to do instead:** Update git branch (merge/cherry-pick + push) → `git fetch && git reset --hard` on the server → **stop and ask the user** before touching any containers.

## Rule: Audit Container Topology Before ANY Docker Operation on Prod

**🚨 CRITICAL: Never run `docker-compose up/down/stop/rm`, `docker stop`, or `docker rm` on prod without first SSHing to the production server and running:**

```bash
docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -tlnp | grep 8000
```

Understand which container is *actually serving traffic* before touching anything. Legacy containers may depend on Docker DNS (`redis` hostname). Stopping ANY container on the shared network can break DNS for the serving container.

**Safe:** `docker pull`, `docker logs`, `docker inspect`
**Dangerous:** `docker-compose up -d`, `docker-compose down`, `docker stop/rm` on any container

## Rule: Deploy to Staging After Implementing User-Requested Changes

**Never deploy to prod directly.** All changes go through staging first, then graduate. The `prod` branch must only be updated when code is actually deployed to the production server.

**Workflow:**
1. Implement change on `main`, run tests, verify locally
2. Cherry-pick to `staging` via worktree: `cd ~/cursor_projects/visa_bulletin_staging && git cherry-pick <hash> && git push origin staging`
3. After CI builds: `docker pull ghcr.io/vyakunin/visa_bulletin:<tag>` then `IMAGE_TAG=<tag> docker-compose -f deployment/docker-compose.yml up -d web` on the staging server
4. Verify on staging

**Critical hotfix (prod-down only):** Cherry-pick to `prod` via worktree → push → deploy to the production server. Only for crashes/5xx.

**Do NOT deploy when:** user says "local only", change is docs-only, user only asked to plan/document.

## Rule: DEBUG Must Be False in Production — Never Derive DEBUG From Other Signals

**🚨 CRITICAL: `settings.DEBUG` must be an explicit env var (`DEBUG=True/False`), defaulting to False. Never derive it from SECRET_KEY, hostname, or any other signal.**

**Why:** If DEBUG silently flips on when an unrelated env var (e.g. `DJANGO_SECRET_KEY`) is missing, a minor config drift will leak URL conf, settings, env vars, and tracebacks to every public 404/500 visitor. This happened on 2026-04-19 — prod served the Django debug 404 page with the full URLconf exposed.

**Required invariants (enforced in `django_config/settings.py` + `debug_safety.py`):**
- `DEBUG` defaults to **False**; only set to True via explicit `DEBUG=True` env var.
- `django_config.debug_safety.assert_debug_is_safe(DEBUG, ALLOWED_HOSTS)` runs at import time and raises `ImproperlyConfigured` if `DEBUG=True` and any production hostname (`visa-bulletin.us`, `www.visa-bulletin.us`) is in `ALLOWED_HOSTS`. Container will refuse to boot.
- Prod `.env` must set `DEBUG=False` explicitly. Local dev `.env` sets `DEBUG=True`.
- Only one docker-compose file is canonical: `deployment/docker-compose.yml` (wires `env_file: ../.env`). Do not add a root-level `docker-compose.yml` without `env_file` — it launches containers with defaults and no secrets.

**Verifying in prod.** SSH to the production server and run:
```bash
docker exec vb_web python -c 'from django.conf import settings; print("DEBUG=", settings.DEBUG)'
# Expect: DEBUG= False
```

**Regression test:** `tests/test_debug_safety.py` — asserts `assert_debug_is_safe` raises on DEBUG+prod-hostname and is a no-op otherwise. Must stay green.

## Rule: Never Use Development Scripts on Production

**NEVER use `restart_server.sh` on the production server.** Production uses Gunicorn in Docker containers — manage via `docker-compose restart`.

**Development (local):** `./scripts/restart_server.sh`, `bazel run //:runserver`
**Production:** `docker-compose -f deployment/docker-compose.yml restart web`, `docker-compose up -d`

## GitHub Actions and Testing

**ALWAYS** test workflow changes with `act --dryrun` before pushing tags. Transient Bazel network failures (502 from GitHub) are not code bugs — retry the workflow.

**Rule:** Test workflow changes → `act -W .github/workflows/docker-build-push.yml -j build-and-push --dryrun` before tagging.
