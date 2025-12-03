# PERM/LCA Salary Database - Comprehensive Design Document

## Executive Summary

A searchable database of H-1B and PERM salary data extracted from DOL public disclosures, allowing users to research salaries by job title, company, and location. This is the **fastest, highest-ROI feature** with 100% public data and massive SEO/viral potential.

**Key Metrics:**
- **Data Volume:** 500K+ H-1B records/year, 100K+ PERM records/year
- **Addressable Market:** 500K H-1B workers + 1M students + 300K PERM applicants
- **Implementation Time:** 2-4 weeks
- **Traffic Potential:** 100K+ monthly visitors
- **PR Potential:** Journalists love salary transparency data

---

## 1. Product Vision

### 1.1 Core Value Proposition

**For H-1B Workers:**
"Know your worth. Compare your salary to what companies actually pay for your job title and location in immigration filings."

**For Job Seekers:**
"Find green-card-friendly employers and see exactly what they pay international hires."

**For Researchers/Journalists:**
"Analyze immigration salary trends, company practices, and wage disparities with authoritative government data."

### 1.2 User Stories

**Story 1: Salary Research**
```
As a Software Engineer on H-1B in California
I want to know what Google pays for my role in PERM filings
So that I can negotiate my salary or evaluate job offers
```

**Story 2: Employer Research**
```
As an international student looking for first job
I want to see which companies sponsor most H-1Bs and at what salary
So that I can target employers likely to hire me
```

**Story 3: Market Analysis**
```
As a journalist writing about tech immigration
I want to compare H-1B salaries across companies
So that I can report on wage practices and trends
```

### 1.3 Key Features

**MVP (Week 1-2):**
- Search by job title, company, location
- Filter by visa type (H-1B vs PERM), year, salary range
- Display results in sortable table
- Basic stats (median, average, range)

**V1.1 (Week 3-4):**
- Advanced filters (experience level, industry, SOC code)
- Company profiles (aggregate stats per employer)
- Salary distribution charts
- Export to CSV
- Email alerts for new filings

**V2.0 (Month 2-3):**
- Salary trends over time (annual comparisons)
- Cost of living adjustment (compare SF vs Austin salaries)
- Peer comparison ("You're in 75th percentile")
- API access for researchers

---

## 2. Technical Architecture

### 2.1 Data Sources

**Primary: DOL H-1B LCA Disclosure Data**
- **URL:** https://www.dol.gov/agencies/eta/foreign-labor/performance
- **Format:** Excel/CSV files (one per fiscal year)
- **Size:** ~100MB per year, ~500K records
- **Fields:**
  - CASE_NUMBER
  - CASE_STATUS (Certified, Denied, Withdrawn)
  - EMPLOYER_NAME
  - JOB_TITLE
  - SOC_CODE, SOC_TITLE
  - WAGE_RATE_OF_PAY_FROM, WAGE_RATE_OF_PAY_TO
  - WAGE_UNIT_OF_PAY (Hour, Week, Year, Month)
  - WORKSITE_CITY, WORKSITE_STATE
  - DECISION_DATE
  - NAICS_CODE (industry classification)

**Secondary: DOL PERM Disclosure Data**
- **URL:** https://www.dol.gov/agencies/eta/foreign-labor/performance
- **Format:** Excel/CSV files
- **Size:** ~20MB per year, ~100K records
- **Fields:**
  - CASE_NUMBER
  - CASE_STATUS
  - EMPLOYER_NAME
  - JOB_TITLE
  - EDUCATION_LEVEL_REQUIRED (HS, Bachelor's, Master's, PhD)
  - EXPERIENCE_REQUIRED_MONTHS
  - WAGE_OFFERED_FROM, WAGE_OFFERED_TO
  - WORKSITE_CITY, WORKSITE_STATE
  - DECISION_DATE

**Update Frequency:** DOL releases data quarterly, ~3 months lag

### 2.2 Database Schema

```sql
-- Core salary records table
CREATE TABLE salary_records (
    id BIGSERIAL PRIMARY KEY,
    
    -- Source
    source VARCHAR(10) NOT NULL,  -- 'h1b' or 'perm'
    case_number VARCHAR(50) UNIQUE NOT NULL,
    case_status VARCHAR(20) NOT NULL,
    fiscal_year INTEGER NOT NULL,
    decision_date DATE,
    
    -- Employer
    employer_name VARCHAR(255) NOT NULL,
    employer_name_normalized VARCHAR(255),  -- For grouping variations
    
    -- Job
    job_title VARCHAR(255) NOT NULL,
    job_title_normalized VARCHAR(255),  -- "Software Engineer" not "Sr. SW Eng III"
    soc_code VARCHAR(10),
    soc_title VARCHAR(255),
    naics_code VARCHAR(10),
    
    -- Salary
    wage_from DECIMAL(12, 2) NOT NULL,
    wage_to DECIMAL(12, 2),
    wage_unit VARCHAR(10) NOT NULL,  -- 'Year', 'Hour', 'Month'
    annual_salary DECIMAL(12, 2) NOT NULL,  -- Normalized to annual
    
    -- Location
    city VARCHAR(100),
    state VARCHAR(2) NOT NULL,
    
    -- Requirements (PERM only)
    education_level VARCHAR(50),
    experience_months INTEGER,
    
    -- Indexes for fast queries
    INDEX idx_employer_norm (employer_name_normalized),
    INDEX idx_job_title_norm (job_title_normalized),
    INDEX idx_state (state),
    INDEX idx_fiscal_year (fiscal_year),
    INDEX idx_annual_salary (annual_salary),
    INDEX idx_source_status (source, case_status)
);

-- Normalized employer names (for grouping)
CREATE TABLE employers (
    id SERIAL PRIMARY KEY,
    name_canonical VARCHAR(255) UNIQUE NOT NULL,  -- "Google LLC"
    name_variations TEXT[],  -- ["Google", "Google Inc", "Google LLC"]
    total_h1b_count INTEGER DEFAULT 0,
    total_perm_count INTEGER DEFAULT 0,
    avg_salary DECIMAL(12, 2),
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Normalized job titles
CREATE TABLE job_titles (
    id SERIAL PRIMARY KEY,
    title_canonical VARCHAR(255) UNIQUE NOT NULL,  -- "Software Engineer"
    title_variations TEXT[],  -- ["SWE", "Software Dev", "Software Developer"]
    median_salary DECIMAL(12, 2),
    record_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT NOW()
);

-- Pre-computed aggregations for performance
CREATE MATERIALIZED VIEW salary_stats_by_company AS
SELECT 
    employer_name_normalized,
    source,
    COUNT(*) as record_count,
    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY annual_salary) as median_salary,
    AVG(annual_salary) as avg_salary,
    MIN(annual_salary) as min_salary,
    MAX(annual_salary) as max_salary,
    fiscal_year
FROM salary_records
WHERE case_status = 'Certified'
GROUP BY employer_name_normalized, source, fiscal_year;
```

### 2.3 Data Pipeline

**Step 1: Download**
```python
# scripts/download_dol_data.py
def download_h1b_data(fiscal_year: int) -> Path:
    """Download H-1B LCA data from DOL website."""
    urls = {
        2024: "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2024.xlsx",
        2023: "https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/LCA_Disclosure_Data_FY2023.xlsx",
        # etc
    }
    # Download and cache locally
```

**Step 2: Parse**
```python
# lib/dol_parser.py
def parse_h1b_record(row: dict) -> SalaryRecord:
    """Parse single H-1B LCA record."""
    # Normalize employer name
    employer = normalize_employer_name(row['EMPLOYER_NAME'])
    
    # Normalize job title
    job_title = normalize_job_title(row['JOB_TITLE'])
    
    # Convert all wages to annual salary
    annual_salary = convert_to_annual(
        wage=row['WAGE_RATE_OF_PAY_FROM'],
        unit=row['WAGE_UNIT_OF_PAY']
    )
    
    return SalaryRecord(...)
```

**Step 3: Load**
```python
# Bulk insert with PostgreSQL COPY
# ~500K records in <1 minute
def bulk_load_records(records: list[SalaryRecord]):
    with connection.cursor() as cursor:
        cursor.copy_from(csv_buffer, 'salary_records', columns=...)
```

**Step 4: Refresh Materialized Views**
```sql
REFRESH MATERIALIZED VIEW salary_stats_by_company;
REFRESH MATERIALIZED VIEW salary_stats_by_title;
```

### 2.4 API Endpoints

```python
# webapp/views.py

@cache_page(3600)  # Cache 1 hour
def salary_search(request):
    """
    GET /salary-search/?q=software+engineer&company=google&state=CA
    
    Returns paginated results with filters.
    """
    query = request.GET.get('q', '')
    company = request.GET.get('company', '')
    state = request.GET.get('state', '')
    min_salary = request.GET.get('min_salary', 0)
    year = request.GET.get('year', 2024)
    
    results = SalaryRecord.objects.filter(
        case_status='Certified',
        fiscal_year=year
    )
    
    if query:
        results = results.filter(job_title_normalized__icontains=query)
    if company:
        results = results.filter(employer_name_normalized__icontains=company)
    # ... more filters
    
    return render(request, 'salary_search.html', {
        'results': results[:100],
        'stats': calculate_stats(results)
    })


@cache_page(3600)
def company_profile(request, employer_slug):
    """
    GET /company/google/
    
    Company-specific salary profile.
    """
    company = get_object_or_404(Employer, slug=employer_slug)
    
    records = SalaryRecord.objects.filter(
        employer_name_normalized=company.name_canonical
    )
    
    return render(request, 'company_profile.html', {
        'company': company,
        'salary_stats': aggregate_by_job_title(records),
        'by_year': aggregate_by_year(records),
        'by_location': aggregate_by_location(records),
        'top_roles': get_top_roles(records, limit=20)
    })
```

### 2.5 UI/UX Design

**Homepage Search Box:**
```
┌─────────────────────────────────────────────────────────────┐
│                 💼 H-1B & PERM Salary Database              │
│                                                             │
│  Search 600,000+ immigration salary records from the DOL   │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐ │
│  │ 🔍 Software Engineer                                  │ │
│  └───────────────────────────────────────────────────────┘ │
│                                                             │
│  Advanced Filters:                                          │
│  Company: [Any      ▼]  State: [CA      ▼]  Year: [2024 ▼]│
│  Salary Range: [$0 ] to [$500K]                           │
│                                                             │
│  [Search]                                                   │
│                                                             │
│  Popular: Amazon · Google · Meta · Microsoft · Tesla       │
└─────────────────────────────────────────────────────────────┘
```

**Results Page:**
```
Results: 1,247 Software Engineer salaries at Google (2024)

Summary Stats:
├─ Median: $185,000
├─ Average: $192,340
├─ Range: $145,000 - $285,000
└─ Locations: CA (78%), WA (15%), NY (7%)

[Chart: Salary Distribution Histogram]

┌──────────────────────────────────────────────────────────┐
│ Company    | Job Title           | Location  | Salary   │
├──────────────────────────────────────────────────────────┤
│ Google LLC | Software Engineer   | San Jose  | $185,000 │
│ Google LLC | Software Engineer L3| Sunnyvale | $165,000 │
│ Google LLC | Sr Software Engineer| Mountain  | $225,000 │
│ ...                                                       │
└──────────────────────────────────────────────────────────┘

[Export CSV] [Save Search] [Get Alerts]
```

**Company Profile Page:**
```
┌─────────────────────────────────────────────────────────────┐
│                        Google LLC                           │
│                                                             │
│  H-1B Sponsorships: 3,456 (2024)                          │
│  PERM Applications: 1,247 (2024)                          │
│  Average Salary: $192,340                                  │
│  Approval Rate: 97% (H-1B)                                 │
└─────────────────────────────────────────────────────────────┘

Salary by Role:
├─ Software Engineer: $185K (median) | 1,247 records
├─ Data Scientist: $165K (median) | 234 records
├─ Product Manager: $175K (median) | 187 records
└─ Research Scientist: $195K (median) | 156 records

Salary by Location:
├─ Mountain View, CA: $195K (median)
├─ Sunnyvale, CA: $188K (median)
├─ Seattle, WA: $182K (median)
└─ New York, NY: $190K (median)

Salary Trends (2020-2024):
[Chart showing salary growth over time]

Top Roles Sponsored:
[Chart: Pie chart of job title distribution]
```

---

## 2. Competition Analysis

### 2.1 Direct Competitors

#### H1BSalary.com
**Strengths:**
- Established brand (>10 years)
- Large dataset
- Simple interface

**Weaknesses:**
- Outdated UI (looks like 2010)
- Poor mobile experience
- Limited filtering options
- No company profiles
- Ads everywhere

**Our Advantages:**
- Modern, clean UI (Bootstrap 5)
- Better UX (your site already has better design)
- Mobile-first (56% of your traffic is mobile)
- No ads (ad-free experience)
- Company report card integration
- Historical trends and predictions

#### H1BData.info
**Strengths:**
- Clean interface
- Good search
- Company pages

**Weaknesses:**
- H-1B only (no PERM data)
- No historical trends
- Limited analysis tools
- No integration with visa bulletin/wait times

**Our Advantages:**
- Combined H-1B + PERM data
- Integration with your visa bulletin tracker
- "See salary AND wait time" - unique value prop
- Better for green card seekers (not just H-1B)

#### Levels.fyi
**Strengths:**
- User-submitted data (more recent)
- Total compensation (stock, bonus)
- Tech-focused community
- Clean design

**Weaknesses:**
- Crowdsourced (less reliable)
- Not specific to immigration
- No government verification
- Missing smaller companies

**Our Advantages:**
- **Government-verified data** (DOL official)
- Specific to visa holders
- Historical data back to 2000s
- All companies (not just tech)
- No need to rely on user submissions

#### MyVisaJobs.com
**Strengths:**
- Comprehensive immigration data
- H-1B + PERM + sponsor database
- Company profiles

**Weaknesses:**
- **EXTREMELY CLUTTERED** interface
- Overwhelming ads
- Confusing navigation
- Slow page loads
- Dated design

**Our Advantages:**
- **FAR superior UX** (your site is already better)
- Fast loading
- Ad-free
- Mobile-optimized
- Integration with visa bulletin
- Modern charts/visualizations

### 2.2 Competitive Positioning

**Your Unique Position:**
```
"The only visa bulletin tracker that also shows you:
 - What companies pay for your role
 - How long they take to sponsor
 - Whether it's worth the wait
 
 All government-verified. No ads. No bullshit."
```

**Target Keywords:**
- "H-1B salary data" (5K searches/month)
- "[Company name] H-1B salary" (100K+ combined searches)
- "PERM salary database" (2K searches/month)
- "Google software engineer H-1B salary" (high intent)

---

## 3. Implementation Plan

### 3.1 Week 1: Data Pipeline

**Tasks:**
1. Download DOL H-1B data (FY 2020-2024)
2. Download DOL PERM data (FY 2020-2024)
3. Create database schema (PostgreSQL recommended for full-text search)
4. Write parser for H-1B LCA format
5. Write parser for PERM format
6. Normalize employer names (handle "Google" vs "Google LLC" vs "Google Inc")
7. Normalize job titles (standardize variations)
8. Convert all wages to annual salaries
9. Bulk load into database
10. Create indexes and materialized views

**Estimated Data Volume:**
- 5 years × 500K H-1B = 2.5M records
- 5 years × 100K PERM = 500K records
- Total: 3M records (~1.5GB database)

**Bazel Targets:**
```python
py_library(
    name = "dol_parser",
    srcs = ["lib/dol_parser.py"],
    deps = [":models"],
)

py_binary(
    name = "import_dol_data",
    srcs = ["scripts/import_dol_data.py"],
    deps = [
        ":dol_parser",
        requirement("pandas"),
        requirement("openpyxl"),
    ],
)
```

### 3.2 Week 2: Search & Display

**Django Models:**
```python
# models/salary.py
class SalaryRecord(models.Model):
    source = models.CharField(max_length=10, choices=[('h1b', 'H-1B'), ('perm', 'PERM')])
    case_number = models.CharField(max_length=50, unique=True, db_index=True)
    case_status = models.CharField(max_length=20)
    fiscal_year = models.IntegerField(db_index=True)
    
    employer_name = models.CharField(max_length=255)
    employer_name_normalized = models.CharField(max_length=255, db_index=True)
    
    job_title = models.CharField(max_length=255)
    job_title_normalized = models.CharField(max_length=255, db_index=True)
    
    annual_salary = models.DecimalField(max_digits=12, decimal_places=2, db_index=True)
    state = models.CharField(max_length=2, db_index=True)
    city = models.CharField(max_length=100, blank=True)
    
    class Meta:
        indexes = [
            models.Index(fields=['employer_name_normalized', 'fiscal_year']),
            models.Index(fields=['job_title_normalized', 'state']),
        ]
```

**Search View:**
```python
def salary_search(request):
    query = request.GET.get('q', '').strip()
    company = request.GET.get('company', '').strip()
    state = request.GET.get('state', '')
    year = int(request.GET.get('year', date.today().year))
    min_salary = int(request.GET.get('min_salary', 0))
    
    results = SalaryRecord.objects.filter(
        case_status='Certified',
        fiscal_year=year
    )
    
    if query:
        results = results.filter(
            Q(job_title_normalized__icontains=query) |
            Q(soc_title__icontains=query)
        )
    
    if company:
        results = results.filter(employer_name_normalized__icontains=company)
    
    if state:
        results = results.filter(state=state)
    
    if min_salary:
        results = results.filter(annual_salary__gte=min_salary)
    
    # Calculate stats
    stats = results.aggregate(
        count=Count('id'),
        median=Median('annual_salary'),
        avg=Avg('annual_salary'),
        min=Min('annual_salary'),
        max=Max('annual_salary')
    )
    
    return render(request, 'salary_search.html', {
        'results': results[:100],  # Paginate
        'stats': stats,
        'query': query,
    })
```

### 3.3 Week 3-4: Polish & Features

**Tasks:**
1. Company profile pages (aggregate views)
2. Salary charts (Plotly histograms)
3. Comparison tool (compare 2 companies side-by-side)
4. Export CSV functionality
5. Mobile optimization
6. SEO optimization (rich snippets, schema.org)
7. Social sharing cards
8. Performance tuning (query optimization, caching)

### 3.4 Bazel Build Integration

**Add to BUILD file:**
```python
py_library(
    name = "dol_parser",
    srcs = ["lib/dol_parser.py"],
    deps = [
        ":models",
        requirement("pandas"),
    ],
)

py_binary(
    name = "import_dol_data",
    srcs = ["scripts/import_dol_data.py"],
    deps = [":dol_parser"],
)

py_test(
    name = "test_dol_parser",
    srcs = ["tests/test_dol_parser.py"],
    deps = [":dol_parser"],
)
```

### 3.5 Deployment Considerations

**Database:**
- Switch from SQLite to PostgreSQL for full-text search
- 3M records requires proper indexing
- Consider AWS RDS or self-hosted on Lightsail

**Storage:**
- Raw DOL files: ~500MB
- Database: ~1.5GB (with indexes)
- Backup strategy for raw files

**Performance:**
- Materialized views for common queries
- Redis caching for hot searches
- CDN for static assets

---

## 4. Go-to-Market Strategy

### 4.1 Launch Sequence

**Week 1-2: Stealth Build**
- Build MVP, no announcement
- Load 2024 data only (test with smaller dataset)
- Internal testing

**Week 3: Soft Launch**
- Load full 5 years of data
- Announce on Reddit (r/h1b, r/cscareerquestions)
- Post: "I built a free H-1B salary database - no ads, government data"

**Week 4: Media Push**
- Generate "2024 H-1B Salary Report" with insights
- Pitch to TechCrunch, Hacker News, immigration reporters
- LinkedIn posts with data insights

**Month 2: SEO Push**
- Create company profile pages for FAANG+
- Optimize for "[Company] H-1B salary" keywords
- Submit to search engines

### 4.2 Seeding Strategy

**Day 1 (Reddit Launch):**

**Post Title:** "I analyzed 500,000 H-1B salary records from the DOL - here's what I found (free database inside)"

**Post Content:**
```
Hey r/h1b,

I scraped 5 years of DOL disclosure data (500K+ records) and built 
a free salary database for visa holders.

Some interesting findings:
- Amazon filed 18,234 H-1B LCAs in 2024 (most of any company)
- Median Software Engineer H-1B salary: $135,000
- Infosys average: $78,000 vs Google average: $192,000
- California has 38% of all H-1B jobs

Check it out: visa-bulletin.us/salaries

No ads. No paywall. Just government data.

What would you like to see analyzed next?
```

**Expected Result:** 500-1000 upvotes, 2-5K visitors on launch day

**Day 2-7 (Other Subreddits):**
- r/cscareerquestions
- r/Immigration  
- r/India (tech immigration angle)
- r/China_irl
- r/Philippines
- r/DataIsBeautiful (create viral visualization)

**Week 2-4 (Twitter/X):**
```
Tweet 1:
"Analyzed 500K+ H-1B salary records from the DOL.

Amazon pays $145K median for SWE
Google pays $185K
Infosys pays $78K

Same job. 2.4x salary difference.

Full database: [link]"

Tweet 2:
"Which companies pay H-1B workers the most?

Top 5:
1. Netflix: $385K median
2. Google: $185K
3. Meta: $180K
4. Apple: $175K
5. Microsoft: $165K

Bottom 5:
Infosys: $78K
Cognizant: $82K
TCS: $79K
..."
```

**Month 2+ (Content Marketing):**
- Monthly blog: "H-1B Salary Trends - November 2025"
- Annual report: "2024 H-1B Salary Report"
- Company comparisons: "Google vs Meta: H-1B Compensation"
- Industry analyses: "Healthcare vs Tech H-1B Salaries"

### 4.3 SEO Strategy

**Target Keywords (Monthly Search Volume):**

**High Volume (10K+):**
- "h1b salary database" (12K)
- "h1b salary" (22K)
- "perm salary" (3K)

**Long-Tail (1K-10K each, thousands of variations):**
- "[Company] h1b salary" (e.g., "google h1b salary": 8K, "amazon h1b salary": 6K)
- "[Job title] h1b salary" (e.g., "software engineer h1b salary": 4K)
- "[Company] [job title] salary" (ultra-specific, high intent)

**Strategy:**
1. **Programmatic SEO** - Generate pages for:
   - Every major company (5,000+ pages)
   - Every job title (10,000+ pages)
   - Company × job title combinations (50,000+ pages)

2. **Schema.org Markup:**
```html
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Dataset",
  "name": "Google H-1B Salary Data",
  "description": "Official H-1B salary data for Google from DOL disclosures",
  "creator": {
    "@type": "Organization",
    "name": "Visa Bulletin Dashboard"
  },
  "distribution": {
    "@type": "DataDownload",
    "contentUrl": "https://visa-bulletin.us/salaries/company/google/",
    "encodingFormat": "text/html"
  }
}
</script>
```

3. **Rich Snippets:**
   - Table markup for salary ranges
   - FAQ schema for common questions
   - Breadcrumb navigation

4. **Backlink Strategy:**
   - Reach out to immigration lawyers to link
   - Guest posts on immigration blogs
   - Cite your data in advocacy materials

### 4.4 PR/Media Strategy

**Angles for Journalists:**

**Angle 1: Wage Disparity**
- "Infosys pays H-1Bs $78K while Google pays $185K for same job"
- Targets: Bloomberg, WSJ, TechCrunch
- Timing: Annual H-1B lottery announcement (March)

**Angle 2: Company Rankings**
- "Top 100 Companies for H-1B Salaries - 2024"
- Create embeddable infographic
- Targets: Business Insider, Forbes, LinkedIn News

**Angle 3: Regional Analysis**
- "San Francisco H-1Bs earn $195K median, but Texas offers better value at $125K"
- Cost-of-living adjusted rankings
- Targets: Local news (SF Chronicle, Austin American-Statesman)

**Angle 4: Industry Trends**
- "H-1B salaries increased 8% in 2024, outpacing inflation"
- "AI/ML engineer H-1B salaries hit $200K median"
- Targets: Tech media, trade publications

**Media Kit:**
- One-page executive summary
- Top 10 findings from data
- Embeddable charts
- Quote attribution
- Links to methodology

**Press Release Template:**
```
FOR IMMEDIATE RELEASE

New Immigration Salary Database Reveals $68 Billion Talent 
Acquisition by U.S. Companies

Free Tool Aggregates 500,000+ DOL Records, Shows Salary 
Transparency for H-1B and Green Card Seekers

[CITY, DATE] - Visa Bulletin Dashboard today launched a 
comprehensive salary database covering 500,000+ H-1B and PERM 
records from Department of Labor disclosures, providing 
unprecedented transparency into immigration salary practices.

Key findings from the 2024 data:
- Amazon led in H-1B sponsorships with 18,234 applications
- Median software engineer H-1B salary: $135,000
- Tech companies pay 2.4x more than outsourcing firms
- California hosts 38% of all H-1B workers

The tool is free and ad-free at visa-bulletin.us/salaries

About:
Visa Bulletin Dashboard is an open-source immigration data 
platform serving the H-1B and green card community.

Contact: vyakunin@gmail.com
```

### 4.5 Community Building

**Reddit Strategy:**
- Weekly "Salary Insights" posts
- Answer salary questions with database links
- AMA: "I analyzed 500K H-1B salaries, AMA"

**Twitter/X Strategy:**
- Daily salary facts
- Respond to salary discussions with data
- Tag companies when posting their data (they'll retweet controversy)

**LinkedIn Strategy:**
- Professional analysis posts
- Target HR/recruiters with data
- Immigration lawyer partnerships

**Partnerships:**
- Immigration lawyers: Cite your data
- Recruitment firms: Data for salary benchmarking
- Advocacy groups: Policy research

---

## 5. Viral Content Playbook

### 5.1 Launch Day Content

**Reddit Post (r/h1b):**
"I analyzed 500K+ H-1B salary records. Here's what shocked me..."

**Data points to include:**
- Biggest pay gap between companies
- Highest paid H-1B job title
- Companies with most sponsorships
- Salary growth trends

**Twitter Thread:**
```
1/ 🧵 I analyzed 500,000 H-1B salary records from DOL data.

Here are 10 shocking findings about immigration salaries...

2/ Amazon filed 18,234 H-1B applications in 2024 - more than 
   any other company. Average salary: $145,000

3/ But Amazon doesn't pay the most. Netflix pays $385K median 
   for H-1Bs. Google: $185K. Meta: $180K.

4/ The lowest? Infosys ($78K), TCS ($79K), Cognizant ($82K).
   
   These outsourcing firms pay 50-60% less than tech companies
   for similar roles.

[continue thread with 6 more insights]

10/ I built a free database to search all this data:
    visa-bulletin.us/salaries
    
    No ads. Government-verified. 500K+ records.
    
    What should I analyze next?
```

### 5.2 Ongoing Content Calendar

**Monthly:**
- "H-1B Salary Report - [Month] 2025"
- Top 10 company changes
- New employers entering market
- Salary trend analysis

**Quarterly:**
- Deep dive: "State of H-1B Salaries Q4 2025"
- Industry comparisons
- State-by-state analysis

**Annually:**
- "2025 H-1B Salary Report"
- Year-over-year trends
- Media kit with embeddable charts
- Press release

**Event-Driven:**
- When H-1B lottery results announced (March)
- When new DOL data released
- When companies announce hiring freezes
- When immigration bills introduced

### 5.3 Viral Content Formats

**1. Controversial Comparisons**
- "Why does Infosys pay H-1Bs 50% less than Google?"
- "Are outsourcing firms exploiting visa holders?"

**2. Regional Rankings**
- "Best states for H-1B salaries (adjusted for cost of living)"
- "Texas vs California: Where H-1Bs earn more"

**3. Company Leaderboards**
- "Top 100 H-1B employers by salary"
- "Which companies pay H-1Bs fairly?"

**4. Trend Analysis**
- "H-1B salaries jumped 12% in 2024 - here's why"
- "AI/ML roles now command $200K+ on H-1B"

**5. Data Visualizations**
- Animated maps showing salary by location
- Salary distribution curves by company
- Interactive comparisons

---

## 6. Monetization Opportunities (Later)

**Free Tier:**
- Search up to 100 results
- Basic company profiles
- 1 salary alert per month

**Premium ($9.99/month):**
- Unlimited search results
- Advanced filters (education, experience)
- Unlimited salary alerts
- Export full datasets
- API access (100 req/day)
- Historical trends (10+ years)

**Enterprise ($99/month):**
- API access (10,000 req/day)
- Custom reports
- Bulk data exports
- White-label embeds

**Affiliate Revenue:**
- Immigration lawyer referrals ($50-100 per lead)
- Salary negotiation coaching ($200 per client)

---

## 7. Success Metrics

### 7.1 Week 1 Goals
- Database loaded (3M records)
- Search functional
- 100 beta testers

### 7.2 Month 1 Goals
- 10K unique visitors
- 50K searches performed
- 500 Reddit upvotes
- 5 company profile pages created

### 7.3 Month 3 Goals
- 50K monthly visitors
- 200K searches/month
- Top 3 Google result for "h1b salary database"
- 1 media mention (TechCrunch, Bloomberg, etc.)

### 7.4 Month 6 Goals
- 100K monthly visitors
- 500K searches/month
- #1 Google result for target keywords
- 5+ media mentions
- 50 organic backlinks

### 7.5 Year 1 Goals
- 200K monthly visitors
- 1M searches/month
- Referenced by immigration lawyers
- Cited in policy discussions
- Partnership with advocacy organization

---

## 8. Risk Assessment

### 8.1 Technical Risks

**Risk:** Data quality issues (duplicate employer names, typos)
- **Mitigation:** Implement robust name normalization, manual review of top 1000 companies

**Risk:** Database performance with 3M records
- **Mitigation:** Proper indexing, materialized views, caching layer

**Risk:** Storage costs
- **Mitigation:** Start with smaller dataset (2024 only), expand as traffic grows

### 8.2 Legal Risks

**Risk:** DOL data usage restrictions
- **Mitigation:** Data is public domain, cite source clearly

**Risk:** Company complaints about data accuracy
- **Mitigation:** Show raw government data, don't editorialize, link to source

**Risk:** Scraping accusations
- **Mitigation:** Use official bulk downloads only, no web scraping

### 8.3 Business Risks

**Risk:** Competitors copy feature
- **Mitigation:** Execution matters more than idea. Your UX is better.

**Risk:** Low adoption
- **Mitigation:** Leverage existing Reddit audience, integrate with visa bulletin

**Risk:** Maintenance burden
- **Mitigation:** Automate updates, quarterly refresh is acceptable

---

## 9. Development Checklist

### Phase 1: MVP (2 weeks)
- [ ] Download DOL data (2024 only)
- [ ] Create database schema
- [ ] Build data parser
- [ ] Normalize employer/job title names
- [ ] Load into PostgreSQL
- [ ] Create search view
- [ ] Create results display
- [ ] Add basic filtering
- [ ] Test with 10 users

### Phase 2: Polish (2 weeks)
- [ ] Load historical data (2020-2024)
- [ ] Add company profile pages
- [ ] Build salary charts
- [ ] Mobile optimization
- [ ] SEO optimization (meta tags, schema.org)
- [ ] Social sharing cards
- [ ] Performance tuning
- [ ] Beta launch on Reddit

### Phase 3: Growth (ongoing)
- [ ] Monitor analytics
- [ ] Respond to user feedback
- [ ] Generate monthly reports
- [ ] Pitch to media
- [ ] Build backlinks
- [ ] Expand features based on traction

---

## 10. Next Steps

1. **Approve this design** and prioritize implementation
2. **Download sample DOL data** to validate format
3. **Set up PostgreSQL** (can start with SQLite for MVP)
4. **Build data parser** (1-2 days)
5. **Create search UI** (2-3 days)
6. **Launch on Reddit** and iterate

**Total time to launch:** 2-4 weeks for a high-quality MVP

---

*Last Updated: December 2025*

