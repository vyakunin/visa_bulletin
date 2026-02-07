# Webapp - Views and Templates

This directory contains Django views, URL routing, templates, and forms for the visa bulletin web application.

## URL Patterns

### Employer Profile Pages
- **URL:** `/employer/<slug:slug>/`
- **View:** `employer_profile_view(request, slug)`
- **Template:** `webapp/templates/webapp/employer_profile.html`
- **Model:** `EmployerCluster` (with `slug` field)
- **Features:**
  - Interactive Plotly charts (job titles, geographic distribution, trends)
  - Filter by years (3/5/10/20) and program (H-1B/PERM)
  - SEO-optimized with meta tags and structured data
  - Caching: 6 hours page-level, 6 hours data-level
  - Auto-redirects from name variations to canonical slug

### Job Title Profile Pages
- **URL:** `/job-title/<title_slug>/`
- **View:** `job_title_profile_view(request, title_slug)`
- **Template:** `webapp/templates/webapp/job_title_profile.html`
- **Model:** `JobTitle`
- **Features:**
  - Market overview statistics
  - Top employers for the role
  - Geographic distribution
  - Year-over-year trends

### Salary Search
- **URL:** `/salaries/`
- **View:** `salary_search_view(request)`
- **Template:** `webapp/templates/webapp/salary_search.html`
- **Features:**
  - Search by job title, employer, state, program, fiscal year
  - Pagination (50 results per page)
  - Salary statistics (avg, min, max)

### Worksite Search
- **URL:** `/worksites/`
- **View:** `worksite_search_view(request)`
- **Template:** `webapp/templates/webapp/worksite_search.html`

## Key Files

- `views.py` - All view functions
- `urls.py` - URL routing configuration
- `forms.py` - Django forms for search
- `sitemaps.py` - Sitemap generation for SEO
- `templates/webapp/` - HTML templates
- `static/` - Static assets (favicons, images)

## Caching Strategy

- **Page-level cache:** `@cache_page_skip_bots(CACHE_TIMEOUT)` (24h); bot traffic is not cached so bots don't evict human cache (LRU).
- **Data-level cache:** Keyed by entity ID and filters
- **Cache duration:** 6 hours (salary data updates infrequently)
- **Cache invalidation:** Manual after data imports, or TTL-based expiration

## SEO Features

- Meta tags (title, description, OG, Twitter)
- Structured data (Schema.org)
- Sitemap generation (`/sitemap.xml`)
- Canonical URLs
- SEO-friendly slugs

## Testing

Tests are in `tests/test_employer_profile_view.py` and other test files in `tests/`.

Run tests:
```bash
bazel test //tests:test_employer_profile_view
```
