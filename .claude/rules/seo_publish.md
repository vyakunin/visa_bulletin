# SEO publish checklist — new/changed public pages

When you ship a **new public page type** or change content that affects SEO (new
pSEO pages, title/meta/schema changes, new content sections), complete ALL of
these in the **same task** — don't leave "SEO fluff" half-wired. This is the
post-launch counterpart to `docs/seo/SEO_OPTIMIZATION.md`.

1. **Sitemap inclusion.** New URLs MUST be emitted by `build_sitemap_xml()` in
   `webapp/views/seo/sitemaps.py` — mirror the view's slug sets there.

   ⚠️ **Since 2026-07-19 the sitemap is PRE-RENDERED to a static file** that nginx
   serves off disk (`scripts/seo/render_sitemap.py` → `staticfiles/sitemap.xml`;
   the Django view is only a fallback for when the file is absent). **Deploying
   the code change is therefore NOT enough** — the live sitemap keeps serving the
   old URL set until the renderer runs. Re-render explicitly as part of the
   launch, don't wait for the 02:40 cron:
   ```bash
   ssh homeserver "docker exec -w /app vb_web python3 -m scripts.seo.render_sitemap"
   ```
   The renderer refuses to publish a render that loses >10% of the on-disk URLs,
   so if a launch legitimately *removes* a large surface, it will (correctly)
   refuse — read the reason, then re-run with `--force`.

   Verify on prod: `curl -s https://visa-bulletin.us/sitemap.xml | grep <new-path>`.
   Confirm `robots.txt` still advertises the sitemap.

2. **Freshness (`<lastmod>`).** Every URL carries a **truthful** `lastmod`, never
   future-dated — Google discounts a future lastmod and, seeing it across many
   URLs, stops trusting the sitemap's lastmod entirely. Always go through
   `_lastmod_capped(<real-change-date>, today)`: bulletin fetch date for
   bulletin-data pages (`_get_latest_bulletin_fetched_at`), `cluster.updated_at`
   for profiles, `published_date` for posts. Never a hardcoded/arbitrary date.

3. **Edge cache purge.** After a content/template deploy, purge Cloudflare so the
   CDN re-fetches fresh HTML (cached pages carry a 1h max-age and would otherwise
   serve stale at the edge):
   ```bash
   CLOUDFLARE_API_TOKEN="$(cat ~/tokens/cloudflare_api_token_cache_purge)" \
     python3 ~/cursor_projects/visa_bulletin_platform/hosting/scripts/cf_cache_purge.py
   ```
   `promote.sh` flushes the Redis page cache + reminds about this; the **edge**
   purge is a separate step you still run.

4. **Submit / "ping" Google.** Submit the sitemap via GSC so Google re-crawls the
   new URLs — Google **deprecated the anonymous sitemap-ping endpoint in 2023**, so
   GSC submit is the supported path (don't hit `google.com/ping?sitemap=`):
   `mcp__gsc__gsc_submit_sitemap(site_url="sc-domain:visa-bulletin.us",
   feedpath="https://visa-bulletin.us/sitemap.xml")`. Verify with
   `gsc_list_sitemaps` — expect `errors: 0` and a recent `lastDownloaded`. (Google
   re-fetches submitted sitemaps on its own cadence; re-submitting on every deploy
   isn't required, but do it on a new-page launch to nudge the crawl.)

5. **Structured data.** High-intent Q&A pages emit valid **FAQPage** JSON-LD (rich
   result). Confirm the `"@type": "FAQPage"` block renders on prod.

6. **Internal-link mesh.** New pages are reachable from existing pages (sibling
   links + a link from the relevant dashboard) — not orphaned. Add inbound links
   from the highest-traffic related page.

7. **Track + measure.** Record the launch in `docs/seo/SEO_OPTIMIZATION.md` + the
   Notion ticket, and GSC-measure clicks/impressions/position after Google indexes
   (days→weeks). See `~/.claude/rules/revenue_growth_state_docs.md`.

## Prediction pages ship on a PRE-drop cadence — live, indexed AND promoted ~1 week BEFORE the bulletin drops

The next-month predictions page (`/predictions/<month>-<year>/`) is the site's
biggest recurring traffic event, and its demand curve **peaks in the days before
the State Department publishes**, not after. So the page must already be live,
indexed and promoted **~1 week ahead of the expected drop** — Google needs that
lead time to rank it before the anticipation wave arrives. Publishing at the drop
moment is too late: the wave finds a page Google has not yet learned to trust.

**The page AND its internal links are automatic.** `scripts/cron/refresh_bulletin.py`
publishes the following month's predictions the moment the current bulletin
ingests; `upcoming_forecast_month()` rolls the sitemap + `/predictions/` links
forward; and since `271983d` the archive pages and the homepage link forward to
the upcoming forecast off that same helper — a prominent banner on the newest
archive month, a compact inline link on older ones, one link on the homepage.
**Do not hand-add a "<Month> predictions are up" banner: it is already there.**
Verify it rendered (`curl` the current month's page and the homepage, grep for
`href="/predictions/<month>-<year>/"` — expect 2 and 1); a MISSING link is a bug
in that mesh, not a page to write. Pinned by
`tests/test_stable_prediction_url.py::TestUpcomingForecastInboundLinks`.

So the work that is NOT automatic, and that this cadence exists to force:

1. **Indexing verify** — `gsc_inspect_url` the page. Not indexed → submit the
   sitemap AND re-render it (item 1 above; the sitemap is a static file, a code
   deploy does not refresh it).
2. **Promotion** — the Reddit seed, owned by `visa_bulletin_platform` (Tier-3,
   needs an explicit go). Timed to land ~1 week before the drop.

**A sitemap entry is a hint; an inbound link from an indexed page is the discovery
path.** On 2026-08-03 `/predictions/september-2026/` was live, self-canonical, and
present in a sitemap Google had downloaded that morning with 0 errors — and
`gsc_inspect_url` still said *"URL is unknown to Google"*: never crawled, ~10 days
before the drop. Nothing linked to it. The one forward link on the already-indexed
August archive page read "See the live forecast for the next bulletin" and pointed
at the **homepage**. So when a page is not indexed, check the inbound links before
touching the sitemap — and never read "it's in the sitemap" as "Google will find
it".

**Read the band off the cadence ticket first; recompute only to CHECK it.** The
measured band lives on ticket `39962b8d409f81f1b900e2b2f247006d`, which is the
authority for the cycle. Three consecutive runs (2026-09-01, the 09-02 digest, the
09-02 readiness inject) each re-derived a band from `bulletin` without reading it
and each got a different answer — that is a class, not a slip. If your recomputed
number disagrees with the ticket, say so ON the ticket rather than quietly
preferring your own.

The check, against prod:
`SELECT publication_date, fetched_at, released_on FROM bulletin ORDER BY publication_date DESC LIMIT 12;`
Recent editions release on the 12th–21st of the prior month and the spread is
real — the Sep-2026 edition landed on day 21, the latest in the series, while the
trailing-12 median sits near day 16. Re-estimate every cycle; the promo window
moves with it.

**`released_on` can be NULL — do not substitute `fetched_at` for it, and know
that two code paths already do.** Both the Aug-2026 and Sep-2026 rows have no
`released_on` (the minipc bridge records none). `fetched_at` is when WE ingested,
not when State published, and the bias is always LATE because a bridge can only
fetch after a release: Aug-2026 reads Jul 20 against an actual ~Jul 15-16
(GoatCounter daily pageviews 12.3k / 15.4k / 14.7k on Jul 15/16/17 vs a ~2k
baseline), and Sep-2026 reads Aug 22 against an actual Aug 21 22:00-22:30 ET.

The substitution is not just a reading habit — it is a live defect, tracked as
`3cf62b8d409f81fbaf0be401b573270b`:
`lib/business/bulletin/release_schedule.py:_record_from_bulletin` falls back to
`fetched_at.date()`, so the public `/when-is-the-next-visa-bulletin/` estimator
already uses it; and `scripts/bulletin/backfill_release_dates.py` would WRITE it
(dry-run 2026-09-02 resolved both rows from source `live`, Wayback contributing
nothing). **Do not run that backfill without `--dry-run` against recent rows** —
leaving a row NULL is strictly better than writing a known-late value, which is
the script's own stated philosophy. When `released_on` is NULL, bound the release
from the bridge log's discover-absent/discover-present bracket, or from the
GoatCounter daily spike.

**Keep the cadence armed durably, not in a session.** Each cycle schedules the
next one via the `scheduled_actions` MCP: a `visa_bulletin` readiness inject ~10
days before the expected drop, and a `visa_bulletin_platform` promo inject ~2 days
after it. A cycle that ends without the next one queued is the failure mode — the
work is invisible until the wave has already passed.

### The URL-scheme trap — a numeric-slug 404 is NOT a missing page

The live page is the **word-month slug**: `/predictions/september-2026/`. The
numeric `/predictions/2026-9/` **404s by design** until an official bulletin exists
for that month; `/predictions/2026-8/` resolves only because August is published,
and `/predictions/august-2026/` 301s to it. So check the word-month slug before
concluding a page is missing — the numeric variant returning 404 for a
not-yet-official month is correct behavior. (Cost a false "page not published"
finding in the 2026-07-29 digest.)

## Origin
2026-07-29 — Vladimir, on a digest that flagged the September page as unpublished:
*"we discussed before we want this page to be fresh for pre-drop cycle so google
likes it, so it has to be published and promoted ~1 week before expected drop."*
The page was in fact live (checked at the numeric slug, which 404s by design); the
real gap was that nothing durable was scheduled to get it indexed and promoted
before the drop. Cadence + the URL trap recorded here, injects queued, ticket
`39962b8d409f81f1b900e2b2f247006d` reframed as the recurring cadence owner.

2026-06-23 — priority-date pSEO launch (`/priority-date/<eb>/<country>/`).
Vladimir: *"make sure all seo fluff is tight: sitemap, ping google, freshness.
Include this in project rules if not already."*
