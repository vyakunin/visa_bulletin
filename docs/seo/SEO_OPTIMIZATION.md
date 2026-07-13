# SEO Optimization — Current State

Site: `https://visa-bulletin.us`

## GSC/GA4 posture (measured 2026-07-04)

- **Profile-surface impressions halved since ~06-19/26** (June-24 Google spam
  update targeting scaled-content abuse = prime suspect): `/job-title/` 2,936 →
  1,536 impr/day, `/employer/` 3,360 → 1,533 impr/day (06-12..25 avg vs
  06-26..07-01), positions stable (~8 / ~6.5-7) — while site-wide fell only
  −16% (31.8k → 26.8k impr/day ex bulletin-spike). Diagnosis ticket open
  (re-check 07-11); quality-gates any new pSEO cluster (I-129 Lever 2).
- **`/salaries` bounce improved** after the 06-26 onward-nav rail + occupation
  pSEO: 65.1% → 57.0% (engaged 34.9% → 43.0%, avg 87.8s → 158.5s; N=193 sess,
  06-27..07-03 vs 05-29..06-25). Confirm on bigger N ~07-14.
- **`/employment-based/india`**: pos 36.6 (06-26 diagnosis) → 21.1 (06-21..27) →
  17.8 (06-28..07-04); the 07-03 lever ship (H1 dedupe + H2s + link-mesh) is
  too fresh to attribute — final re-measure 07-10.
- Employer meta-desc CTR lever live since 07-03 (snippet re-crawl pending);
  surface CTR series: 1.48% (06-12..25) → 1.66% (06-28..07-03), both pre-fix
  serving. Named-page re-measure ~07-14.
- Sitemap-freshness lever: measured, no isolated lift extractable (the profile
  decline swamps it); correct hygiene, stays as-is. Ticket closed 07-04.
- **Engagement / "long click" proxy (GA4; data starts ~06-01, no earlier
  baseline).** Google's dwell signal isn't observable — closest proxies are GA4
  engaged sessions (>10s / 2+ pages / conversion), engagement rate, avg session
  duration. Organic-search weekly series: W23 2,698 sess / 74.9% engaged / 163s
  → W24 4,544 / 69.0% / 138s → W25 4,826 / 70.0% / 134s → W26 2,906 / 70.2% /
  138s → W27(partial) 2,125 / 71.8% / 142s — flat-to-slightly-up THROUGH the
  profile-impression halving, i.e. no engagement collapse accompanies the
  decline. Per-surface organic landings, 06-06..07-03: `/` 9,275 sess / 74.9% /
  145s; `/salaries` 600 / 81.3% / 193s (rail working); `/employer/*` 1,368 /
  68.4% / 125s; `/job-title/*` 416 / 59.1% / 100s — job-title profiles are the
  weakest engagement surface, consistent with the spam-update thin-pSEO
  suspicion. **In the daily checkup since 2026-07-04** (`mcp/daily_checkup_server.py`
  `_section_ga4_engagement`: this-7d vs prior-7d per surface, yellow on ≥10pt
  WoW drop at N≥50). GA4 property 539743892.
- **Profile-engagement dig (2026-07-04, GA4 organic landings).** Why job-title
  interactions are low/falling: (a) **trend is real and coincides with the
  06-25 PERM re-cluster + 404 wave** — weekly engaged rate 61.5% (W23, 143
  sess) → 62.9% (140) → 64.2% (123) → 56.3% (80) → 46.5% (43, partial wk);
  employer only drifts 72.8% → 65.4% over the same 5 wks. (b) **Mobile is the
  weak half**: job-title mobile 213 sess / 49.8% engaged / 73s vs desktop 199 /
  70.4% / 131s (28d) — table-heavy profile layout on phones. (c) **Shallow
  consumption**: only ~45% of job-title / ~43% of employer page users fire the
  90%-scroll event; 1.5–2.2 pageviews/session. (d) **Thin-page composition**:
  hyper-specific 1–3-filing titles land a searcher on a page with nothing to
  do — the ≥100-filing gate argument. Telemetry limits: GA4 enhanced
  measurement only (page_view / scroll@90% / outbound click / form) — NO
  internal-link or element click events, no scroll granularity, no session
  replay; on-page behavior beyond scroll+exit is invisible today (ticket
  2026-07-04 to add profile-interaction events).

## Profile-surface remediation (2026-07-04) — 404 wave, thin pages, mobile, telemetry

Four fixes shipped together off the 2026-07-04 engagement dig:

1. **Stale-slug 404 wave (~3.6k hits/day post 06-25 re-cluster) → 301s.** Two
   classes: (a) slash-less URLs 404ed because `MIDDLEWARE` had no
   `CommonMiddleware`, so `APPEND_SLASH` never ran (`/job-title/lawyers` 404
   while `/job-title/lawyers/` 200) — fixed in `django_config/settings.py`;
   (b) re-clustered slugs — `lib/business/salary/slug_redirects.py` resolves
   them via an indexed ladder (suffix-strip of requisition/uniqueness tokens →
   exact `title_normalized` / `name_normalized` matches through the same
   normalizers that populate those columns → legacy substring scan last),
   with the outcome (incl. no-match) cached 24h because bots bypass the page
   cache. Both profile views 301 to the resolved canonical slug.
2. **Thin-page gate on `/job-title/*`** — `INDEXABLE_MIN_FILINGS = 100`
   (`lib/business/salary/job_title_stats.py`): profiles below it render with
   `noindex, follow` and are excluded from the sitemap (was `>= 10`). Kills
   the requisition-id 1–3-filing pages Google landed searchers on — the
   scaled-content-abuse suspect for the June impression halving. Reversible
   (lift the constant) if the 07-11 re-measure exonerates thin pages.
3. **Mobile first-paint + tables** — Plotly was a **render-blocking `<head>`
   script** on both profile templates (job-title even shipped the full
   unversioned `plotly-latest`, ~3.5 MB); both now load
   `plotly-basic-2.32.0.min.js` with `defer` (init already polls via
   `ensurePlotlyLoaded`). Salary-Range / Min / Max table columns are hidden
   below `md` (`d-none d-md-table-cell`) so profile tables fit a phone without
   sideways scroll. Suspects behind mobile 49.8% engaged vs desktop 70.4%.
4. **Profile-interaction telemetry** —
   `webapp/templates/webapp/includes/profile_interaction_events.html`
   (included with `surface="jt"` / `"emp"`): GoatCounter events
   `ev/profile/<surface>/<target>` (+ GA4 `profile_interaction` when gtag is
   present) for internal-nav clicks by target group (employer-link, role-link,
   pair-link, sponsors-cta, salaries-link), table sorting, filter changes, and
   search-box use. Closes the "what do non-engaging landers do" blind spot.

Tests: `tests/test_profile_slug_redirects.py`. Measure: 404 rate in nginx +
GSC not-found count should fall within days; GC Events tab + GA4
`profile_interaction` populate as traffic lands; job-title engaged-rate WoW in
the daily checkup (`_section_ga4_engagement`) is the outcome metric.

**SHIPPED TO PROD 2026-07-04** (zero-downtime cutover, image `staging-36dd234`;
all four fixes verified live: append-slash 301, ladder 301, thin-page
`noindex`, sitemap 1,265 job-title URLs, telemetry include, plotly-basic +
defer). CF edge purged; sitemap resubmitted to GSC (errors 0, 6,579 URLs).

5. **Slug reclaim (follow-up, same day).** The re-cluster left **513 of 1,265
   indexable job-title clusters with stale slugs** (`slug !=
   slugify(canonical_title)`) — flagship pages on requisition-ID or typo'd
   URLs: the 117k-filing Software Engineer cluster sat on
   `software-engineer-161559609` while `software-engineer` was unclaimed;
   `market-researh-analyst`, `mechanial-engineers`, etc. With the 301 ladder
   live, renaming became safe, so
   `scripts/salary/populate_job_title_slugs.py --refresh-all --min-filings 100
   --skip-collisions` (new flags, commit `6b9a74a`: indexable-only scope,
   biggest-first ordering, never rename INTO a counter-suffixed slug,
   multi-pass to claim freed slugs) reclaimed **454 clean slugs** on both
   staging and prod DBs (59 kept — genuine collisions). Old slugs 301 to the
   reclaimed canonical via the ladder; Redis flushed on both stacks, CF
   purged, sitemap resubmitted. Rule of thumb going forward: after ANY
   job-title re-cluster, run this refresh (indexable scope) so canonical URLs
   track canonical titles instead of accreting suffixes.

6. **Thin-page rescue — relevant, not just noindexed (same day, per Vladimir:
   "aim to keep them on site; if not possible — be helpful and relevant").**
   The Similar Roles section matched on the title's FIRST WORD, so "Senior
   Vice President, Legal & Compliance" recommended Senior Software Engineer —
   qualifier noise, and on thin pages it was the only escape hatch. Now
   (`lib/business/salary/similar_titles.py`): suggestions are the ~1.3k
   **indexable** clusters ranked by shared content tokens
   (seniority/level qualifiers stripped, requisition junk tokenizes away).
   Thin pages additionally render a **broader-role CTA banner** — the best
   indexable cluster whose content tokens are a strict subset of the page's
   ("Software Engineer" for "Software Engineer Kbgfjg353961"): "Only N
   filings match this exact title — see the full X profile (M filings)".
   Fallback when no subset exists: a `/salaries/?q=<distinctive-token>`
   search link. CTA clicks tracked as `ev/profile/jt/broader-role-cta`;
   compare against thin-page exits at the 07-11 re-measure.

## Sitemap & robots.txt

Both generated dynamically by `webapp/views/seo/sitemaps.py`.

**robots.txt** (`/robots.txt`):
```
User-agent: *
Allow: /
Disallow: /api/
Sitemap: https://visa-bulletin.us/sitemap.xml
```

**Sitemap** (`/sitemap.xml`) — single `<urlset>`, ~9,500+ URLs:

| Section | Count | Filter criteria | `lastmod` |
|---------|-------|----------------|-----------|
| Static pages | 12 | the 8 English + `/es/`, `/es/faq/`, `/es/predictions/`, `/es/priority-date/` (Spanish cluster) | Latest bulletin date |
| Category/country landings | ~12 | `/employment-based/`, `/family-sponsored/` × countries | Latest bulletin date |
| Priority-date landings | 12 | `/priority-date/{eb1,eb2,eb3}/{india,china,philippines,mexico}/` | Latest bulletin date |
| Priority-date landings (Spanish) | 12 | `/es/priority-date/{eb1,eb2,eb3}/{india,china,philippines,mexico}/` | Latest bulletin date |
| Priority-date hub + rollups | 4 | `/priority-date/` + `/priority-date/{eb1,eb2,eb3}/` (country-agnostic) | Latest bulletin `fetched_at` |
| Employer profiles | ~3,900 | `EmployerCluster` with slug, `total_lca_count >= 5`, top 10k | Latest bulletin date |
| Job title profiles | ~1,265 | `JobTitleCluster` with slug, `total_filings >= INDEXABLE_MIN_FILINGS` (100 — the thin-page gate; was `>= 10` / ~5,200 until 2026-07-04) | Latest bulletin date |
| Blog posts | all published | `BlogPost.is_published=True` | Per-post `published_date` |
| Prediction archive | all bulletin months | One URL per `Bulletin` month | Per-bulletin `publication_date` |
| Month forecast | 1 (rolling) | The upcoming bulletin month (`latest + 1`) | Latest bulletin `fetched_at` |

All static/profile URLs use `changefreq: monthly`, `priority: 0.8`. Blog posts use `changefreq: yearly`, `priority: 0.6`. Prediction archive pages use `changefreq: yearly`, `priority: 0.5`. The month-forecast page uses `changefreq: weekly`, `priority: 0.7` (refreshes as the forecast updates).

**Search engine ping**: The refresh pipeline pings Google and Bing after clearing the sitemap cache (`step_ping_search_engines` in `scripts/cron/refresh/steps.py`). Non-fatal on failure.

## Priority-date landing pages (`/priority-date/<eb_class>/<country>/`)

Per-EB-class × per-country focused landing pages targeting high-intent queries
("eb2 india priority date", "eb3 china priority date" — real GSC demand at pos
~7-8). EB-1/2/3 × India/China/Philippines/Mexico (12 pages). Each shows the
current Final Action + Dates-for-Filing cutoffs, the latest month-over-month
movement, a 6-month history table, an FAQ (FAQPage schema), and links into the
full per-country dashboard + salary data + sibling pages (internal-link mesh).

- View: `webapp/views/bulletin/priority_date_landing.py` (reuses the normalized
  `get_aggregated_visa_class_data` series; headline status from the latest
  bulletin row so C/U vs a date is accurate).
- **Deliberately cheap to render** — no live VQS solver (predictions are linked,
  not embedded), so the page stays fast + cacheable and avoids the per-country
  dashboard's filter-combo query cost.
- Unknown class/country or a combo with no cutoff data → 404 (no thin pages).
- Test: `tests/test_priority_date_landing.py`.
- **Status (2026-06-23):** core shipped to `main` + sitemap, suite green.
  Pending: staging deploy + real-data render verify, internal links FROM the
  main dashboards, then GSC measurement. Possible v2: embed the prediction,
  add EB-4/EB-5 + ALL, expand country set.

### Featured-snippet harvest (priority-date hub / rollups / landings)

The priority-date **hub** (`/priority-date/`), per-EB-class **rollups**
(`/priority-date/<eb>/`), and per-country **landings** (`/priority-date/<eb>/<country>/`)
— plus the Spanish landings — are optimized for position-0 (paragraph featured
snippet) capture on the priority-date question cluster, where they already rank
in striking distance: "eb2 priority date" pos ~3.5, "green card priority date"
pos ~4.2, "eb3 priority date" pos ~4.6, "priority date" pos ~6.6,
"eb2 priority date india" pos ~7.5.

- **Lead-answer paragraph** directly under the H1 (a `.lead` `<p>`, ~50 words)
  that *directly answers the head query* — the snippet bait Google lifts:
  - Hub: a definitional answer for "what is a (green card) priority date".
  - Rollup: data-driven from the country rows (`_rollup_lead_answer`), so it
    never claims a cutoff the bulletin doesn't show.
  - Landing: names the current Final Action + Dates-for-Filing cutoffs
    (`_lead_answer` / `_lead_answer_es`).
- **FAQ questions render as real `<h3>` headings** (were `<div class="fw-semibold">`)
  with the answer as a `<p>` immediately below — improves paragraph- and
  People-Also-Ask snippet harvest and heading hierarchy/a11y. FAQPage JSON-LD
  unchanged (already present).
- Views: `priority_date_rollup.py` (`_HUB_LEAD`, `_rollup_lead_answer`),
  `priority_date_landing.py` (`_lead_answer`, `_lead_answer_es`). Tests assert
  the lead paragraph + `<h3>` in `test_priority_date_rollup.py`,
  `test_priority_date_landing.py`, `test_spanish_cluster.py`.
- **Status (2026-06-25):** code on `main`, suite green. Pending: staging diff +
  prod promote (Path-1) + CF purge + GSC resubmit, then GSC-measure
  position-0 / CTR uplift on the priority-date cluster over ~2-3 wks.

## Spanish (/es/) cluster

Spanish-language sibling pages converting real Spanish search demand ("boletín de
visas", "fecha de prioridad eb2 india", "predicciones boletín de visas",
"preguntas frecuentes boletín de visas"). Static-sibling pattern (hardcoded
Spanish copy, no Django i18n middleware) — the live data widgets (dashboard,
salaries, prediction archive) stay English and the Spanish pages link into them
with a note that the visual interface (dates/categories/countries) is navigable
without advanced English.

- **`/es/`** — landing explainer (pre-existing; now links the cluster).
- **`/es/priority-date/<eb>/<country>/`** (12) — Spanish mirror of the English
  per-EB×country landings. Reuses the EN data path (`_latest_status` / `_series` /
  `_chart_json` in `priority_date_landing.py`); only the rendered chrome/copy is
  localized (`spanish_priority_date_landing_view` + Spanish `_trend_es` / `_faq_es`
  / date formatting). FAQPage JSON-LD. Same 404 gate as EN (no thin pages).
- **`/es/priority-date/`** — Spanish hub indexing the 12 landings.
- **`/es/faq/`** — Spanish FAQ (8 Q&A) with FAQPage JSON-LD.
- **`/es/predictions/`** — Spanish explainer of the Bulletin Forecast model,
  linking to the English prediction archive.
- **Views:** `webapp/views/static/spanish.py` (hub/faq/predictions) +
  `spanish_priority_date_landing_view` in `priority_date_landing.py`.
- **hreflang:** bidirectional `es`↔`en` declared on every pair (ES landing↔EN
  landing, ES FAQ↔EN FAQ `/faq/`, ES hub↔EN hub `/priority-date/`, ES
  predictions↔EN `/predictions/`); `x-default` → English. The base template only
  emits hreflang on `/`; each page template overrides the `hreflang` block.
- **Sitemap:** all `/es/` URLs emitted (4 static + 12 landings) with truthful
  `lastmod`. Test: `tests/test_spanish_cluster.py`.
- **Status (2026-06-24):** shipped to `main`, suite green. Pending: staging
  deploy + real-data render verify, GSC measurement after indexing. Possible v2:
  Spanish per-country dashboard data, expand to other high-demand Spanish queries.

## Priority-date HUB + per-EB-class rollups (`/priority-date/` + `/priority-date/<eb_class>/`)

Country-AGNOSTIC priority-date pages sitting above the per-country landings.
**Why (GSC, 2026-06):** the generic query "eb2 priority date" (no country) pulled
~1.4k impr/month at pos ~5 onto the `/salaries/` and `/employers/` list pages,
which answer it terribly (**0% CTR**) — nothing on the site targeted the
no-country query. Combined, those two list pages carried ~10k impr/month of
priority-date-intent queries at ~0% CTR (the real cause of their <0.5% aggregate
CTR — on their OWN intent they're healthy: `/salaries/` salary queries ≈ 3.55%).

- **Hub** `/priority-date/`: index of all EB classes × countries; targets
  "priority date" / "visa bulletin priority date". Gives `/salaries/` +
  `/employers/` a clean link target to steer priority-date intent away.
- **Rollup** `/priority-date/<eb_class>/` (eb1/eb2/eb3): ONE EB class across all
  five chargeability areas (India/China/Mexico/Philippines/All-Others) in one
  table; targets the generic "ebN priority date".
- View: `webapp/views/bulletin/priority_date_rollup.py` (reuses the landing
  page's cheap helpers — no live VQS solver). FAQPage schema on both. Unknown EB
  class or no cutoff data → 404 (no thin page). Distinct URL segment counts from
  the per-country landing route, so no shadowing.
- Cross-links added FROM `/salaries/` + `/employers/` → the hub (intent steering
  + reassignment signal + no dead-end).
- Test: `tests/test_priority_date_rollup.py`.
- **Status (2026-06-23):** shipped to `main` + sitemap, suite green. Pending:
  staging deploy + real-data render verify, then GSC measurement of whether the
  generic PD queries reassign off `/salaries/`+`/employers/` onto these pages
  (the CTR-recovery thesis).

## Per-month forecast landing pages (`/predictions/<month>-<year>/`)

Evergreen forecast page for the **upcoming** bulletin month, targeting the
recurring high-intent query "visa bulletin {month} {year} predictions" (the
predictions cluster we already rank top-3 for, per `visa_bulletin_platform/docs/SEO.md`).
e.g. `/predictions/october-2026/`. Distinct from the prediction *archive*
(`/predictions/<category>/<year>-<month>/`), which is the backtest accuracy view
and 404s for any month without a published bulletin — the forecast page covers
exactly that gap (the not-yet-published month).

- View: `webapp/views/bulletin/prediction_month_forecast.py`. URL: a tight
  `re_path` (`^predictions/(?P<slug>[a-z]+-20\d{2})/$`) registered **before**
  `predictions/<str:category>/` so it never shadows the category/legacy routes.
- Renders the model's predicted Final Action / Filing cutoffs across all EB + FS
  categories × countries, headline cards for the oversubscribed India/China EB-2/3
  series (with movement-probability badges), an FAQ (FAQPage schema), and links
  into the live dashboards + per-country priority-date pages + methodology.
- **Deliberately cheap to render** — NEVER calls the live VQS solver (the 23s path
  removed from FS pages in `4524f04`). Reads only **stored** `PredictedCutoff`
  rows, which the hourly refresh publishes for `latest_bulletin_month + 1`
  (`_publish_predictions_for_latest_bulletin`). `@cache_page_skip_bots`; the cron's
  `cache.clear()` on each new ingest keeps it fresh.
- Once the target month's actual bulletin lands → **301 → the accuracy archive**
  (no duplicate page for the same month). A future month with no stored forecast,
  or an invalid month slug → 404 (no thin page, no solver).
- Sitemap emits ONE rolling URL (`upcoming_forecast_month()`), auto-advancing as
  bulletins land. Inbound links FROM `/predictions/` (archive) and
  `/when-is-the-next-visa-bulletin/`.
- Test: `tests/test_prediction_month_forecast.py`.
- **Status (2026-07-13, full-page audit):** live and the site's #2 traffic surface —
  `/predictions/august-2026/` did 8,827 GSC clicks / 74,805 impr / 11.8% CTR /
  pos 4.8 and 10.5k GoatCounter views over 06-13..07-13 (site total 86.4k). Top
  queries are actual-bulletin intent ("visa bulletin august 2026" 2,446 clicks /
  13,284 impr pos 3.0) ahead of prediction intent ("… predictions" 1,235 clicks,
  pos 2.2); Spanish queries ~223 clicks/30d land here with no ES page (tracked).
  Audit outcome: model side is at its documented 1m ceiling (persistence + T3
  demand gate, calibrated 80% CIs); page-side follow-ups ticketed in Notion —
  CF-edge purge missing from the bulletin-ingest path (stale page up to 1h at the
  drop), post-drop archive title lacks "Visa Bulletin" (301-inherited query
  equity), grid CIs hover-only (invisible on mobile), ES month pages + hreflang,
  VQS ensemble re-tune.

## Top-H-1B-sponsors-per-role pages (`/h1b-sponsors/<job-title-slug>/`)

Dedicated ranked leaderboard answering the high-intent query the existing pages
don't: **"top H-1B sponsors for {role}" / "which companies sponsor H-1B for
{role}" / "companies that sponsor H-1B for {title}"**. The `/job-title/<slug>/`
profile is salary-stats-first and `/salaries/by-state/<code>/` is state-first;
neither is a clean ranked "companies that sponsor H-1B for X" answer — so this is
a new page, not a thin duplicate.

- **Content:** headline stats (H-1B filings, # sponsoring employers, median
  H-1B wage + p25–p75); a ranked top-25 employer table (employer → `/employer/`
  link, H-1B filing count, mean wage); a top-states block; an FAQ (FAQPage
  schema). Ranked by certified H-1B LCA filing count from DOL data.
- **View:** `webapp/views/salary/h1b_sponsors.py`. **Deliberately cheap** — a
  handful of indexed, single-cluster aggregates (`visa_program`, `wage_annual`,
  `job_title_entity`/`employer` FKs); no live VQS solver, no full scan.
  `@cache_page_skip_bots`.
- **No thin pages:** a role 404s unless it has **≥50 H-1B filings AND ≥8 distinct
  sponsoring employers**. This gate is shared (`lib/business/salary/h1b_sponsors.py`)
  with the sitemap emit-set, so the sitemap NEVER lists a page that 404s.
- **Sitemap:** emits the qualifying slug set (cached 24h via the shared helper —
  the gate is a GROUP BY over the H-1B corpus, too heavy per bot fetch; the
  refresh pipeline's `cache.clear()` refreshes it). `changefreq monthly`,
  `priority 0.6`, lastmod = latest bulletin `fetched_at`. Capped to the top 5,000
  roles by H-1B volume.
- **Internal-link mesh:** inbound from each role's `/job-title/<slug>/` profile
  (a CTA in the "Top Employers" card, rendered only when the role qualifies so we
  never link to a 404) + the sitemap; outbound to the profile, salary search, and
  each `/employer/<slug>/`.
- **Test:** `tests/test_h1b_sponsors_landing.py` (qualifying renders + FAQPage +
  self-canonical; thin role 404; PERM-heavy role 404 = H-1B-only; sitemap lists
  qualifying only).
- **Status (2026-06-24):** **LIVE on prod** (`prod 19fb476`, img `staging-718bc17`),
  189 pages in the prod sitemap, CF purged, GSC re-submitted, suite green. GSC
  measurement pending (days→weeks to index).
  **Follow-up (v2):** denormalize per-cluster H-1B filing/sponsor counts onto
  `JobTitleCluster` in the stats refresh, which lets the sitemap drop the heavy
  cached aggregate and enables a related-role sponsor-page cross-link mesh.

## Top-H-1B-sponsors-per-state pages (`/h1b-sponsors/in/<state-code>/`)

The state variant of the H-1B-sponsors pillar, answering the distinct query the
existing pages don't: **"top H-1B sponsors in {state}" / "which companies sponsor
H-1B in {state}" / "highest-paying H-1B employers in {state}"**. A **NEW
dedicated URL**, deliberately NOT a re-angle of the live `/salaries/by-state/`
page — that page's state-overview intent (ranks employers by filing volume across
H-1B *and* PERM) is left untouched, so there is **zero de-rank risk** to a
working page. Same posture as the role page being a new URL rather than re-angling
`/job-title/`.

- **Content:** headline stats (H-1B filings in-state, # sponsoring employers,
  median H-1B wage + p25–p75); **two** ranked tables — (1) **top sponsors by H-1B
  filing volume** (the robust "which companies sponsor H-1B in {state}" answer),
  (2) **highest-paying H-1B employers** ranked by mean wage with a **≥5-filing
  floor** so a single outlier filing can't top the chart (the "highest-paying"
  query, answered without noise); a top-H-1B-roles block; an FAQ (FAQPage schema).
- **View:** `webapp/views/salary/h1b_sponsors.py:h1b_sponsors_state_view`. Cheap
  single-state indexed aggregates (`visa_program`, `wage_annual`, `worksite_state`,
  FKs); no live solver, no full scan. `@cache_page_skip_bots`.
- **No thin pages:** a state 404s unless **≥50 H-1B filings AND ≥8 distinct
  sponsors**, the same shared gate (`lib/business/salary/h1b_sponsors.py`) as the
  cached sitemap emit-set — and the sitemap set is intersected with the canonical
  `US_STATES` list, so it NEVER emits an invalid or 404 URL (48 of 51 qualify).
- **Internal-link mesh (both directions):** inbound from each `/salaries/by-state/`
  page (a gated CTA) + the sitemap; the role page's top-states block links to the
  state page (gated); the state page's top-roles block links to the role page
  (gated, falling back to the `/job-title/` profile for non-qualifying roles).
- **Test:** `tests/test_h1b_sponsors_state_landing.py` (qualifying renders both
  tables + FAQPage + self-canonical; thin/PERM-heavy/unknown 404; pay floor
  honored; sitemap lists qualifying states only; by-state CTA gated).
- **Status (2026-06-24):** **LIVE on prod** (`prod 19fb476`, img `staging-0e739bd`),
  48 state pages in the prod sitemap, CF purged, GSC re-submitted, suite 74 green.
  GSC measurement pending.

## Per-(employer × role) H-1B salary pages (`/h1b-salary/<employer>/<role>/`)

The third pSEO pillar from LCA data, answering the (employer × role) query the
employer-wide and role-wide profiles don't: **"{role} salary at {employer}" /
"does {employer} sponsor H-1B for {role}" / "{employer} {role} H-1B salary"**.
The `/employer/<slug>/` profile is employer-wide (all roles) and `/job-title/
<slug>/` is role-wide (all employers); neither is the specific (employer × role)
salary answer — so this is a new page, not a duplicate.

- **Content:** salary distribution (p10–p90), median + p25–p75 + wage range, an
  H-1B-filings-by-year trend, top worksite states, and the non-duplicative insight
  — how the pair's median compares to the role's **market-wide** median (X%
  above/below). FAQPage schema, self-canonical, outbound links to the employer,
  role, and role-sponsor pages.
- **View:** `webapp/views/salary/h1b_salary_pair.py`. Cheap single-pair indexed
  aggregates (`visa_program`, `wage_annual`, employer/job-title FKs); no live
  solver, no full scan. `@cache_page_skip_bots`.
- **No thin pages:** a pair 404s unless **≥10 H-1B filings** (≈506 qualifying pairs
  on current data). Gate shared (`lib/business/salary/h1b_salary_pair.py`) between
  the view 404-gate and the cached sitemap emit-set (capped 5k) so the sitemap
  never lists a 404.
- **Internal-link mesh (gated, never a 404):** the h1b-sponsors role page links
  each qualifying employer's wage cell to its pair page; the `/job-title/` profile
  links each top-employer's median cell to the pair page. Plus the sitemap.
- **Test:** `tests/test_h1b_salary_pair_landing.py` (qualifying renders distribution
  + market-comparison + FAQPage + self-canonical + outbound mesh; thin/sub-
  threshold/PERM/unknown 404; gate + sitemap emit qualifying only; role-page
  wage-cell mesh gated).
- **Status (2026-06-24):** **LIVE on prod** via the first zero-downtime code
  cutover (`hosting/cutover.sh --code 1090314`; vb never 502'd), `prod d940644`,
  506 pages in the prod sitemap, CF purged, GSC re-submitted, suite 75 green. GSC
  measurement pending.

## {occupation} salary landing pages (`/h1b-salary/<occupation>/` + `/h1b-salary/` hub)

Head-term salary pages keyed off the clean **DOL SOC occupation code**, capturing
the **"{occupation} h1b salary" / "{occupation} salary"** demand that drives the
/salaries on-site search (Software Engineer, Data Scientist, Financial Analyst …).
The existing `/job-title/<slug>/` cluster pages only rank for ultra-long-tail
niche titles because clustering mangles the head terms —
`/job-title/software-engineer/` 301s to a garbage canonical
(`sr-member-of-the-technical-staff-software-engineer`), so the head terms had **no
clean landing page**. This page type fixes that with a curated occupation→SOC
registry, independent of clustering.

- **Why SOC, not soc_title:** `soc_code` is the clean DOL classification;
  `soc_title` in the data is employer-typed garbage (often the code itself or a
  random title). A curated registry maps colloquial head terms → SOC-6 prefixes
  (validated against the dominant real `job_title` per code on prod).
- **Content:** percentiles (p10–p90), median + p25–p75 range, top sponsoring
  employers (linked), top worksite states, real job-title cross-links (to
  `/job-title/` pages), H-1B-vs-PERM split, query-targeted `<title>`
  ("{Occupation} H-1B & PERM Salary {year}: Median $X (N filings)"). FAQPage +
  Occupation JSON-LD, self-canonical.
- **Registry/view:** `lib/business/salary/soc_occupations.py` (41 curated
  occupations, alias→canonical 301s), `lib/business/salary/occupation_stats.py`
  (reuses `common_stats`; `$12k` wage floor keeps low-wage PERM occupations like
  cook/truck-driver), `webapp/views/salary/occupation.py`.
- **No thin pages:** an occupation 404s unless **≥100 filings**; gate shared with
  the cached sitemap emit-set so the sitemap never lists a 404. All 41 registry
  occupations currently qualify.
- **Internal-link mesh:** "Salary by occupation" hub button added to the
  `/salaries` explore rail (renders on every salary search view); hub
  cross-links every page; pages link back to `/job-title/` + `/salaries`. Also
  in the sitemap + `/llms.txt`.
- **Test:** `tests/test_occupation_salary.py` (qualifying renders title/median/
  percentiles/FAQPage/Occupation/self-canonical + employer mesh; thin 404; alias
  301; SOC-scoping; unknown 404; hub + sitemap emit qualifying only).
- **Status (2026-06-26):** **LIVE on prod** via zero-downtime code cutover
  (`hosting/cutover.sh --code 50b9961`; vb never 502'd), `prod 0a071d1`, 41
  occupation pages + hub in the prod sitemap, CF purged, GSC re-submitted (0
  errors, 14,436 URLs), suite 78 green. Validated against prod data (SWE 460k
  filings/$111k median, attorney $180k, truck-driver $42k). GSC measurement
  pending (~days–weeks to index).

## Timing-query consolidation (`/when-is-the-next-visa-bulletin/`)

The dedicated release-schedule page targets the **"when will the {month} {year}
visa bulletin come out / be released"** cluster (~1,100+ impr/mo, GSC). It was
**indexed but getting 0 impressions** — the homepage had consolidated the timing
intent and ranked the cluster at pos ~10; the better-targeted page never
surfaced. Schema was NOT the gap (it already had FAQPage). Two real levers
applied (2026-06-23):

- **Month-specificity** — `<title>` + an H2 + a month-keyed FAQ question now name
  the governing month (`When Will the {Month Year} Visa Bulletin Come Out?`),
  rolling forward each month like the forecast page, to match the high-volume
  month-specific variant. H1 stays generic ("When does the next Visa Bulletin
  come out?") so the generic query is still covered. View:
  `webapp/views/static/pages.py:next_bulletin_view`.
- **Internal-link consolidation** — contextual timing-anchor links now point to
  the page from high-authority surfaces (homepage body, the per-month forecast
  page CTA, the prediction archive forecast alert), not just the site-wide
  nav/footer — so Google prefers the dedicated page over the homepage for the
  cluster. Previously only `base.html` + `faq.html` linked it.
- Test: `tests/test_next_bulletin.py` (month-specific title/H2/FAQ + inbound-link
  mesh). **Status (2026-06-23):** shipped to `main`, suite green. Pending staging
  deploy + GSC measurement of the homepage→dedicated-page shift over ~2-3 wks.

## Off-page: head-term backlinks (Lever 4)

The "visa bulletin" head term sits at pos ~8.6 (157k impr/mo) with on-page Levers
1–3 shipped; the residual gap is domain authority (inbound links). Lever 4 = earn
links to a link-worthy asset. **Chosen asset: the salary DB** (`/salaries/`) — a
concrete, factual, citeable free reference (1.5M+ DOL wage records, Dataset JSON-LD).

- **Page shaped for citation (2026-06-25):** added a "Cite or link to this database"
  block to the About-This-Data card on `salary_search.html` — canonical URL +
  suggested plain-text reference, so a link is the obvious thing to do. Also softened
  the "How to Use" copy off PERM-as-GC-sponsorship framing (`perm_messaging.md`).
- **Outreach:** drafts (email to immigration blogs / free-tools roundups / comp-data
  writers + a forum-thread post) live in
  `visa_bulletin_platform/marketing/drafts/BACKLINK_OUTREACH_SALARY_DB_2026-06-25.md`.
  Every send is Tier-3 (held for per-target approval). The Reddit account is a poor
  vector here (low karma, banned/removed in the key subs), so vectors are email +
  forum, not Reddit.
- Slow burn — backlinks accrue over weeks/months. Ticket: 38362b8d.

## AI Crawler Support (`/llms.txt`)

`/llms.txt` is served by `llms_txt_view` in `webapp/views/seo/sitemaps.py`. It follows the [llmstxt.org](https://llmstxt.org) convention for telling AI crawlers (ChatGPT, Perplexity, Claude, etc.) what data this site contains and how to cite it.

Content includes:
- Section-by-section description of the site (dashboard, salary DB, employer profiles, job title profiles, analysis)
- Canonical URLs for each section
- Data source descriptions (State Dept, DOL) and update frequency
- Citation guidance

## Caching Strategy

`@cache_page_skip_bots(settings.CACHE_TIMEOUT)` (24 hours) applied to: sitemap, robots.txt, llms.txt, profile pages, directory pages, autocomplete, dashboard, salary search.

**Bot bypass**: `cache_page_skip_bots` (in `django_config/cache_utils.py`) skips the cache entirely for known bot User-Agents (Googlebot, Bingbot, GPTBot, DuckDuckBot, Baiduspider, YandexBot, facebookexternalhit, Slurp). Bots always hit the live view and get fresh data.

**Cache clearing**: `scripts/clear_cache.py` with `--sitemap-only` flag (clears sitemap + robots cache) or full `cache.clear()`. Run automatically in the refresh pipeline after `warm_cache`.

## Meta Tags (base.html)

`webapp/templates/webapp/base.html` provides site-wide defaults. Profile templates override via context variables.

| Tag | Source |
|-----|--------|
| `<title>` | `page_title` context var (default: "U.S. Immigration Data — Visa Bulletin Dashboard") |
| `<meta description>` | `page_description` context var |
| `<meta keywords>` | Hardcoded: visa bulletin, priority date tracker, EB2, EB3, green card, ... |
| `<meta author>` | "U.S. Immigration Data" |
| `<meta theme-color>` | `#003366` |
| `<link rel="canonical">` | `canonical_url` context var (rendered only if set) |
| `<meta robots>` | `meta_robots` context var (rendered only if set; default = no tag = `index, follow`) |

## /salaries onward-navigation rail — dead-end break

`/salaries/` is the highest-traffic non-home page but had the worst behavior
(64% bounce / 36% engaged): result pages ended at pagination with no onward
path, and the landing offered no scannable next step. The **"Explore the salary
database" rail** (`webapp/templates/webapp/includes/salary_explore_rail.html`)
now renders on **every** salary search render — bare landing, filtered results,
and zero-result searches — carrying: popular-role chips → `/job-title/<slug>/`,
top-sponsor chips → `/employer/<slug>/`, browse hubs (job-title + employer
directories, sponsor ranking, priority-date hub), and H-1B/PERM quick filters.
Link sets come from `get_salary_explore_links()`
(`lib/business/salary/market_overview.py`, cached — top clusters off precomputed
counts, cheap on every render). This both breaks the UX dead-end and strengthens
the internal-link mesh into the employer/job-title pSEO pages (and now the
`{occupation}` salary pages — the rail's "Salary by occupation" button). Regression
tests: `tests/test_salary_search_view.py::SalaryExploreRailTest`. Follow-up: the
`{occupation}` pSEO landing pages from on-site search demand **shipped 2026-06-26**
(see the `/h1b-salary/<occupation>/` section above); still open: measure the GA4
`/salaries` bounce delta (~1–2 wks) + the `/employer/*` meta-description CTR tweak.

## Crawl-budget hygiene — noindex the free-text search space

The free-text keyword search `/salaries/?q=<keyword>` (and `/worksites/?q=<keyword>`) is an **unbounded URL space** — every distinct query string is a new page. Left indexable, Google burns crawl budget on infinite low-value permutations. Both search views set `meta_robots = "noindex, follow"` whenever a non-empty `q` param is present (`webapp/views/salary/search.py`, constant `_NOINDEX_FOLLOW`), and `base.html` renders `<meta name="robots" content="noindex, follow">` from it. `follow` keeps link equity flowing from results to the canonical employer/job-title/state slug pages.

Stays indexable (no robots tag): the bare `/salaries/` landing, slug pages (`/salaries/employer/<slug>/`, `/salaries/role/<slug>/`, `/salaries/by-state/<slug>/`), and curated filter combos without a free-text `q` (employer-slug / state / program) — the dynamic-SEO design intentionally ranks those. Regression test: `tests/test_salary_search_view.py::SalarySearchNoindexTest`.

## Canonical URLs

All dynamic pages that can receive query parameters set `canonical_url` to the clean path (no query params):

| Page | Canonical set by |
|------|-----------------|
| Employer profile | `profile.py` → `request.build_absolute_uri(request.path)` → context `canonical_url` |
| Job title profile | `profile.py` → `request.build_absolute_uri(request.path)` → context `canonical_url` |
| Salary search | `search.py` → `request.build_absolute_uri(reverse("salary_search"))` |
| Worksite search | `search.py` → `request.build_absolute_uri(reverse("worksite_search"))` |
| Dashboard | Set in `dashboard.py` |

Profile templates do **not** emit a second `<link rel="canonical">` in `extra_head` — they rely entirely on `base.html` rendering it from the `canonical_url` context var.

## Open Graph & Twitter Cards

Set in `base.html`, overridable via context:

- `og:image` / `twitter:image` → `/static/og-image.png` (1200×630)
- `og:type` → website
- `og:site_name` → "U.S. Immigration Data"
- `twitter:card` → summary_large_image

Profile templates (`job_title_profile.html`) override with page-specific title, description, canonical, and image.

## Structured Data (JSON-LD)

### Global (every page via `base.html`)

1. **Organization** — name, url, logo, contactPoint, sameAs
2. **WebSite** with **SearchAction** — `urlTemplate` for category/country search

### Per-page schemas

| Page | Schemas |
|------|---------|
| Dashboard | `Dataset` (built in Python by `_build_structured_data()` in `lib/business/bulletin/cutoff_data_aggregator.py`) |
| Salaries landing (`/salaries/`, bare) | corpus `Dataset` (1.5M+ DOL salary records) via `webapp/views/seo/jsonld.py:build_dataset_jsonld` |
| Salaries (employer-scoped) | per-employer `Dataset` (`search.py:_build_dataset_jsonld`) |
| Employers directory (`/employers/`) | corpus `Dataset` (221K+ visa sponsors) via `build_dataset_jsonld` |
| Job title profile | `Occupation` + `MonetaryAmountDistribution` (salary percentiles) + `BreadcrumbList` |
| Employer profile | `Organization` + optional `AggregateRating` (only when `total_filings > 0`) + `BreadcrumbList` |
| FAQ | `FAQPage` |
| Next-bulletin (`/when-is-the-next-visa-bulletin/`) | `FAQPage` (projected release date, cadence, official source) — projection in `lib/business/bulletin/release_schedule.py` from recent `Bulletin.fetched_at` |

**Dataset on the `/salaries/` + `/employers/` landings (added 2026-06-18, commit `5f74599`).**
These landings rank for the dataset-intent head queries ("h1b salary database",
"perm salary database", "green card salary database", sponsor lookups) but had no
page-level structured data — the bare `/salaries/` landing explicitly emitted none.
Each now carries a `schema.org/Dataset` describing the whole corpus, eligible for a
Dataset rich result on exactly those queries. Shared builder + `<script>`-safe
embedding live in `webapp/views/seo/jsonld.py`. Same change tightened both page
`<title>`s to ≤60 chars (were truncating in SERP), keeping "Database" + the
question hook front-loaded. CTR impact to be re-measured in GSC ~2 weeks out.

> Note on the `/employers/` aggregate CTR (~0.075% on ~27k impr): most of those
> impressions are structurally **wrong-intent** — the page surfaces at pos ~8–10 for
> generic visa-bulletin queries ("boletin de visas", "bulletin visa uscis", "current
> date for eb1 india") it inherits from the domain brand, which no title/meta can win.
> The Dataset + title work targets the dataset-intent queries the page *should* own;
> the wrong-intent drag is a relevance/position concern (the head-terms ticket).

**`AggregateRating` on employer profiles**: uses visa approval rate (0–100) as `ratingValue` on a 0–100 scale. `ratingCount` is always `total_filings > 0` (guard added after Google Search Console warning). Worth monitoring in Search Console Rich Results report to confirm Google renders it.

**`BreadcrumbList`**: emitted as a separate JSON-LD block in the profile `extra_head`. Uses `request.scheme`/`request.get_host` for portability across environments.

## Favicon System

Referenced in `base.html`:

| File | Purpose |
|------|---------|
| `favicon.ico` | Legacy browsers |
| `favicon-32x32.png` | Modern browsers |
| `favicon-16x16.png` | Small tabs |
| `favicon.svg` | Vector format |
| `apple-touch-icon.png` | iOS home screen (180×180) |

Source SVG: `webapp/static/favicon.svg`. Regenerate PNGs: `./scripts/generate_favicon_png.sh`.

## Profile Page SEO

**Job title profiles** (`/job-title/{slug}/`):
- Custom `<title>`, `<meta description>`, `<link rel="canonical">` via `seo` context dict
- Page-specific OG/Twitter tags in `{% block extra_head %}`
- `Occupation` + `BreadcrumbList` JSON-LD schemas

**Employer profiles** (`/employer/{slug}/`):
- Custom `seo` dict with title, description, canonical_url
- `canonical_url` set in context (path-only, no query params)
- `Organization` + optional `AggregateRating` + `BreadcrumbList` JSON-LD schemas
- Fuzzy slug redirect: old/mismatched slugs → 301 to canonical cluster slug

**Directories** (`/job-titles/`, `/employers/`):
- Custom `page_title` and `page_description`
- Paginated with query params

## HTTPS & Redirects

Handled by nginx, not Django. Django HTTPS settings are commented out in `settings.py`. Nginx handles:
- HTTP → HTTPS redirect
- SSL termination (Let's Encrypt via certbot)

## Known Issues

1. **Stale Google index entries**: ~74 old job-title/employer slugs that no longer exist still return 404. These are not in the current sitemap and will self-resolve. Use Search Console "Validate Fix" to speed up.
2. **`AggregateRating` eligibility**: approval-rate-as-rating may not qualify for Google rich snippets (it's not a user-review rating). Monitor in Search Console → Rich Results.
3. **Blog and prediction pages**: no per-page `page_description` or OG image — sharing falls back to site defaults. Consider adding per-post description to `BlogPost` model and per-month description to prediction detail view.
4. **`WebSite` `SearchAction`**: uses `category`/`country` URL template — validate at https://search.google.com/test/rich-results that it qualifies for sitelinks search box.

## Testing & Verification

| Tool | URL | What to check |
|------|-----|---------------|
| Google Rich Results Test | https://search.google.com/test/rich-results | Organization, WebSite, Occupation, BreadcrumbList schemas |
| Facebook Sharing Debugger | https://developers.facebook.com/tools/debug/ | OG image, title, description |
| PageSpeed Insights | https://pagespeed.web.dev/ | Core Web Vitals, image sizes |
| Google Search Console | https://search.google.com/search-console | Index coverage, sitemap status, 404s, rich results |

## Design Decisions

**Homepage title is intentionally narrow (country/category-specific).** The dashboard view builds a title like "India Employment-Based Visa Bulletin Predictions & Tracker - March 2026" based on the active filter. This is deliberate — the vast majority of real visitors are Indian EB-2/EB-3 applicants, so the default title matches their intent and reduces friction. A broad generic title would serve SEO auditors but not actual users.

**`/llms.txt` over robots meta tags for AI.** AI crawlers (GPTBot, Claude-Web, PerplexityBot) are already in the `cache_page_skip_bots` bypass list and allowed by robots.txt. The `llms.txt` file adds structured guidance on what content is available and citable, without restricting access.

## Key Files

| File | Purpose |
|------|---------|
| `webapp/views/seo/sitemaps.py` | Sitemap, robots.txt, and llms.txt views |
| `webapp/templates/webapp/base.html` | Site-wide meta tags, structured data, favicon refs |
| `webapp/views/job_titles/profile.py` | Job title profile SEO context |
| `webapp/views/employers/profile.py` | Employer profile SEO context |
| `webapp/views/salary/search.py` | Salary/worksite search canonical URLs |
| `django_config/cache_utils.py` | `cache_page_skip_bots` implementation |
| `scripts/cron/refresh/steps.py` | `step_ping_search_engines` and `step_clear_sitemap_cache` |
| `scripts/clear_cache.py` | Manual cache clearing (`--sitemap-only` flag) |
| `scripts/generate_favicon_png.sh` | Regenerate favicon PNGs from SVG |
