# Company Green Card Sponsorship Report Card - Comprehensive Design Document

## Executive Summary

A data-driven grading system that ranks companies on their green card sponsorship friendliness using objective metrics from DOL PERM data. Think "Glassdoor for Immigration" but based on government data, not user reviews.

**Key Metrics:**
- **Data Source:** 100% public DOL PERM disclosure data
- **Addressable Market:** 500K H-1B workers + 1M students choosing employers
- **Implementation Time:** 3-4 weeks (builds on Salary Database)
- **Traffic Potential:** 150K+ monthly visitors
- **PR Potential:** EXPLOSIVE - companies will respond publicly

---

## 1. Product Vision

### 1.1 Core Value Proposition

**For Job Seekers:**
"Choose employers who will actually sponsor your green card. See objective data on sponsorship speed, success rates, and support."

**For H-1B Workers:**
"Thinking of switching jobs? See which companies follow through on green card promises vs which delay forever."

**For Students:**
"Your first employer choice determines your immigration timeline. Choose wisely with data, not promises."

### 1.2 The Problem

**Current state:**
- Students accept jobs based on verbal promises ("we sponsor green cards")
- No way to verify if companies actually follow through
- Immigration timelines vary wildly by employer
- Word-of-mouth is unreliable

**What users ask:**
- "Does [Company] really sponsor green cards?"
- "How long until they file PERM?"
- "What's their approval rate?"
- "Do they pay for legal fees?"

### 1.3 Our Solution

**Objective Report Card based on PUBLIC data:**

**Grade Components (All from DOL data):**
1. **Volume:** How many PERMs filed per year?
2. **Speed:** Average time from H-1B to PERM filing
3. **Success Rate:** What % get approved?
4. **Salary:** Do they pay competitively?
5. **Consistency:** Do they sponsor reliably year-over-year?

**Example Grading:**
```
Google: A+
├─ PERM filings (2024): 1,247 (High volume)
├─ Average time to file: 4.2 months (Fast)
├─ Approval rate: 98% (Excellent)
├─ Average salary: $192K (Top 5%)
└─ 5-year consistency: Yes (sponsors every year)

Infosys: C
├─ PERM filings (2024): 421 (Low relative to H-1B count)
├─ Average time to file: 14.8 months (Slow)
├─ Approval rate: 89% (Below average)
├─ Average salary: $84K (Bottom 25%)
└─ 5-year consistency: Yes
```

---

## 2. Available Public Data & Metrics

### 2.1 What DOL PERM Data Includes

**For Each PERM Application:**
- ✅ Employer name
- ✅ Case status (Certified, Denied, Withdrawn)
- ✅ Filing date
- ✅ Decision date
- ✅ Job title
- ✅ Salary offered
- ✅ Location (city, state)
- ✅ Education requirement
- ✅ Experience requirement
- ✅ Employer FEIN (tax ID)

**What We CAN Calculate:**
- Number of PERMs filed per company per year
- Approval/denial rates
- Average salary by company
- Time from filing to decision (processing time)
- Year-over-year trends
- Geographic distribution

### 2.2 What Data Is MISSING (Cannot Calculate)

**❌ NOT in public data:**
- Time from H-1B hire to PERM filing (company-specific delay)
- Whether company pays legal fees
- Internal company policies
- Employee satisfaction
- I-140 filing speed after PERM
- Support during process

**⚠️ Must Be Estimated or Skipped:**
- "Time to file" requires matching H-1B to PERM by person (no unique ID)
- "Pays legal fees" = would need user reviews (not in scope for v1)
- "Support quality" = qualitative (need crowdsourcing)

### 2.3 Honest Metrics We CAN Provide (v1)

**Tier 1: Direct from PERM Data (100% Objective)**

1. **Sponsorship Volume Grade**
   ```
   Formula: PERMs filed in 2024
   - A: 500+ filings
   - B: 100-499 filings
   - C: 20-99 filings
   - D: 5-19 filings
   - F: <5 filings
   ```

2. **Approval Rate Grade**
   ```
   Formula: (Certified / Total Filed) × 100
   - A: 95%+ approval
   - B: 90-94%
   - C: 85-89%
   - D: 80-84%
   - F: <80%
   ```

3. **Salary Competitiveness Grade**
   ```
   Formula: Company avg salary vs national avg for same role
   - A: Top 20% (pays above market)
   - B: Top 40% (competitive)
   - C: Average (50th percentile)
   - D: Bottom 30% (below market)
   - F: Bottom 20% (significantly underpays)
   ```

4. **Consistency Grade**
   ```
   Formula: Sponsors in 4+ of past 5 years?
   - A: Every year, growing volume
   - B: Every year, stable
   - C: 4/5 years
   - D: 3/5 years
   - F: Sporadic (<3/5 years)
   ```

5. **Overall Grade**
   ```
   Weighted average:
   - Volume: 25%
   - Approval Rate: 25%
   - Salary: 30%
   - Consistency: 20%
   ```

**Tier 2: Contextual Metrics (Calculable)**

6. **Relative H-1B to PERM Conversion**
   ```
   Formula: (PERM filings / H-1B filings) × 100
   
   Example:
   - Google: 3,456 H-1Bs, 1,247 PERMs = 36% conversion
   - Infosys: 29,847 H-1Bs, 421 PERMs = 1.4% conversion
   
   Grade:
   - A: >30% (most H-1Bs get PERM sponsored)
   - B: 20-30%
   - C: 10-20%
   - D: 5-10%
   - F: <5% (red flag)
   ```

7. **Processing Speed** (DOL side only)
   ```
   Formula: Median days from PERM filing to decision
   - A: <180 days (6 months)
   - B: 180-270 days (6-9 months)
   - C: 270-365 days (9-12 months)
   - D: 365-540 days (1-1.5 years)
   - F: >540 days (>1.5 years)
   
   Note: This is DOL processing, not company delay
   ```

---

## 3. Technical Implementation

### 3.1 Database Schema (Extends Salary DB)

```sql
-- Company aggregated data
CREATE TABLE company_profiles (
    id SERIAL PRIMARY KEY,
    name_canonical VARCHAR(255) UNIQUE NOT NULL,
    slug VARCHAR(255) UNIQUE NOT NULL,  -- URL-friendly
    
    -- Volume metrics
    h1b_count_2024 INTEGER DEFAULT 0,
    perm_count_2024 INTEGER DEFAULT 0,
    h1b_to_perm_ratio DECIMAL(5, 2),  -- Conversion percentage
    
    -- Quality metrics
    perm_approval_rate DECIMAL(5, 2),
    avg_salary DECIMAL(12, 2),
    median_salary DECIMAL(12, 2),
    
    -- Grades
    grade_volume CHAR(1),
    grade_approval CHAR(1),
    grade_salary CHAR(1),
    grade_consistency CHAR(1),
    grade_overall CHAR(1),
    
    -- Metadata
    industry VARCHAR(100),
    headquarters_state VARCHAR(2),
    year_founded INTEGER,
    
    -- Timestamps
    data_last_updated TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Historical company data
CREATE TABLE company_historical (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id),
    fiscal_year INTEGER NOT NULL,
    h1b_count INTEGER,
    perm_count INTEGER,
    approval_rate DECIMAL(5, 2),
    avg_salary DECIMAL(12, 2),
    
    UNIQUE(company_id, fiscal_year)
);

-- Company grade changelog (for "grade improved" notifications)
CREATE TABLE company_grade_history (
    id SERIAL PRIMARY KEY,
    company_id INTEGER REFERENCES company_profiles(id),
    grade_overall CHAR(1),
    recorded_at TIMESTAMP DEFAULT NOW()
);
```

### 3.2 Grade Calculation Algorithm

```python
# lib/company_grader.py

def calculate_company_grade(company_name: str, fiscal_year: int) -> CompanyGrade:
    """Calculate objective grade from PERM data."""
    
    # Get all PERMs for this company
    perms = SalaryRecord.objects.filter(
        source='perm',
        employer_name_normalized=company_name,
        fiscal_year=fiscal_year
    )
    
    # Get H-1Bs for conversion rate
    h1bs = SalaryRecord.objects.filter(
        source='h1b',
        employer_name_normalized=company_name,
        fiscal_year=fiscal_year
    )
    
    # 1. Volume Grade
    perm_count = perms.count()
    grade_volume = grade_volume_score(perm_count)
    
    # 2. Approval Rate Grade
    certified = perms.filter(case_status='Certified').count()
    approval_rate = (certified / perm_count) * 100 if perm_count > 0 else 0
    grade_approval = grade_approval_score(approval_rate)
    
    # 3. Salary Grade (vs national median for same job titles)
    company_salaries = perms.values_list('annual_salary', flat=True)
    company_median = statistics.median(company_salaries)
    
    # Compare to national median for these job titles
    job_titles = perms.values_list('job_title_normalized', flat=True).distinct()
    national_median = calculate_national_median(job_titles, fiscal_year)
    
    salary_percentile = percentileofscore(national_median, company_median)
    grade_salary = grade_salary_score(salary_percentile)
    
    # 4. Consistency Grade (5-year history)
    historical_years = get_years_with_perms(company_name, last_n_years=5)
    grade_consistency = grade_consistency_score(historical_years)
    
    # 5. H-1B to PERM Conversion
    h1b_count = h1bs.count()
    conversion_rate = (perm_count / h1b_count * 100) if h1b_count > 0 else 0
    
    # Overall Grade (weighted)
    overall_score = (
        grade_volume * 0.20 +
        grade_approval * 0.25 +
        grade_salary * 0.35 +
        grade_consistency * 0.20
    )
    
    return CompanyGrade(
        volume=grade_volume,
        approval=grade_approval,
        salary=grade_salary,
        consistency=grade_consistency,
        conversion_rate=conversion_rate,
        overall=score_to_letter_grade(overall_score)
    )
```

### 3.3 UI Design

**Company Report Card Page:**

```
┌────────────────────────────────────────────────────────────┐
│                      Google LLC                            │
│                  Overall Grade: A+                         │
│                  ⭐⭐⭐⭐⭐                                    │
└────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Grade Breakdown (2024 Data)                                │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  📊 Sponsorship Volume: A                                   │
│      1,247 PERM applications filed                          │
│      Top 0.1% (among 50,000+ employers)                     │
│                                                             │
│  ✅ Approval Rate: A                                         │
│      98% of PERMs approved                                  │
│      Above industry average (92%)                           │
│                                                             │
│  💰 Salary Competitiveness: A+                              │
│      $192,340 average salary                                │
│      Top 5% nationally for sponsored roles                  │
│                                                             │
│  📈 Consistency: A+                                          │
│      Sponsored 1,000+ PERMs annually (2020-2024)            │
│      Trend: Growing (+15% year-over-year)                   │
│                                                             │
│  🔄 H-1B to PERM Conversion: A                              │
│      36% of H-1B workers get PERM sponsored                 │
│      Above industry average (18%)                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Salary Data by Role                                        │
├─────────────────────────────────────────────────────────────┤
│  Software Engineer                                          │
│    Median: $185,000 | Range: $145K - $285K | Count: 847    │
│                                                             │
│  Data Scientist                                             │
│    Median: $175,000 | Range: $135K - $240K | Count: 234    │
│                                                             │
│  Product Manager                                            │
│    Median: $165,000 | Range: $125K - $210K | Count: 187    │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Geographic Distribution                                    │
├─────────────────────────────────────────────────────────────┤
│  [Map visualization]                                        │
│  CA: 78% (972 PERMs)                                       │
│  WA: 15% (187 PERMs)                                       │
│  NY: 7% (88 PERMs)                                         │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  5-Year Trends                                              │
├─────────────────────────────────────────────────────────────┤
│  [Line chart: PERM filings 2020-2024]                      │
│  2020: 876 PERMs                                           │
│  2021: 932 PERMs                                           │
│  2022: 1,045 PERMs                                         │
│  2023: 1,124 PERMs                                         │
│  2024: 1,247 PERMs                                         │
│  Trend: +42% growth over 5 years                           │
└─────────────────────────────────────────────────────────────┘

[View Salary Details] [Compare with Other Companies]
```

---

## 2. Competition Analysis

### 2.1 Direct Competitors

#### MyVisaJobs.com
**What They Do:**
- Company profiles with H-1B/PERM counts
- Historical data
- "Green card sponsorship rating"

**Their Strengths:**
- Established (10+ years)
- Comprehensive data
- Large company database

**Their Weaknesses:**
- **TERRIBLE UX** (cluttered, overwhelming)
- Ads everywhere
- Rating methodology unclear
- No clear grading system
- Mobile experience poor
- Slow page loads

**Our Advantages:**
- **10x better UX** (clean, modern design)
- Clear grading methodology (transparent)
- Letter grades (A-F) vs vague "rating"
- Mobile-first
- Ad-free
- Fast loading
- Integrated with visa bulletin

#### H1BGrader.com (if it exists)
**Search for competitors with "grading" systems**

**Our Advantages:**
- More comprehensive metrics
- Better data visualization
- Company comparison tools
- Integration with salary database

### 2.2 Indirect Competitors

#### Glassdoor
**Strengths:**
- User reviews
- Salary data (user-reported)
- Company culture insights

**Weaknesses:**
- NOT specific to immigration
- Self-reported data (unreliable)
- No green card metrics

**Our Advantages:**
- **Immigration-specific**
- Government-verified data
- Objective metrics (not opinions)

#### Blind (Team Blind app)
**Strengths:**
- Verified employees
- Honest discussions
- Immigration questions

**Weaknesses:**
- Anecdotal, not systematic
- Hard to aggregate insights
- No structured data

**Our Advantages:**
- Quantitative, not qualitative
- Comprehensive historical data
- Searchable and comparable

### 2.3 Positioning Statement

```
"The objective, data-driven way to evaluate employers for 
green card sponsorship. 

Not opinions. Not promises. Just government data.

See which companies actually follow through on sponsoring 
green cards, and which ones delay or fail."
```

---

## 3. Technical Implementation

### 3.1 Data Processing Pipeline

**Step 1: Link H-1B to PERM (Fuzzy Matching)**

This is the KEY technical challenge. We need to estimate "time to file PERM" but there's no unique ID linking H-1B to PERM.

**Matching Strategy:**
```python
def match_h1b_to_perm(h1b_record, perm_records):
    """
    Fuzzy match H-1B to PERM using:
    - Employer name (exact)
    - Job title (similar)
    - Location (same city/state)
    - Salary (within 10%)
    - Timeframe (PERM filed 6-36 months after H-1B)
    """
    potential_matches = perm_records.filter(
        employer_name_normalized=h1b_record.employer_name_normalized,
        job_title_normalized__similar_to=h1b_record.job_title_normalized,
        state=h1b_record.state,
        annual_salary__gte=h1b_record.annual_salary * 0.9,
        annual_salary__lte=h1b_record.annual_salary * 1.1,
        decision_date__gte=h1b_record.decision_date + timedelta(months=6),
        decision_date__lte=h1b_record.decision_date + timedelta(months=36)
    )
    
    # This gives us APPROXIMATE time-to-file estimates
    return potential_matches.first()  # Best match
```

**⚠️ Limitation:** This is estimation, not perfect matching. Must disclose methodology.

**Alternative (More Honest):** 
Skip "time to file" metric for v1, only use metrics directly calculable:
- Volume
- Approval rate
- Salary
- Consistency

### 3.2 API Endpoints

```python
# webapp/views.py

@cache_page(3600 * 24)  # Cache 24 hours
def company_report_card(request, company_slug):
    """
    GET /company/google/report-card/
    """
    company = get_object_or_404(CompanyProfile, slug=company_slug)
    
    context = {
        'company': company,
        'grades': company.grades,
        'metrics': {
            'perm_count': company.perm_count_2024,
            'approval_rate': company.perm_approval_rate,
            'avg_salary': company.avg_salary,
            'conversion_rate': company.h1b_to_perm_ratio
        },
        'historical': company.get_historical_data(),
        'top_roles': company.get_top_sponsored_roles(limit=10),
        'geographic': company.get_geographic_distribution(),
        'peer_comparison': get_peer_companies(company, limit=5)
    }
    
    return render(request, 'company_report_card.html', context)


@cache_page(3600 * 6)  # Cache 6 hours
def company_rankings(request):
    """
    GET /companies/rankings/?sort=overall_grade&industry=tech
    """
    industry = request.GET.get('industry', 'all')
    sort_by = request.GET.get('sort', 'overall_grade')
    
    companies = CompanyProfile.objects.filter(
        perm_count_2024__gte=20  # Minimum threshold
    )
    
    if industry != 'all':
        companies = companies.filter(industry=industry)
    
    # Sort
    sort_mapping = {
        'overall_grade': '-grade_overall',
        'volume': '-perm_count_2024',
        'salary': '-avg_salary',
        'approval': '-perm_approval_rate'
    }
    companies = companies.order_by(sort_mapping.get(sort_by, '-grade_overall'))
    
    return render(request, 'company_rankings.html', {
        'companies': companies[:100],
        'industry': industry
    })


@cache_page(3600)
def company_compare(request):
    """
    GET /companies/compare/?companies=google,amazon,meta
    """
    company_slugs = request.GET.get('companies', '').split(',')
    companies = CompanyProfile.objects.filter(slug__in=company_slugs[:5])
    
    comparison_data = []
    for company in companies:
        comparison_data.append({
            'name': company.name_canonical,
            'grade': company.grade_overall,
            'perm_count': company.perm_count_2024,
            'approval_rate': company.perm_approval_rate,
            'avg_salary': company.avg_salary,
            'conversion_rate': company.h1b_to_perm_ratio
        })
    
    return render(request, 'company_compare.html', {
        'companies': comparison_data
    })
```

### 3.3 URL Structure (SEO-Optimized)

```
/companies/                          → Company rankings (all)
/companies/tech/                     → Tech companies only
/companies/healthcare/               → Healthcare companies
/companies/rankings/a-grade/         → All A-grade companies

/company/google/                     → Google profile (overview)
/company/google/report-card/         → Full report card
/company/google/salaries/            → Salary breakdown
/company/google/history/             → Historical trends

/compare/google-vs-amazon/           → Direct comparison
```

---

## 4. Go-to-Market Strategy

### 4.1 Launch Timeline

**Week 1: Stealth Development**
- Calculate grades for top 100 tech companies
- Build UI
- No announcement

**Week 2: Private Beta**
- Share with 20 trusted users
- Get feedback on grading fairness
- Refine methodology

**Week 3: Reddit Launch**
- Create provocative post
- Include controversial findings
- Drive initial traffic

**Week 4-8: Media Blitz**
- Pitch to TechCrunch, Business Insider, Bloomberg
- Create embeddable rankings widget
- Reach out to immigration lawyers
- SEO optimization

### 4.2 Launch Content Strategy

**Reddit Launch Post (r/h1b, r/cscareerquestions):**

**Title:** "I graded 10,000 companies on green card sponsorship using government data. Here's what I found."

**Content:**
```
TL;DR: I analyzed DOL PERM data to grade companies A-F on how 
good they are at sponsoring green cards.

Methodology:
- Sponsorship volume (how many PERMs filed)
- Approval rate (% that get approved)
- Salary competitiveness (vs market)
- 5-year consistency (reliable or sporadic)

Some findings:

🏆 Best Companies (A+ Grade):
- Google: 1,247 PERMs, 98% approval, $192K avg salary
- Microsoft: 967 PERMs, 97% approval, $178K avg
- Apple: 834 PERMs, 96% approval, $182K avg

⚠️ Lowest Grades (C or below):
- Infosys: 421 PERMs (1.4% of H-1Bs), 89% approval, $84K avg
- Cognizant: 312 PERMs (0.9% of H-1Bs), 87% approval, $82K avg

🚩 Red Flags to Watch:
- Low H-1B to PERM conversion (<5%) = company rarely sponsors
- Low volume = limited experience with process
- Low approval rate (<90%) = sloppy applications

Full database: visa-bulletin.us/companies

Thoughts? Should I add other metrics?
```

**Expected:** 1000-2000 upvotes, 10-20K visitors, explosive discussion

### 4.3 Viral Content Calendar

**Week 1:**
- Reddit launch post
- Twitter thread: "Top 10 / Bottom 10 companies"
- LinkedIn: Professional analysis post

**Week 2:**
- "Best Tech Companies for Green Cards - 2024"
- Embed in r/cscareerquestions wiki
- Email immigration lawyers

**Week 3:**
- "Outsourcing Firms vs Tech Companies: Data Analysis"
- Pitch to Bloomberg: "Immigration wage gap revealed"
- Create infographic for social media

**Week 4:**
- "State-by-State Rankings"
- "Best Companies in Texas, California, New York"
- Local media outreach

**Month 2:**
- "Do FAANG companies sponsor equally?"
- Company-specific deep dives
- Partner with immigration advocacy groups

### 4.4 Seeding Strategy

**Target Communities:**

**1. Reddit (Days 1-7):**
- r/h1b (125K members) - PRIMARY
- r/cscareerquestions (4M members) - HUGE
- r/Immigration (235K members)
- r/India (500K members) - filter by tech
- r/developersIndia (450K members)
- r/Philippines (300K members)
- r/ABCDesis (Indian Americans, 150K)

**Posting Strategy:**
- Different angle for each subreddit
- Data-driven, not promotional
- Invite discussion/feedback
- Respond to all comments

**2. Twitter/X (Week 2+):**
```
Strategy: Hot takes + data

Tweet examples:
- "Netflix pays H-1Bs $385K. Infosys pays $78K. Both sponsor 
   green cards. This is why company choice matters."
   
- "I graded 10,000 companies on green card sponsorship. Only 
   47 got an A grade. Here's why..."
   
- "PSA for international students: Before accepting an offer, 
   check the company's grade at [link]. Could save you years."
```

**3. LinkedIn (Week 2+):**
```
Professional analysis posts:

"Why Your Employer Choice Determines Your Green Card Timeline: 
A Data Analysis of 10,000 Companies"

Target: HR professionals, recruiters, career coaches
Format: Long-form analysis with data visualizations
CTA: Link to company rankings
```

**4. Hacker News (Week 3):**
```
Title: "Show HN: I graded companies on green card sponsorship 
using DOL data"

Post: Technical approach, open-source, invite feedback
Timing: Tuesday-Thursday morning PST (optimal)
```

**5. Product Hunt (Week 4):**
```
Title: "Company Green Card Report Card - Glassdoor for Immigration"
Tagline: "Grade 10,000 companies on green card sponsorship with 
government data"
Maker: @vyakunin
```

### 4.5 SEO Strategy

**Primary Keywords:**
- "company green card sponsorship" (2K searches/month)
- "[company name] green card" (100K+ combined)
- "best companies for green card" (3K/month)
- "h1b to green card companies" (1.5K/month)

**Long-Tail Strategy:**

Generate programmatic pages for:
1. **Every major company** (5,000 pages)
   - `/company/google/report-card/`
   - Target: "Google green card sponsorship"

2. **Industry rankings** (50 pages)
   - `/companies/tech/rankings/`
   - Target: "best tech companies for green card"

3. **Location-based** (50 states × industries)
   - `/companies/california/tech/`
   - Target: "California tech companies green card"

4. **Grade-based** (5 pages: A, B, C, D, F)
   - `/companies/a-grade/`
   - Target: "companies with best green card sponsorship"

**Content Strategy:**
- Each company page = unique meta description
- Auto-generate based on data: "Google sponsors 1,247 green cards annually with 98% approval rate. Grade: A+. See full report card."
- Rich snippets with schema.org

### 4.6 PR/Media Strategy

**Target Media Outlets:**

**Tier 1 (Tech Media):**
- TechCrunch
- The Verge
- Ars Technica
- Hacker News

**Tier 2 (Business Media):**
- Bloomberg
- WSJ
- Business Insider
- Forbes

**Tier 3 (Immigration Media):**
- Immigration Daily
- SHRM (HR magazine)
- Immigration Impact
- American Immigration Lawyers Association

**Angles for Each:**

**For Tech Media (TechCrunch):**
"Data Reveals: Tech Giants Excel at Green Card Sponsorship, Outsourcing Firms Lag Behind"
- Focus on company comparisons
- FAANG vs Infosys/TCS narrative
- Industry implications

**For Business Media (Bloomberg):**
"New Tool Grades Companies on Immigration Sponsorship"
- Business/HR angle
- Talent competition narrative
- Economic impact

**For Immigration Media:**
"Objective Data Finally Available for Employer Green Card Practices"
- Policy implications
- Transparency angle
- Worker empowerment

**Pitch Email Template:**
```
Subject: Data Story: Amazon vs Infosys on Green Card Sponsorship

Hi [Reporter Name],

I recently analyzed 5 years of DOL PERM data (500K+ records) 
and created an objective grading system for companies' green 
card sponsorship practices.

Some findings that might interest you:

1. Tech companies (Google, Microsoft) sponsor 36% of their 
   H-1B workers for green cards. Outsourcing firms: 1-2%.

2. Despite filing 30,000 H-1Bs, Infosys only filed 421 PERMs 
   in 2024 - a 1.4% conversion rate.

3. Salary disparity: Netflix pays $385K for H-1B software 
   engineers. Infosys: $78K.

I built a free tool that grades 10,000 companies: 
visa-bulletin.us/companies

Would this be of interest for [Publication]? Happy to provide:
- Exclusive access to data
- Custom analysis for your piece
- Interviews/quotes
- Embeddable visualizations

The database launches publicly next week, but I can give you 
early access for a story.

Best,
Vladimir
```

**Follow-up:**
- Send 2-3 days before public launch
- Offer exclusive early access
- Provide ready-to-use quotes and data
- Make it easy for them (do their work)

### 4.7 Controversy Strategy (Intentional PR)

**Why:** Controversial content spreads faster

**Strategy:** Tag companies in tweets with their grades

```
Tweet: "@Infosys filed 29,847 H-1Bs in 2024 but only 421 
PERMs (1.4% conversion). Meanwhile @Google converted 36% of 
H-1Bs to green cards. 

Grade: Infosys C, Google A+

See full report: [link]"
```

**Expected:**
- Companies may respond (free publicity)
- Reddit will amplify controversy
- Media picks up "company drama"
- Traffic spike

**Risk Mitigation:**
- All data is factual (government records)
- Clear methodology posted
- Link to raw data
- Frame as "objective analysis" not attack

---

## 5. Viral Mechanisms

### 5.1 Shareability Features

**1. Company Comparison Tool**
```
"Compare Your Offer: Google vs Amazon for Green Card"

Users share: "I got offers from Google (A+) and Amazon (A). 
Here's the data that helped me decide: [link]"
```

**2. Embeddable Badges**
```
Companies can embed on career pages (if they have good grades):

[Image: "A+ Green Card Sponsor - Visa Bulletin Dashboard"]

Badge code provided with attribution link
```

**3. Social Sharing Cards**
```
When sharing /company/google/:

[Image with company grade, key stats]
"Google: A+ for Green Card Sponsorship"
- 1,247 PERMs (2024)
- 98% approval rate  
- $192K avg salary

via visa-bulletin.us
```

### 5.2 Viral Triggers

**1. Rankings Lists**
- People love rankings
- "Best/Worst" posts get shared
- Triggers discussion/debate

**2. Controversy**
- Expose unfair practices
- Company drama = engagement
- Outsourcing firms will have low grades

**3. Utility**
- Job seekers bookmark and share
- "This tool saved me" testimonials
- Word-of-mouth growth

**4. Transparency**
- First to show this data openly
- "Finally someone did this"
- Fill obvious gap in market

### 5.3 Growth Loops

**Loop 1: Job Search → Share**
```
User searches company → Finds useful data → 
Shares with friends in same situation → New users search
```

**Loop 2: Reddit → More Reddit**
```
Post on r/h1b → Gets upvoted → 
Users ask about other companies → Return to post with data →
More engagement → Reddit algorithm boosts → Frontpage
```

**Loop 3: SEO → Organic**
```
Rank for "[Company] green card" → 
Organic traffic → Users explore other companies →
Internal links boost other company pages → More rankings
```

**Loop 4: Media → Credibility**
```
Media coverage → Legitimacy → 
Lawyers cite your data → More backlinks → 
Higher SEO → More traffic → More media attention
```

---

## 6. Ethical Considerations

### 6.1 Fairness in Grading

**Potential Criticisms:**
"Your grading system favors large tech companies!"

**Response:**
- Grades are based on objective metrics
- Methodology is transparent
- Small companies can get A grades too
- It's not our bias, it's the data

**Example: Small Company A-Grade**
```
BioTech Startup XYZ: A-
├─ PERMs (2024): 23 (appropriate for size)
├─ Approval rate: 96%
├─ Avg salary: $145K (competitive)
├─ Consistency: 5/5 years
└─ Conversion: 78% (excellent!)
```

### 6.2 Data Accuracy

**Challenge:** Employer name variations

**Solution:**
- Manual curation of top 1,000 companies
- Algorithm for name matching
- User feedback mechanism: "Report incorrect company grouping"
- Disclaimer: "Data aggregated from government records. Variations in company names may affect accuracy."

### 6.3 Privacy

**No privacy issues:**
- All data is already public (DOL)
- No individual names (only company/job aggregate)
- No PII collected

---

## 7. Success Metrics & KPIs

### 7.1 Traffic Metrics

**Week 1 Goal:**
- 5K unique visitors
- 500 company profile views
- 50 shares on social media

**Month 1 Goal:**
- 30K unique visitors
- 10K company profile views
- 5K searches performed
- 1K social shares

**Month 3 Goal:**
- 100K unique visitors
- 50K company profile views
- 50K searches
- First media mention

**Month 6 Goal:**
- 200K unique visitors
- Google page 1 for top keywords
- 5+ media mentions
- Cited by immigration lawyers

### 7.2 Engagement Metrics

**Measure:**
- Time on site (goal: >3 minutes)
- Pages per session (goal: >3)
- Bounce rate (goal: <40%)
- Search-to-company-profile click-through (goal: >20%)
- Company comparison usage (goal: 10% of visitors)

### 7.3 Impact Metrics

**Measure:**
- Media mentions
- Backlinks acquired
- Social shares
- Cited in Reddit comments
- Immigration lawyer referrals
- Companies responding/disputing grades

---

## 8. Phase 2 Features (Month 2-3)

### 8.1 Additional Metrics

**If we can collect supplementary data:**

**1. Glassdoor Integration**
- Fetch Glassdoor ratings
- Show correlation between work culture and sponsorship
- "A+ green card sponsor + 4.5★ Glassdoor = dream employer"

**2. LinkedIn Company Size**
- Normalize sponsorship volume by company size
- "Sponsorships per 1000 employees"
- Fairer to small companies

**3. Industry Benchmarking**
- Grade within industry context
- "A for healthcare" vs "A for tech" (different standards)

### 8.2 User-Generated Content (Optional)

**If community grows:**
- User reviews (verified employees only)
- "Did your employer pay legal fees?" Yes/No voting
- "How long until PERM filed?" crowdsourced timeline
- Tips and warnings

**Verification:**
- Require company email to review
- Rate limit to prevent spam
- Moderation queue

---

## 9. Revenue Potential (Future)

**Freemium Model:**

**Free:**
- View any company grade
- Basic search
- Compare up to 3 companies

**Premium ($9.99/month):**
- Unlimited company comparisons
- Historical data (10 years)
- Salary alerts for new filings
- Export company lists
- API access (basic)

**Enterprise ($299/month):**
- Bulk data access
- Custom reports
- White-label embeds
- Priority support
- API access (advanced)

**Expected Conversion:**
- 1% of 200K visitors = 2K subscribers
- $9.99 avg = $20K/month MRR
- Plus enterprise: ~$3K/month
- **Total: $23K/month by Month 6**

**Alternative Revenue:**
- Affiliate (immigration lawyers): $5K/month
- Sponsorships: $2K/month
- **Total with ads/affiliates: ~$30K/month**

---

## 10. Legal & Compliance

### 10.1 Terms of Service

**Include:**
- Data source attribution (DOL)
- No warranty on accuracy
- "For informational purposes only"
- Not legal advice
- Report inaccuracies: email

### 10.2 Company Disputes

**If company complains "your grade is wrong":**

**Response Template:**
```
Thank you for reaching out. Our grades are calculated from 
public DOL PERM disclosure data using the following 
methodology: [link].

Your company's data:
- PERMs filed (2024): [X] (DOL Case Numbers: [list])
- Approval rate: [Y]%
- Average salary: $[Z]

If you believe there's an error in the DOL data or our 
aggregation, please provide:
1. Specific case numbers with discrepancies
2. Corrected information with evidence

We'll review and update within 48 hours if warranted.

All grades are objective and based solely on government records.
```

### 10.3 Fair Use

**Using Company Names:**
- ✅ Allowed (nominative fair use)
- Companies cannot prevent use of their name in factual reporting
- Similar to Glassdoor, Yelp, etc.

**Using Company Logos:**
- ⚠️ Potential trademark issue
- Use sparingly, with attribution
- Or skip logos, use text only

---

## 11. Development Checklist

### Phase 1: Data & Grading (Week 1-2)
- [ ] Download PERM data (2020-2024)
- [ ] Download H-1B data (2020-2024)
- [ ] Create company_profiles table
- [ ] Build employer name normalization
- [ ] Calculate grades for all companies
- [ ] Create grade calculation tests
- [ ] Generate top 1000 company profiles

### Phase 2: UI (Week 2-3)
- [ ] Design company report card template
- [ ] Build company rankings page
- [ ] Build company comparison tool
- [ ] Create grade badge CSS
- [ ] Add search autocomplete for companies
- [ ] Mobile optimization
- [ ] Social sharing cards

### Phase 3: SEO (Week 3-4)
- [ ] Generate URL slugs for all companies
- [ ] Add schema.org markup
- [ ] Create meta descriptions (programmatic)
- [ ] Submit sitemap to Google
- [ ] Create canonical URLs
- [ ] Add breadcrumb navigation

### Phase 4: Launch (Week 4)
- [ ] Write Reddit launch post
- [ ] Create Twitter thread
- [ ] Write LinkedIn post
- [ ] Prepare press release
- [ ] Create media kit (PDF)
- [ ] Set up analytics tracking
- [ ] Launch!

### Phase 5: Iterate (Month 2+)
- [ ] Monitor feedback
- [ ] Fix reported issues
- [ ] Add requested features
- [ ] Create monthly reports
- [ ] Pitch to media
- [ ] Track SEO rankings

---

## 12. Integration with Existing Site

### 12.1 Cross-Linking Strategy

**Visa Bulletin Dashboard → Company Grades:**
```
User is viewing EB-2 India wait times (30 years)

Show message:
"💡 Choosing the right employer can save years. Companies 
with A+ grades typically file PERM faster.

[View Company Rankings]"
```

**Salary Database → Company Grades:**
```
User searches "Google Software Engineer salary"

Show:
"💼 Google pays $185K for this role (A+ for salary)

Want to see their full green card sponsorship grade?
[View Google Report Card]"
```

**Company Grade → Salary Database:**
```
User viewing Google report card

Include section:
"📊 Salary Details by Role
[View full salary data for Google]"
```

### 12.2 Navigation Updates

**Add to main nav:**
```
Home | Companies | Salaries | About | FAQ | Contact
       ↑          ↑
       New pages
```

**Footer links:**
```
Resources:
- Visa Bulletin Tracker
- Company Report Cards (NEW)
- Salary Database (NEW)
- Wait Time Calculator (coming soon)
```

---

## 13. Risk Mitigation

### 13.1 Company Backlash Risk

**Scenario:** Infosys threatens legal action over "unfair grade"

**Mitigation:**
1. **All data is factual** (government records)
2. **Methodology is objective** and documented
3. **First Amendment protection** (factual reporting)
4. **Precedent:** Glassdoor, Yelp successfully defended similar cases
5. **Backup:** Keep all raw data and calculations

**Prepare:**
- Terms of Service with disclaimers
- Documented methodology
- Legal defense fund (if needed)
- **Most likely:** Companies won't sue, just improve practices

### 13.2 Data Quality Risk

**Scenario:** Users report "Google has 50K PERMs, not 1,247!"

**Mitigation:**
- Link to raw DOL data
- Explain employer name matching
- Provide transparency: "If you find errors, report here"
- Manual review of top 100 companies

### 13.3 Maintenance Risk

**Scenario:** DOL changes data format, breaks parser

**Mitigation:**
- Automated tests for data format
- Quarterly refresh (not real-time dependency)
- Alerts if data import fails
- Manual review process

---

## 14. Success Stories (Projected)

**Month 1:**
"Student chooses Google over Amazon using our company grades"

**Month 3:**
"Immigration lawyer cites our data in blog post"

**Month 6:**
"Featured in TechCrunch: 'New Tool Grades Tech Companies on Immigration'"

**Month 12:**
"Company improves practices after receiving C grade, now B+"
"200K monthly visitors rely on company grades for career decisions"

---

## 15. Next Steps

### Immediate Actions:
1. **Download sample PERM data** to validate format
2. **Calculate grades for 5 test companies** (manual)
3. **Design company report card UI** (mockup)
4. **Get feedback** on grading methodology
5. **Decide:** Build salary database first or in parallel?

### Decision Points:
- **Sequential:** Build Salary Database (Week 1-2), then Company Grades (Week 3-4)
- **Parallel:** Build both simultaneously (share same data pipeline)

**Recommendation:** Sequential - salary database is easier, validate approach first.

---

*Last Updated: December 2025*

