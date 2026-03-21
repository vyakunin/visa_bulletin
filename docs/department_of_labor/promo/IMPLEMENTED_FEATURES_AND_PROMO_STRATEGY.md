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
- **Autocomplete:** Job title and company autocomplete endpoints used by the search form (see 1.6).
- **SEO:** Title "H-1B & PERM Salary Database | U.S. Immigration Data", description for search engines.

**Data scope:** Non-worksite salary records only; excludes `employer_name='Unknown'` and records without a valid annual wage.

---

### 1.2 Employer Directory (`/employers/`)

**Purpose:** Browse employers that have sponsored H-1B or PERM (by name and optionally by state).

**Implemented capabilities:**

- **Listing:** Paginated list of employer clusters that have at least one LCA or PERM filing. Excludes "Unknown" and clusters without a slug.
- **Search:** Optional query (company name substring) and optional state filter (worksite state).
- **Display:** For each employer: canonical name, slug link to profile, filing counts (LCA + PERM when available), optional state breakdown.
- **Ordering:** By relevance (e.g. total filing count) and name.
- **SEO:** Indexable directory page; each row links to `/employer/<slug>/`.

---

### 1.3 Employer Profile (`/employer/<slug>/`)

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
- **SEO:** Dynamic title "{Employer} H-1B & PERM Sponsorship Data | Visa Bulletin", description with filings count, approval rate, median salary. Canonical URL set.
- **Performance:** Page payload (stats + chart data) cached per employer/filters; cache timeout from settings.

---

### 1.4 Job Title Directory (`/job-titles/`)

**Purpose:** Browse job titles by popularity (filing count).

**Implemented capabilities:**

- **Listing:** Paginated list of job title clusters with `slug` and `total_filings > 0`. Excludes clusters without slug.
- **Summary:** Aggregate stats (total titles, total filings, average salary) when available.
- **Featured:** "Popular" job titles (e.g. top 12 by total filings) for quick access.
- **Display:** For each cluster: canonical title, slug link to profile, total filings, median/avg salary when available.
- **SEO:** Indexable directory; each row links to `/job-title/<slug>/`.

---

### 1.5 Job Title Profile (`/job-title/<slug>/`)

**Purpose:** Market analysis for a single job title (cluster).

**Implemented capabilities:**

- **Resolve slug:** Slug matches `JobTitleCluster.slug`. If not found, attempts match by normalized title and redirects to canonical cluster slug (301). Otherwise 404.
- **Market overview (from cluster + stats):**
  - Total filings (uses cluster-level total so it matches directory "Popular Job Titles")
  - Median salary, percentiles
  - Top employers for this role (with links to employer profiles)
  - **Experience vs salary** – When any salary records in the cluster are linked to a `JobTitle` with a non-empty `experience_level`, the profile shows a breakdown by level (count and median salary per level, plus an optional histogram overlay). Data comes from `JobTitle.experience_level` (extracted from raw title, e.g. "Senior", "II", "Manager"). In practice, many clusters have only one distinct level (or only "Unspecified"), so the section often shows a single segment; clusters with multiple levels (e.g. Senior + Junior + Unspecified) would show a multi-segment comparison.
- **Charts:** Salary distribution, geography, trends (built by `build_job_title_profile_charts`).
- **Related job titles:** Other titles in the same cluster (raw title variants).
- **Similar job titles:** Other clusters whose canonical title shares the first word (e.g. "Software" → "Software Engineer", "Software Developer"); limited (e.g. top 5 by filing count).
- **Filters (query params):**
  - **years** – 1–20 (default 5)
  - **program** – `h1b`, `perm`, or `all`
  - **level** – Experience level or `all` / `unspecified`
- **SEO:** Dynamic title "{Job Title} Salary Data & Market Analysis | Visa Bulletin", description with total filings and median salary. Canonical URL set.
- **Performance:** Cached per cluster/filters; cache timeout from settings.

**Experience vs salary – data and examples (checked against local DB; prod may differ):**

- **JobTitle** has an `experience_level` field (extracted from raw title: entry, junior, mid, senior, staff, principal, lead, manager, director, or roman i–v). In a recent local DB: ~56K `salary_job_title` rows had a non-empty `experience_level`; ~202K `salary_record` rows were linked to those job titles.
- **Where it shows:** The "Experience vs salary" section appears when the cluster's salary records include at least one linked to a job title with a non-empty level (or only "Unspecified"). In the same local DB, no cluster had **multiple** distinct experience levels among its records—each cluster had either all Unspecified or a single level (e.g. all "Senior" or all "II"). So the section often renders with **one segment** (e.g. "Senior", "II", or "Unspecified") rather than a multi-bar comparison.
- **Example job title profiles that show the section (one segment):**
  - **Senior Software Engineer** – `https://visa-bulletin.us/job-title/senior-software-engineer/` — one level: Senior (~8.9K records, ~\$143K avg in sample).
  - **Software Development Engineer II** – `https://visa-bulletin.us/job-title/software-development-engineer-ii/` — one level: II (~12K records, ~\$119K avg in sample).
- **To verify on production:** Run `bazel run //:run_sql` (or the same query on prod DB) and use:
  - Experience-level counts: `SELECT experience_level, COUNT(*) FROM salary_job_title WHERE COALESCE(experience_level, '') != '' GROUP BY experience_level ORDER BY COUNT(*) DESC;`
  - Clusters with at least one non-empty level and their breakdown:  
    `SELECT jtc.slug, jt.experience_level, COUNT(sr.id), ROUND(AVG(sr.wage_annual)::numeric,0) FROM salary_record sr JOIN salary_job_title jt ON sr.job_title_entity_id = jt.id JOIN salary_job_title_cluster jtc ON jt.canonical_cluster_id = jtc.id WHERE jtc.slug IS NOT NULL AND sr.wage_annual > 0 GROUP BY jtc.slug, jt.experience_level ORDER BY jtc.slug, COUNT(sr.id) DESC LIMIT 30;`

---

### 1.6 Autocomplete APIs

**Company autocomplete** – `GET /api/company-autocomplete/?q=<query>&limit=20`

- Returns JSON array of `{ name, slug, count }` for employer clusters whose `canonical_name` contains the query (case-insensitive). Excludes "Unknown" and clusters without slug. Ordered by total filing count (LCA + PERM) then name. Minimum 2 characters for `q`.

**Job title autocomplete** – `GET /api/job-title-autocomplete/?q=<query>&limit=20`

- Returns JSON array of `{ title, slug, total_filings }` for job title clusters whose `canonical_title` contains the query. Uses precomputed `total_filings_recent` (e.g. last 5 years). Minimum 2 characters for `q`.

**Company autocomplete** is used by the salary search form (employer filter), the employer directory search box, and the employer profile "Search for another employer" box. **Job title autocomplete** is used by the salary search form (job title/keywords), the job title directory search box, and the job title profile "Search for another profession" box. Both can be reused for future UI (e.g. comparison tools).

---

### 1.7 Sitemaps & Robots

**Robots:** `robots.txt` allows all crawlers and points to the sitemap URL.

**Sitemap:** Single XML sitemap listing:

- Static: `/`, `/salaries/`, `/employers/`, `/job-titles/`, `/faq/`, `/about/`, `/contact/`
- Category landing pages: `/employment-based/`, `/family-sponsored/`, and per-country under each
- Employer profile URLs: `/employer/<slug>/` for clusters with slug and `total_lca_count >= 5`, ordered by LCA count, capped at 10,000
- Job title profile URLs: `/job-title/<slug>/` for clusters with slug and `total_filings >= 10`, ordered by filing count, capped at 10,000

This supports SEO and discovery of employer/job title pages by search engines.

---

### 1.8 Static & Supporting Pages

- **FAQ** – `/faq/`
- **About** – `/about/`
- **Contact** – `/contact/`
- **Dashboard** – `/` (visa bulletin dashboard; employment-based/family-sponsored category and country landing pages use the same view with different parameters)

These are linked from the main site and included in the sitemap.

---

### 1.9 Data & Backend (Relevant to "What's Implemented")

- **Models:** `SalaryRecord`, `WorksiteRecord`, `Employer`, `EmployerCluster`, `JobTitle`, `JobTitleCluster` (see `models/salary.py`, `models/job_title.py`).
- **Employer clustering:** Canonical employer names and slugs; profile pages use cluster-level stats.
- **Job title clustering:** Canonical job titles and slugs; stats and "related/similar" use cluster-level data.
- **Pipeline:** Data ingest (LCA, PERM, worksite files), employer/job title clustering, and scripts such as `update_employer_stats`, `update_job_title_cluster_stats`, `populate_job_title_slugs` keep counts and slugs up to date. Cache is cleared after refresh (e.g. via `clear_cache` script) so directory and profile pages reflect new data.

---

## Part 2: Step-by-Step Promotion Strategy (What's Already Live)

The following sequence promotes **only** what exists today: salary search, employer directory and profiles, job title directory and profiles, autocomplete, and sitemaps. (Worksite search exists but is not linked from the main site and is not promoted; see Appendix A.) Use the drafts as-is or adapt to your voice and current numbers.

**Production data (as of February 2026):**

- **Salary records (searchable):** 1.54M (non-worksite, with valid wage, employer ≠ Unknown)
- **Employer clusters (profiles):** 221K (with slug, has LCA or PERM filings)
- **Job title clusters (profiles):** 114K (with slug, total_filings > 0)
- **Example employer (tweet 7 / journalist):** Microsoft – 36,635 filings, median salary ~\$122K, slug `microsoft-corporation` → https://visa-bulletin.us/employer/microsoft-corporation/
- **Top job title by filings:** Software Developers, Applications – 192K filings, slug `software-developers-applications`
- **Striking comparison:** Google ~\$127K median vs Cognizant ~\$77K median (similar volume); useful for journalist "pay gap" angle.

Refresh these numbers on prod before a campaign: run the same queries (see "How to verify" in Part 1) or query `salary_record`, `salary_employer_cluster`, `salary_job_title_cluster` counts and top employers.

---

### Step 1: Reddit – r/h1b (and r/immigration if allowed)

**Goal:** Reach H-1B and green card seekers; drive traffic and bookmarks.

**When:** Week 1, Day 1 (or first day of "launch").

**Draft post (copy-paste ready; fill [BRACKETS]):**

```text
Title: I built a free searchable database of H-1B & PERM salaries from DOL data – 1.5M records

Body:

I've been using the public DOL disclosure files for a while and finally put together a site where you can search and browse the data without downloading spreadsheets.

What you can do:
• Search salaries by job title, company, state, visa program (H-1B vs PERM), and year: https://visa-bulletin.us/salaries/
• Browse employers and open a profile per company (filings, approval rate, median salary, top roles, by state, trends): https://visa-bulletin.us/employers/
• Browse job titles and open a profile per role (total filings, median salary, top employers, geography, similar titles): https://visa-bulletin.us/job-titles/

Data comes from official DOL LCA and PERM disclosures (1.5M+ records, 220K+ employers, 114K+ job titles). No paywall, no signup. I run it as a side project for the immigration community.

If you're negotiating an offer or comparing companies, the employer and job title pages are the most useful. Hope it helps.
```

**Checklist before posting:**

- [ ] Confirm all three links return 200 and show data. (Refresh production data block above if numbers are stale.)
- [ ] Read subreddit rules; ensure "no self-promotion" or "self-promo" rules allow one clear, useful post; add disclaimer if required (e.g. "I built this").

---

### Step 2: Reddit – r/immigration (if separate from Step 1)

**Goal:** Reach a broader immigration audience (family-based, students, etc.) who may still care about employer sponsorship and salary transparency.

**When:** Week 1, Day 2 (or 24h after r/h1b to avoid cross-posting the same day).

**Draft post:**

```text
Title: Free H-1B & PERM salary database from DOL data – search by company, job title, state

Body:

There's a lot of DOL disclosure data out there but it's not easy to search. I built a free site that indexes it so you can:

• Search H-1B and PERM salaries by job title, employer, state, and year
• See per-company stats: total filings, approval rate, median salary, top job titles, geographic breakdown
• See per-job-title stats: total filings, median salary, top employers, similar roles

All from official DOL data, no login. Links:
Salaries: https://visa-bulletin.us/salaries/
Employers: https://visa-bulletin.us/employers/
Job titles: https://visa-bulletin.us/job-titles/

Might be useful if you're researching employers or comparing offers.
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
1/ I built a free, searchable database of 1.5M H-1B & PERM salaries from official DOL data.

No spreadsheets. No signup. Just search by company, job title, or state.

https://visa-bulletin.us/salaries/

2/ You can see per-company profiles: total filings, approval rate, median salary, top job titles, and where they hire (by state).

Example – search "Google" or go to employers and open any company:
https://visa-bulletin.us/employers/

3/ You can also see per-job-title profiles: how many filings, median salary, top employers, and similar roles.

Useful when comparing offers or researching a role:
https://visa-bulletin.us/job-titles/

4/ Data = LCA + PERM disclosure files from the Department of Labor. Same data that's public, but indexed and filterable.

H-1B vs PERM, by year, by state – all in one place.

5/ I run this as a side project for the immigration community. No ads, no paywall.

If you find it useful, bookmark it or share with someone job hunting or negotiating.

6/ Quick links:
• Salary search: https://visa-bulletin.us/salaries/
• Employers: https://visa-bulletin.us/employers/
• Job titles: https://visa-bulletin.us/job-titles/

7/ Example: Microsoft has 36,635 H-1B/PERM filings in the data, median salary ~$122K. Top role: Software Developers, Applications. (From https://visa-bulletin.us/employer/microsoft-corporation/)

8/ Built with Django, Postgres, and the same public DOL files you could download yourself – just made it queryable and linked employer/job title profiles so you don't have to.

9/ If you're on H-1B or going through PERM, hope this helps with offer comparison and employer research. Feedback welcome.

10/ Summary: Free H-1B & PERM salary DB (1.5M records) → https://visa-bulletin.us/salaries/ — search by company, job title, state. Employer & job title profiles with stats and trends. No signup.
```

**Checklist:**

- [ ] Refresh production data block above if numbers are stale before posting.
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

If you work in immigration, HR, or recruiting, you might find it useful for benchmarking or candidate conversations. If you're negotiating an offer, the employer and job title pages can help.

Link: https://visa-bulletin.us/salaries/

#H1B #PERM #Immigration #SalaryTransparency #DOL
```

**Checklist:**

- [ ] Confirm link works; optionally add one employer or job title profile link in a comment.
- [ ] Adjust hashtags to your usual style if needed.

---

### Step 5: Journalist / outlet outreach (email)

**Goal:** One or two stories or mentions in immigration, tech, or business outlets.

**When:** Week 1, Day 4–5 (after Reddit/Twitter so you can say "recently launched" or "getting traction on Reddit").

**Draft email (send individually; personalize [Publication] and [Angle]):**

```text
Subject: New free tool: searchable H-1B & PERM salary database (DOL data)

Hi [Name / "the team"],

I built a free, public database that makes DOL H-1B and PERM disclosure data searchable – 1.5M records, 220K+ employers, 114K+ job titles. I thought it might be useful for [Publication]'s coverage of [immigration / tech hiring / salary transparency].

What's live:
• Salary search: filter by employer, job title, state, visa program, year
• Employer profiles: total filings, approval rate, median salary, top roles, geographic breakdown, trends
• Job title profiles: market size, median salary, top employers, similar roles
• All from official DOL data; no paywall or signup

Link: https://visa-bulletin.us/salaries/

[Optional: I can share headline-ready stats – e.g. Microsoft leads with 36,635 filings (~$122K median); Google ~$127K vs Cognizant ~$77K median for similar volume – or a short methodology note. Happy to provide screenshots or a quick call if useful.]

Thanks,
[Your name]
[Your email]
```

**Checklist:**

- [ ] Replace [Publication] and [Angle]; use a real name if possible.
- [ ] Prepare 2–3 concrete stats (e.g. "Top employers: Microsoft 36.6K filings, Google 27.5K, Amazon 25.1K"; "Google ~$127K median vs Cognizant ~$77K") and attach or paste in a short follow-up.
- [ ] Target 5–10 outlets (e.g. TechCrunch, Bloomberg Law, Law360, Vox Recode, The Verge, local tech/immigration beat reporters).

---

### Step 6: Hacker News (Show HN)

**Goal:** Technical audience and possible front-page traffic.

**When:** Week 2, Day 1 (or when you have one or two Reddit/Twitter replies to cite as "early feedback").

**Draft post:**

```text
Title: Show HN: Searchable H-1B & PERM salary database from DOL disclosure data

Body:

I built a site that indexes public DOL LCA and PERM data so you can search and browse without downloading spreadsheets.

• Search: https://visa-bulletin.us/salaries/ — by job title, company, state, program (H-1B/PERM), year
• Employer profiles: https://visa-bulletin.us/employers/ — per-company stats (filings, approval rate, median salary, top roles, by state)
• Job title profiles: https://visa-bulletin.us/job-titles/ — per-role stats (filings, median salary, top employers)

Stack: Django, Postgres, employer/job title clustering to dedupe names. Data is refreshed from DOL files periodically. No login, no ads.

I run it for the immigration community; feedback from HN would be valuable.
```

**Checklist:**

- [ ] Post as "Show HN" and expect moderation; avoid marketing language.
- [ ] Be ready to answer technical questions (stack, scaling, data pipeline) in the thread.

---

### Step 7: Follow-up and reuse

**Goal:** Keep momentum and reuse content.

- **Reddit:** When someone asks "where can I check H-1B salaries?" or "how do I compare employers?", reply with a short sentence + link to https://visa-bulletin.us/salaries/ or the relevant employer/job title page. Don't spam; one helpful reply per thread.
- **Twitter/X:** Quote-tweet your own thread with one new stat (e.g. "Update: [X] employers now in the database" or "Most-searched job title this week: [Y]" if you add analytics later).
- **Journalists:** If no reply in 5–7 days, one short follow-up email: "Re: searchable H-1B/PERM database – happy to send 2–3 headline-ready stats or a 1-pager if that's useful."
- **Email list / newsletter:** If you have one, add one paragraph to the next issue: "I launched a free H-1B & PERM salary search and employer/job title profiles from DOL data: https://visa-bulletin.us/salaries/."

---

## Part 3: Quick reference – URLs and one-liners

**For social bios, link trees, or signatures:**

- **One link:** https://visa-bulletin.us/salaries/
- **One-liner:** "Free searchable H-1B & PERM salary database from DOL data – by company, job title, and state."
- **Longer:** "Search 1.5M H-1B and PERM salaries from DOL data. 220K+ employer and 114K+ job title profiles with filings, approval rates, and median pay. No signup."

**Key URLs:**

| Page            | URL                                      |
|-----------------|-------------------------------------------|
| Salary search   | https://visa-bulletin.us/salaries/        |
| Employers       | https://visa-bulletin.us/employers/       |
| Employer profile| https://visa-bulletin.us/employer/<slug>/ |
| Job titles      | https://visa-bulletin.us/job-titles/      |
| Job title profile | https://visa-bulletin.us/job-title/<slug>/ |
| FAQ             | https://visa-bulletin.us/faq/             |
| About           | https://visa-bulletin.us/about/           |
| Contact         | https://visa-bulletin.us/contact/         |

---

## Part 4: What's not implemented (out of scope for this doc)

The following are **not** built yet; do not promise them in promo:

- Employer "grades" or report cards
- Employer comparison tool (side-by-side)
- Rankings/leaderboards (e.g. "Top 100 by salary")
- User accounts, alerts, or saved searches
- Export or API for third parties
- Cost-of-living adjusted salary views
- Demographics (country of chargeability, education) on profile pages

Stick to: search, employer profiles, job title profiles, directories, autocomplete, and sitemaps.

---

## Appendix A: Worksite Search (`/worksites/`)

**Status:** Implemented but **not reachable from the main site** (no nav or footer link) and **not actively supported**. Do not promote it in launch materials. The URL exists and the view works if you know it; it is **not** included in the sitemap.

### Implemented capabilities (for reference)

**Purpose:** Search worksite location data from DOL Worksites disclosure files.

- **Filters**
  - **q** – Job title / keyword (job_title, soc_title, worksite_city)
  - **state** – Worksite state (2-letter code)
  - **city** – Worksite city (substring match)
  - **program** – `h1b`, `perm`, or all
  - **year** – Fiscal year or all
- **Results:** Paginated list with worksite city/state, job title, wage, program, year.
- **Stats:** When any filter is applied, shows total count and avg/min/max salary for the filtered set.
- **SEO:** Title "Worksite Location Data | U.S. Immigration Data", description for search engines.

**Data scope:** `WorksiteRecord` model (separate table from employer-centric `SalaryRecord`).

**URL:** https://visa-bulletin.us/worksites/

---

### How worksite data differs from salary records, and eventual use case

**Salary records** (LCA/PERM employer files) are **employer-centric**: each row has employer name, job title, worksite city/state, wage, etc. Use case: "Which companies sponsor? What do they pay? Where do they hire?" — i.e. search by company, analyze employer patterns, and power employer/job title profiles.

**Worksite records** come from **separate DOL Worksites disclosure files** with a **different structure**: they focus on **worksite location** (city, state, zip) and job title, and do **not** carry meaningful employer information (worksite files use a different case-number prefix and no employer columns in the same format). So you cannot search or filter worksite data by employer; it is purely location + role. See **`docs/department_of_labor/WORKSITE_FILES_DESIGN.md`** for the full design: data model, file format, and why worksite data was split into `WorksiteRecord` instead of mixing with `SalaryRecord`.

The **eventual unique use case** for worksite data is **location-first analytics**: e.g. "How many H-1B/PERM filings for [job title] in [city] or [state]?" and "What's the salary distribution by metro or region?" without an employer dimension — useful for relocation decisions, regional job market analysis, and geographic salary comparisons. Today's `/worksites/` view is a basic implementation of that idea; it is not linked from the main page and is not part of the supported product surface until the design in `WORKSITE_FILES_DESIGN.md` is fully adopted and the UI is promoted.

---

---

## Part 5: Pre-Launch Assessment (March 2026)

### Traffic & Usage Analysis

#### Overall Site Traffic (GoatCounter, Dec 2025 – Mar 21 2026)

| Month | Page Views | Notes |
|-------|-----------|-------|
| Dec 2025 | 23,177 | Baseline (visa bulletin core product only) |
| Jan 2026 | 15,452 | Low month |
| Feb 2026 | 91,170 | 6× spike — Feb visa bulletin release + predictions launch |
| Mar 2026 (partial, 21 days) | 34,430 | On track for ~50k full month |
| **Total** | **164,229** | |

Peak day: Feb 19, 2026 — **2,729 Google clicks** (GSC) coinciding with visa bulletin release.

#### Salary/Employer Product Traffic (GoatCounter, top pages)

| Page | Views | Notes |
|------|-------|-------|
| `/salaries/` | 1,142 | Salary search |
| `/employers/` | 918 | Employer directory |
| `/job-titles/` | 616 | Job title directory |
| `/about/` | 1,294 | High — users checking credibility |
| `/faq/` | 1,090 | High — users trying to understand data |
| `/contact/` | 246 | |

**Key insight:** Salary/employer pages account for ~2,700 views (1.6% of total). The site's traffic is overwhelmingly driven by visa bulletin predictions (85%+). The salary product is essentially undiscovered — no promotion has happened yet, traffic is purely from organic Google discovery and site navigation.

#### Google Search Console (Dec 20, 2025 – Mar 19, 2026)

**Total:** 25,128 clicks / 1,476,714 impressions / 1.7% CTR / avg position 8.1

**Traffic by content type:**

| Content | Clicks | Impressions | CTR | Notes |
|---------|--------|-------------|-----|-------|
| Homepage (visa bulletin) | 22,290 | 1,184,783 | 1.88% | 89% of all clicks |
| `/employment-based/india/` | 1,026 | 48,022 | 2.14% | India EB predictions |
| **`/salaries/`** | **29** | **4,515** | **0.64%** | Almost no search clicks yet |
| **`/employers/`** | **11** | **29,925** | **0.04%** | 30K impressions, almost zero clicks |
| Employer profiles (`/employer/*`) | ~100 | ~5,000 | ~2% | Long-tail: specific company searches |
| Job title profiles (`/job-title/*`) | ~50 | ~5,000 | ~1% | Long-tail: specific role searches |

**Top search queries driving salary/employer clicks:**

| Query | Clicks | Impressions | CTR | Position |
|-------|--------|-------------|-----|----------|
| perm database | 12 | 186 | 6.45% | 7.28 |
| perm salary database | 6 | 51 | 11.76% | 3.73 |
| green card salary database | 8 | 40 | 20% | 3.48 |
| visa salary database | 1 | 15 | 6.67% | 7 |
| perm database search | 1 | 19 | 5.26% | 7.79 |
| perm search by employer | 1 | 6 | 16.67% | 8 |
| [specific employer names] | ~50 | ~2,000 | ~2.5% | varied |
| [specific job title salaries] | ~30 | ~3,000 | ~1% | varied |

**Interpretation:** The salary/employer product has almost zero organic search traffic because:
1. No backlinks or social signals yet (no promotion done)
2. Pages are new to Google (indexed Dec 2025 – Jan 2026)
3. Domain authority built entirely on visa bulletin content
4. `/employers/` gets 30K impressions but 0.04% CTR — the title/description may not match user intent well

**Positive signals:**
- "perm database" and "perm salary database" queries rank well (position 3-7) with good CTR — validates the PERM data angle
- Employer-specific queries (company name + "h1b" or "perm") are starting to appear
- The long tail of employer and job title profiles is growing

#### Geographic Breakdown (GSC)

| Country | Clicks | % of Total | Notes |
|---------|--------|------------|-------|
| United States | 20,016 | 80% | Core audience |
| India | 1,209 | 4.8% | Key EB-2/EB-3 audience |
| Philippines | 715 | 2.8% | Family-sponsored heavy |
| Canada | 274 | 1.1% | |
| Kenya | 193 | 0.8% | |
| UK | 172 | 0.7% | |
| Pakistan | 167 | 0.7% | |
| UAE | 145 | 0.6% | |

80% US-based — perfect for salary/employer data promotion (H-1B holders and job seekers are primarily US-based).

#### Device Split (GSC)

| Device | Clicks | Impressions | CTR |
|--------|--------|-------------|-----|
| Mobile | 15,428 | 819,941 | 1.88% |
| Desktop | 9,498 | 638,883 | 1.49% |
| Tablet | 202 | 17,890 | 1.13% |

61% mobile — salary search and employer profiles must work well on mobile.

---

### Production Feature Verification (March 21, 2026)

**All core salary/employer features are live and working:**

| Feature | Status | URL |
|---------|--------|-----|
| Salary search | ✅ 200 | `/salaries/` |
| Employer directory | ✅ 200 | `/employers/` |
| Job title directory | ✅ 200 | `/job-titles/` |
| Employer profiles | ✅ 200 | `/employer/<slug>/` |
| Job title profiles | ✅ 200 | `/job-title/<slug>/` |
| Company autocomplete | ✅ Working | `/api/company-autocomplete/` |
| Job title autocomplete | ✅ Working | `/api/job-title-autocomplete/` |
| Worksites (hidden) | ✅ 200 | `/worksites/` (not linked) |
| Sitemap | ✅ Present | `/sitemap.xml` |
| Predictions page | ❌ 404 | `/predictions/employment_based/` |

**Employer profile enhanced features (all verified on Microsoft):**

| Feature | Status |
|---------|--------|
| Base Salary Only disclaimer | ✅ Present |
| Sponsorship Breakdown (H-1B vs PERM) | ✅ Present |
| Filing Pace by Program | ✅ Present |
| Processing Time stats/trend | ✅ Present |
| Recent Filing Activity | ✅ Present |
| Salary Distribution chart | ✅ Present |
| Top Job Titles | ✅ Present |
| Geography (filings by state) | ✅ Present |

**The product is feature-complete for launch.** All items marked as "DONE" in the revised launch strategy are confirmed live.

---

### Pre-Promo Recommendations

#### Critical: Do Before Launch

1. **Verify `case_submitted` / `decision_date` backfill status on prod.** The revised strategy lists this as unchecked. Processing time and filing pace sections show on the Microsoft page, so this may already be partially done. Verify coverage: if <50% populated, the sections may show incomplete data for smaller employers.

2. **Refresh data counts in promo materials.** The existing drafts use "1.5M records, 220K employers, 114K job titles" from Feb 2026. Before posting, re-query prod for current counts.

3. **Fix `/employers/` GSC CTR problem.** 30K impressions but 0.04% CTR suggests the meta title/description doesn't match what users searching for employer sponsorship info expect. Consider A/B testing the meta description to emphasize "H-1B & PERM sponsorship history" rather than just "employer directory."

#### High-Impact Easy Wins (implement before promo)

1. **Employer rankings/leaderboard page** (`/employers/rankings/` or `/employers/top/`)
   - A "Top H-1B Sponsors" and "Top PERM Filers" page would generate strong social sharing
   - Uses existing data (sort `EmployerCluster` by filing count)
   - Promo angle: "The Top 100 H-1B sponsors — and which ones actually file Green Cards"
   - Estimate: 1–2 days

2. **Employer comparison** (even a basic side-by-side)
   - `/compare/?employers=google-inc,cognizant-technology-solutions-corporation`
   - The Google ($127K) vs Cognizant ($77K) comparison is mentioned in promo drafts — make it a shareable link
   - Estimate: 2–3 days

3. **Link worksites from nav** (trivial)
   - `/worksites/` works but is hidden. Add a nav link or at minimum a sitemap entry.
   - Gives location-first angle for promo: "Where are H-1B jobs? Search by city and state."

4. **Internal cross-linking from visa bulletin pages to salary pages**
   - 85% of traffic lands on visa bulletin pages. Add contextual links like "Research employer sponsorship data →" on prediction pages. This is the single highest-leverage change for discovery.

#### Nice-to-Have (after initial launch)

- Cost-of-living adjusted salary views
- Country-of-origin data on PERM profiles
- User alerts for new filing activity at watched employers
- Export/API for researchers
- Employer "report card" grading system (full design exists in `docs/future_features/COMPANY_REPORT_CARD_DESIGN.md`)

#### Launch Timing Recommendation

The product is stable and ready. Key considerations:

- **Best day to launch:** Tuesday or Wednesday (higher engagement on Reddit, HN)
- **Best time:** 15:00 CET / 9:00 AM EST (per revised strategy)
- **February spike context:** The Feb 2026 traffic spike (91K views) was driven by the visa bulletin release cycle. Promoting salary data during a bulletin release week (when traffic is 3-5× normal) would maximize cross-pollination. The next bulletin releases are typically around the 8th-12th of each month.
- **Reddit karma:** Ensure the posting account has some history in r/h1b or r/immigration before the launch post.

#### Updated Promo Data Block (refresh before launch)

```
Production data (as of March 21, 2026):
- Salary records (searchable): 1,543,924
- Employer clusters (profiles): 221,032
- Job title clusters (profiles): 99,859
- Site traffic: 164K+ page views since Dec 2025
- Google indexed: 30K+ employer impressions, growing
- Example: Microsoft – 36,665 filings, median $119K
```

---

### Summary Assessment

| Dimension | Score | Notes |
|-----------|-------|-------|
| Feature completeness | **9/10** | All core features live, enhanced employer profiles with sponsorship breakdown |
| Data quality | **8/10** | 1.54M records, good clustering. `case_submitted` 73.8% populated; `decision_date` 99.2% — processing time and filing pace sections are live |
| SEO readiness | **7/10** | Sitemap and meta tags present. `/employers/` CTR needs work. New pages still building authority |
| Mobile readiness | **7/10** | 61% of traffic is mobile. Verify salary search UX on mobile before launch |
| Promo materials | **9/10** | Two complete strategy docs with ready-to-post drafts for Reddit, Twitter, LinkedIn, HN, journalists |
| Missing critical features | **None** | No blockers. Rankings and comparison are nice-to-have, not required |
| Traffic baseline | **Low** | 2,700 salary/employer views total — essentially zero organic discovery. All upside from promo |

**Verdict: Ready to launch.** The product is stable, feature-complete, and the promo materials are thorough. The biggest opportunity is internal cross-linking from the high-traffic visa bulletin pages to drive discovery before (and alongside) external promotion.

---

*Last updated: March 21, 2026. Align promo with current site and data; refresh record counts and example links before each campaign.*
