# SEO Optimization — Current State

Site: `https://visa-bulletin.us`

## Sitemap & robots.txt

Both generated dynamically by `webapp/views/seo/sitemaps.py`.

**robots.txt** (`/robots.txt`):
```
User-agent: *
Allow: /
Disallow: /api/
Sitemap: https://visa-bulletin.us/sitemap.xml
```

**Sitemap** (`/sitemap.xml`) — single `<urlset>`, ~9,200 URLs:

| Section | Count | Filter criteria |
|---------|-------|----------------|
| Static pages | 7 | `/`, `/salaries/`, `/employers/`, `/job-titles/`, `/faq/`, `/about/`, `/contact/` |
| Category/country landing | ~12 | `/employment-based/`, `/family-sponsored/` × countries |
| Employer profiles | ~3,900 | `EmployerCluster` with slug, `total_lca_count >= 5`, top 10k |
| Job title profiles | ~5,200 | `JobTitleCluster` with slug, `total_filings >= 10`, top 10k |

All URLs include `<lastmod>` set to the latest bulletin publication date (best proxy for "data last refreshed"). `changefreq: monthly`, `priority: 0.8`.

**Search engine ping**: The refresh pipeline pings Google and Bing after clearing the sitemap cache (`step_ping_search_engines` in `scripts/cron/refresh/steps.py`). Non-fatal on failure.

## Caching Strategy

`@cache_page_skip_bots(settings.CACHE_TIMEOUT)` (24 hours) applied to: sitemap, robots.txt, profile pages, directory pages, autocomplete, dashboard, salary search.

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

## Open Graph & Twitter Cards

Set in `base.html`, overridable via context:

- `og:image` / `twitter:image` → `/static/og-image.png` (1200×630)
- `og:type` → website
- `og:site_name` → "U.S. Immigration Data"
- `twitter:card` → summary_large_image

Profile templates (`job_title_profile.html`) override with page-specific title, description, canonical, and image.

## Structured Data (JSON-LD)

Embedded in `base.html`:

1. **Organization** — name, url, logo, contactPoint, sameAs
2. **WebSite** with **SearchAction** — `urlTemplate` for category/country search

Profile pages add page-specific schemas:
- **Job title profile**: `Occupation` schema with salary stats, employer count
- **Employer profile**: intended to have `Organization` schema (see known issues)

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
- `Occupation` JSON-LD schema

**Employer profiles** (`/employer/{slug}/`):
- Custom `seo` dict with title, description, canonical_url
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

## Testing & Verification

| Tool | URL | What to check |
|------|-----|---------------|
| Google Rich Results Test | https://search.google.com/test/rich-results | Organization, WebSite, Occupation schemas |
| Facebook Sharing Debugger | https://developers.facebook.com/tools/debug/ | OG image, title, description |
| PageSpeed Insights | https://pagespeed.web.dev/ | Core Web Vitals, image sizes |
| Google Search Console | https://search.google.com/search-console | Index coverage, sitemap status, 404s |

## Design Decisions

**Homepage title is intentionally narrow (country/category-specific).** The dashboard view builds a title like "India Employment-Based Visa Bulletin Predictions & Tracker - March 2026" based on the active filter. This is deliberate — the vast majority of real visitors are Indian EB-2/EB-3 applicants, so the default title matches their intent and reduces friction. A broad generic title would serve SEO auditors but not actual users.

## Key Files

| File | Purpose |
|------|---------|
| `webapp/views/seo/sitemaps.py` | Sitemap + robots.txt views |
| `webapp/templates/webapp/base.html` | Site-wide meta tags, structured data, favicon refs |
| `webapp/views/job_titles/profile.py` | Job title profile SEO context |
| `webapp/views/employers/profile.py` | Employer profile SEO context |
| `django_config/cache_utils.py` | `cache_page_skip_bots` implementation |
| `scripts/cron/refresh/steps.py` | `step_ping_search_engines` and `step_clear_sitemap_cache` |
| `scripts/clear_cache.py` | Manual cache clearing (`--sitemap-only` flag) |
| `scripts/generate_favicon_png.sh` | Regenerate favicon PNGs from SVG |
