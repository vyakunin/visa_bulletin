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

**The page itself is automatic.** `scripts/cron/refresh_bulletin.py` publishes the
following month's predictions the moment the current bulletin ingests, and
`upcoming_forecast_month()` rolls the sitemap + `/predictions/` links forward. So
publication is normally DONE weeks early and free. The work that is NOT automatic,
and that this cadence exists to force, is the **pre-drop half**:

1. **Indexing verify** — `gsc_inspect_url` the page. Not indexed → submit the
   sitemap AND re-render it (item 1 above; the sitemap is a static file, a code
   deploy does not refresh it).
2. **Internal links** — a "<Month> predictions are up" banner on the current
   month's page, plus the `/predictions/` hub and the homepage.
3. **Promotion** — the Reddit seed, owned by `visa_bulletin_platform` (Tier-3,
   needs an explicit go). Timed to land ~1 week before the drop.

**Estimate the drop from measured data, never from a rule of thumb.** Query prod:
`SELECT publication_date, released_on FROM bulletin ORDER BY publication_date DESC LIMIT 12;`
Recent cadence is the 13th–19th of the prior month (Jul→Jun 16, Jun→May 13,
May→Apr 16, Apr→Mar 17, Mar→Feb 19), but editions run late — Aug-2026 landed
~Jul 20. Re-estimate every cycle; the promo window moves with it.

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
