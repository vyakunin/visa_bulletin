# DoL Data: Implemented Features & Promotion Strategy

This document summarizes **currently implemented** features for Department of Labor (DoL) salary data on visa-bulletin.us and provides a **step-by-step promotion strategy** with ready-to-send drafts (posts, emails, pitches).

**Base URL:** https://visa-bulletin.us

---

## Part 1: Currently Implemented Features (Detailed)

### 1.1 Salary Search (`/salaries/`)

**Purpose:** Search H-1B and PERM salary records from DOL disclosure files.

**Implemented capabilities:**

- **Filters**
  - **q** – Job title / keyword search (job_title, soc_title)
  - **employer** – Employer name (matches canonical cluster name)
  - **state** – Worksite state (2-letter code)
  - **program** – Visa program: `h1b`, `perm`, or all
  - **year** – Single fiscal year (e.g. FY 2024) or all years
- **Results:** Paginated list (50 per page) with employer name, job title, worksite city/state, wage (annual, and wage_to when present), visa program, fiscal year. Each row links to employer profile and job title profile when available.
- **When no filters are applied:** Market overview section with:
  - Filing volume over time (chart)
  - Median salary trend over time (chart)
  - Filings by state (chart)
  - Median salary by state (chart)
- **When filters are applied:** Aggregate stats (avg, min, max salary) for the filtered set.
- **Autocomplete:** Job title and company autocomplete endpoints used by the search form (see 1.5).
- **SEO:** Title “H-1B & PERM Salary Database | U.S. Immigration Data”, description for search engines.

**Data scope:** Non-worksite salary records only; excludes `employer_name='Unknown'` and records without a valid annual wage.

---

### 1.2 Worksite Search (`/worksites/`)

**Purpose:** Search worksite location data from DOL Worksites disclosure files.

**Implemented capabilities:**

- **Filters**
  - **q** – Job title / keyword (job_title, soc_title, worksite_city)
  - **state** – Worksite state (2-letter code)
  - **city** – Worksite city (substring match)
  - **program** – `h1b`, `perm`, or all
  - **year** – Fiscal year or all
- **Results:** Paginated list with worksite city/state, job title, wage, program, year.
- **Stats:** When any filter is applied, shows total count and avg/min/max salary for the filtered set.
- **SEO:** Title “Worksite Location Data | U.S. Immigration Data”, description for search engines.

**Data scope:** `WorksiteRecord` model (separate from employer-centric salary records).

---

### 1.3 Employer Directory (`/employers/`)

**Purpose:** Browse employers that have sponsored H-1B or PERM (by name and optionally by state).

**Implemented capabilities:**

- **Listing:** Paginated list of employer clusters that have at least one LCA or PERM filing. Excludes “Unknown” and clusters without a slug.
- **Search:** Optional query (company name substring) and optional state filter (worksite state).
- **Display:** For each employer: canonical name, slug link to profile, filing counts (LCA + PERM when available), optional state breakdown.
- **Ordering:** By relevance (e.g. total filing count) and name.
- **SEO:** Indexable directory page; each row links to `/employer/<slug>/`.

---

### 1.4 Employer Profile (`/employer/<slug>/`)

**Purpose:** Single-employer view of sponsorship and salary statistics.

**Implemented capabilities:**

- **Resolve slug:** Slug from URL matches `EmployerCluster.slug`. If not found, attempts match by normalized employer name and redirects to canonical cluster slug (301). Otherwise 404.
- **Overview (basic stats):**
  - Total filings (for selected years/program/level)
  - Approval rate (approved / total)
  - Median, min, max salary
  - Year-over-year growth (e.g. filing volume or salary trend)
- **Top job titles:** Top 10 job titles at this employer by filing count, with count, median/min/max salary; each links to job title profile.
- **Salary distribution:** Histogram of salary distribution; optional overlays for top job titles.
- **Geography:**
  - Filings by state (bar chart: count per state)
  - Median salary by state (bar chart)
- **Trends:** Year-over-year filing volume (line chart).
- **Filters (query params):**
  - **years** – 1–20 fiscal years (default 5)
  - **program** – `h1b`, `perm`, or `all`
  - **level** – Experience level (entry, mid, senior, etc.) or `all` / `unspecified`
- **SEO:** Dynamic title “{Employer} H-1B & PERM Sponsorship Data | Visa Bulletin”, description with filings count, approval rate, median salary. Canonical URL set.
- **Performance:** Page payload (stats + chart data) cached per employer/filters; cache timeout from settings.

---

### 1.5 Job Title Directory (`/job-titles/`)

**Purpose:** Browse job titles by popularity (filing count).

**Implemented capabilities:**

- **Listing:** Paginated list of job title clusters with `slug` and `total_filings > 0`. Excludes clusters without slug.
- **Summary:** Aggregate stats (total titles, total filings, average salary) when available.
- **Featured:** “Popular” job titles (e.g. top 12 by total filings) for quick access.
- **Display:** For each cluster: canonical title, slug link to profile, total filings, median/avg salary when available.
- **SEO:** Indexable directory; each row links to `/job-title/<slug>/`.

---

### 1.6 Job Title Profile (`/job-title/<slug>/`)

**Purpose:** Market analysis for a single job title (cluster).

**Implemented capabilities:**

- **Resolve slug:** Slug matches `JobTitleCluster.slug`. If not found, attempts match by normalized title and redirects to canonical cluster slug (301). Otherwise 404.
- **Market overview (from cluster + stats):**
  - Total filings (uses cluster-level total so it matches directory “Popular Job Titles”)
  - Median salary, percentiles
  - Top employers for this role (with links to employer profiles)
  - Experience vs salary (when experience_level data exists)
  - Geographic salary distribution
- **Charts:** Salary distribution, geography, trends (built by `build_job_title_profile_charts`).
- **Related job titles:** Other titles in the same cluster (raw title variants).
- **Similar job titles:** Other clusters whose canonical title shares the first word (e.g. “Software” → “Software Engineer”, “Software Developer”); limited (e.g. top 5 by filing count).
- **Filters (query params):**
  - **years** – 1–20 (default 5)
  - **program** – `h1b`, `perm`, or `all`
  - **level** – Experience level or `all` / `unspecified`
- **SEO:** Dynamic title “{Job Title} Salary Data & Market Analysis | Visa Bulletin”, description with total filings and median salary. Canonical URL set.
- **Performance:** Cached per cluster/filters; cache timeout from settings.

---

### 1.7 Autocomplete APIs

**Company autocomplete** – `GET /api/company-autocomplete/?q=<query>&limit=20`

- Returns JSON array of `{ name, slug, count }` for employer clusters whose `canonical_name` contains the query (case-insensitive). Excludes “Unknown” and clusters without slug. Ordered by total filing count (LCA + PERM) then name. Minimum 2 characters for `q`.

**Job title autocomplete** – `GET /api/job-title-autocomplete/?q=<query>&limit=20`

- Returns JSON array of `{ title, slug, total_filings }` for job title clusters whose `canonical_title` contains the query. Uses precomputed `total_filings_recent` (e.g. last 5 years). Minimum 2 characters for `q`.

Both are used by the salary search form and can be reused for other UI (e.g. employer directory, future comparison tools).

---

### 1.8 Sitemaps & Robots

**Robots:** `robots.txt` allows all crawlers and points to the sitemap URL.

**Sitemap:** Single XML sitemap listing:

- Static: `/`, `/salaries/`, `/worksites/`, `/employers/`, `/job-titles/`, `/faq/`, `/about/`, `/contact/`
- Category landing pages: `/employment-based/`, `/family-sponsored/`, and per-country under each
- Employer profile URLs: `/employer/<slug>/` for clusters with slug and `total_lca_count >= 5`, ordered by LCA count, capped at 10,000
- Job title profile URLs: `/job-title/<slug>/` for clusters with slug and `total_filings >= 10`, ordered by filing count, capped at 10,000

This supports SEO and discovery of employer/job title pages by search engines.

---

### 1.9 Static & Supporting Pages

- **FAQ** – `/faq/`
- **About** – `/about/`
- **Contact** – `/contact/`
- **Dashboard** – `/` (visa bulletin dashboard; employment-based/family-sponsored category and country landing pages use the same view with different parameters)

These are linked from the main site and included in the sitemap.

---

### 1.10 Data & Backend (Relevant to “What’s Implemented”)

- **Models:** `SalaryRecord`, `WorksiteRecord`, `Employer`, `EmployerCluster`, `JobTitle`, `JobTitleCluster` (see `models/salary.py`, `models/job_title.py`).
- **Employer clustering:** Canonical employer names and slugs; profile pages use cluster-level stats.
- **Job title clustering:** Canonical job titles and slugs; stats and “related/similar” use cluster-level data.
- **Pipeline:** Data ingest (LCA, PERM, worksite files), employer/job title clustering, and scripts such as `update_employer_stats`, `update_job_title_cluster_stats`, `populate_job_title_slugs` keep counts and slugs up to date. Cache is cleared after refresh (e.g. via `clear_cache` script) so directory and profile pages reflect new data.

---

## Part 2: Step-by-Step Promotion Strategy (What’s Already Live)

The following sequence promotes **only** what exists today: salary search, worksite search, employer directory and profiles, job title directory and profiles, autocomplete, and sitemaps. Use the drafts as-is or adapt to your voice and current numbers.

**Assumptions:** You have approximate record counts (e.g. “500K+ salary records”, “10K+ employers”) and a few concrete examples (e.g. top employers, a striking salary comparison). Replace placeholders before sending.

---

### Step 1: Reddit – r/h1b (and r/immigration if allowed)

**Goal:** Reach H-1B and green card seekers; drive traffic and bookmarks.

**When:** Week 1, Day 1 (or first day of “launch”).

**Draft post (copy-paste ready; fill [BRACKETS]):**

```text
Title: I built a free searchable database of H-1B & PERM salaries from DOL data – 500K+ records

Body:

I’ve been using the public DOL disclosure files for a while and finally put together a site where you can search and browse the data without downloading spreadsheets.

What you can do:
• Search salaries by job title, company, state, visa program (H-1B vs PERM), and year: https://visa-bulletin.us/salaries/
• Browse employers and open a profile per company (filings, approval rate, median salary, top roles, by state, trends): https://visa-bulletin.us/employers/
• Browse job titles and open a profile per role (total filings, median salary, top employers, geography, similar titles): https://visa-bulletin.us/job-titles/
• Worksite search (by city/state/job title): https://visa-bulletin.us/worksites/

Data comes from official DOL LCA and PERM disclosures. No paywall, no signup. I run it as a side project for the immigration community.

If you’re negotiating an offer or comparing companies, the employer and job title pages are the most useful. Hope it helps.
```

**Checklist before posting:**

- [ ] Replace “500K+” with your actual approximate salary record count if different.
- [ ] Confirm all four links return 200 and show data.
- [ ] Read subreddit rules; ensure “no self-promotion” or “self-promo” rules allow one clear, useful post; add disclaimer if required (e.g. “I built this”).

---

### Step 2: Reddit – r/immigration (if separate from Step 1)

**Goal:** Reach a broader immigration audience (family-based, students, etc.) who may still care about employer sponsorship and salary transparency.

**When:** Week 1, Day 2 (or 24h after r/h1b to avoid cross-posting the same day).

**Draft post:**

```text
Title: Free H-1B & PERM salary database from DOL data – search by company, job title, state

Body:

There’s a lot of DOL disclosure data out there but it’s not easy to search. I built a free site that indexes it so you can:

• Search H-1B and PERM salaries by job title, employer, state, and year
• See per-company stats: total filings, approval rate, median salary, top job titles, geographic breakdown
• See per-job-title stats: total filings, median salary, top employers, similar roles

All from official DOL data, no login. Links:
Salaries: https://visa-bulletin.us/salaries/
Employers: https://visa-bulletin.us/employers/
Job titles: https://visa-bulletin.us/job-titles/

Might be useful if you’re researching employers or comparing offers.
```

**Checklist:**

- [ ] Verify links and that pages load.
- [ ] Comply with subreddit self-promo rules (e.g. ratio of participation vs promotion).

---

### Step 3: Twitter/X – Single launch thread

**Goal:** Shareability and discovery; possible pickup by immigration/tech accounts.

**When:** Week 1, Day 2 or 3.

**Draft thread (10 tweets; replace [N] with actual numbers where possible):**

```text
1/ I built a free, searchable database of 500K+ H-1B & PERM salaries from official DOL data.

No spreadsheets. No signup. Just search by company, job title, or state.

https://visa-bulletin.us/salaries/

2/ You can see per-company profiles: total filings, approval rate, median salary, top job titles, and where they hire (by state).

Example – search "Google" or go to employers and open any company:
https://visa-bulletin.us/employers/

3/ You can also see per-job-title profiles: how many filings, median salary, top employers, and similar roles.

Useful when comparing offers or researching a role:
https://visa-bulletin.us/job-titles/

4/ Data = LCA + PERM disclosure files from the Department of Labor. Same data that’s public, but indexed and filterable.

H-1B vs PERM, by year, by state – all in one place.

5/ I run this as a side project for the immigration community. No ads, no paywall.

If you find it useful, bookmark it or share with someone job hunting or negotiating.

6/ Quick links:
• Salary search: https://visa-bulletin.us/salaries/
• Employers: https://visa-bulletin.us/employers/
• Job titles: https://visa-bulletin.us/job-titles/
• Worksites: https://visa-bulletin.us/worksites/

7/ [Optional – add one concrete fact from your data, e.g.]
Example: In the last 5 years, [Company X] had [N] H-1B/PERM filings with a median salary of $[X]. Top role: [Job Title]. (From https://visa-bulletin.us/employer/[slug]/)

8/ Built with Django, Postgres, and the same public DOL files you could download yourself – just made it queryable and linked employer/job title profiles so you don’t have to.

9/ If you’re on H-1B or going through PERM, hope this helps with offer comparison and employer research. Feedback welcome.

10/ Summary: Free H-1B & PERM salary DB from DOL data → https://visa-bulletin.us/salaries/ — search by company, job title, state. Employer & job title profiles with stats and trends. No signup.
```

**Checklist:**

- [ ] Replace “500K+” and any example company/numbers with real data.
- [ ] Add one real employer profile link in tweet 7 (and optional tweet 10).
- [ ] Post from an account that has some history (not a brand-new account) to reduce spam flags.

---

### Step 4: LinkedIn – Single professional post

**Goal:** Reach HR, recruiters, and immigration-adjacent professionals; position as a transparency tool.

**When:** Week 1, Day 3 or 4.

**Draft post:**

```text
I built a free, searchable database of H-1B and PERM salaries from U.S. DOL disclosure data.

What it does:
→ Search salaries by job title, company, state, and visa program (H-1B vs PERM).
→ Employer profiles: filing volume, approval rate, median salary, top roles, geographic spread.
→ Job title profiles: market size, median salary, top employers, similar roles.

Data source: public LCA and PERM disclosure files. No paywall, no signup – just a side project to make this data easier to use for job seekers and anyone researching sponsorship and pay.

If you work in immigration, HR, or recruiting, you might find it useful for benchmarking or candidate conversations. If you’re negotiating an offer, the employer and job title pages can help.

Link: https://visa-bulletin.us/salaries/

#H1B #PERM #Immigration #SalaryTransparency #DOL
```

**Checklist:**

- [ ] Confirm link works; optionally add one employer or job title profile link in a comment.
- [ ] Adjust hashtags to your usual style if needed.

---

### Step 5: Journalist / outlet outreach (email)

**Goal:** One or two stories or mentions in immigration, tech, or business outlets.

**When:** Week 1, Day 4–5 (after Reddit/Twitter so you can say “recently launched” or “getting traction on Reddit”).

**Draft email (send individually; personalize [Publication] and [Angle]):**

```text
Subject: New free tool: searchable H-1B & PERM salary database (DOL data)

Hi [Name / "the team"],

I built a free, public database that makes DOL H-1B and PERM disclosure data searchable – 500K+ records by company, job title, and state. I thought it might be useful for [Publication]’s coverage of [immigration / tech hiring / salary transparency].

What’s live:
• Salary search: filter by employer, job title, state, visa program, year
• Employer profiles: total filings, approval rate, median salary, top roles, geographic breakdown, trends
• Job title profiles: market size, median salary, top employers, similar roles
• All from official DOL data; no paywall or signup

Link: https://visa-bulletin.us/salaries/

[Optional: I can share a few headline-ready stats – e.g. top employers by volume, biggest pay gaps between companies for the same role – or a short methodology note. Happy to provide screenshots or a quick call if useful.]

Thanks,
[Your name]
[Your email]
```

**Checklist:**

- [ ] Replace [Publication] and [Angle]; use a real name if possible.
- [ ] Prepare 2–3 concrete stats (e.g. “Top 5 employers by H-1B filings”, “Median salary for Software Engineers at Company X vs Y”) and attach or paste in a short follow-up.
- [ ] Target 5–10 outlets (e.g. TechCrunch, Bloomberg Law, Law360, Vox Recode, The Verge, local tech/immigration beat reporters).

---

### Step 6: Hacker News (Show HN)

**Goal:** Technical audience and possible front-page traffic.

**When:** Week 2, Day 1 (or when you have one or two Reddit/Twitter replies to cite as “early feedback”).

**Draft post:**

```text
Title: Show HN: Searchable H-1B & PERM salary database from DOL disclosure data

Body:

I built a site that indexes public DOL LCA and PERM data so you can search and browse without downloading spreadsheets.

• Search: https://visa-bulletin.us/salaries/ — by job title, company, state, program (H-1B/PERM), year
• Employer profiles: https://visa-bulletin.us/employers/ — per-company stats (filings, approval rate, median salary, top roles, by state)
• Job title profiles: https://visa-bulletin.us/job-titles/ — per-role stats (filings, median salary, top employers)
• Worksite search: https://visa-bulletin.us/worksites/ — by city/state/title

Stack: Django, Postgres, employer/job title clustering to dedupe names. Data is refreshed from DOL files periodically. No login, no ads.

I run it for the immigration community; feedback from HN would be valuable.
```

**Checklist:**

- [ ] Post as “Show HN” and expect moderation; avoid marketing language.
- [ ] Be ready to answer technical questions (stack, scaling, data pipeline) in the thread.

---

### Step 7: Follow-up and reuse

**Goal:** Keep momentum and reuse content.

- **Reddit:** When someone asks “where can I check H-1B salaries?” or “how do I compare employers?”, reply with a short sentence + link to https://visa-bulletin.us/salaries/ or the relevant employer/job title page. Don’t spam; one helpful reply per thread.
- **Twitter/X:** Quote-tweet your own thread with one new stat (e.g. “Update: [X] employers now in the database” or “Most-searched job title this week: [Y]” if you add analytics later).
- **Journalists:** If no reply in 5–7 days, one short follow-up email: “Re: searchable H-1B/PERM database – happy to send 2–3 headline-ready stats or a 1-pager if that’s useful.”
- **Email list / newsletter:** If you have one, add one paragraph to the next issue: “I launched a free H-1B & PERM salary search and employer/job title profiles from DOL data: https://visa-bulletin.us/salaries/.”

---

## Part 3: Quick reference – URLs and one-liners

**For social bios, link trees, or signatures:**

- **One link:** https://visa-bulletin.us/salaries/
- **One-liner:** “Free searchable H-1B & PERM salary database from DOL data – by company, job title, and state.”
- **Longer:** “Search 500K+ H-1B and PERM salaries from DOL data. Employer and job title profiles with filings, approval rates, and median pay. No signup.”

**Key URLs:**

| Page            | URL                                      |
|-----------------|-------------------------------------------|
| Salary search   | https://visa-bulletin.us/salaries/        |
| Worksite search | https://visa-bulletin.us/worksites/       |
| Employers       | https://visa-bulletin.us/employers/       |
| Employer profile| https://visa-bulletin.us/employer/<slug>/ |
| Job titles      | https://visa-bulletin.us/job-titles/      |
| Job title profile | https://visa-bulletin.us/job-title/<slug>/ |
| FAQ             | https://visa-bulletin.us/faq/             |
| About           | https://visa-bulletin.us/about/           |
| Contact         | https://visa-bulletin.us/contact/         |

---

## Part 4: What’s not implemented (out of scope for this doc)

The following are **not** built yet; do not promise them in promo:

- Employer “grades” or report cards
- Employer comparison tool (side-by-side)
- Rankings/leaderboards (e.g. “Top 100 by salary”)
- User accounts, alerts, or saved searches
- Export or API for third parties
- Cost-of-living adjusted salary views
- Demographics (country of chargeability, education) on profile pages

Stick to: search, employer profiles, job title profiles, directories, worksite search, autocomplete, and sitemaps.

---

*Last updated: February 2026. Align promo with current site and data; refresh record counts and example links before each campaign.*
