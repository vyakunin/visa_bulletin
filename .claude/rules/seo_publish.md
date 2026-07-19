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

## Origin
2026-06-23 — priority-date pSEO launch (`/priority-date/<eb>/<country>/`).
Vladimir: *"make sure all seo fluff is tight: sitemap, ping google, freshness.
Include this in project rules if not already."*
