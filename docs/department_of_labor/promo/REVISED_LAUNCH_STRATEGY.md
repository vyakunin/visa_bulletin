# H-1B & PERM Data: Revised Launch Strategy

**Premise:** You are not selling a "Negotiation Tool" (because of the missing stock/bonus data). You are selling a **"Sponsorship Security & Base Pay Benchmarking"** tool. Your competitive advantage over Levels.fyi is the **PERM (Green Card) data**—proving who actually supports long-term immigration, not just who pays the most cash.

**Time Zone Note:** You are in Berlin (CET). Your audience is US-based.

**Post Time:** 15:00 CET (9:00 AM EST) / 18:00 CET (9:00 AM PST).

Do not post in your morning.

---

## Phase 1: Pre-Flight (Do this immediately)

### The "Integrity" Badge -- DONE

Disclaimer text added to:
- `/salaries/` search card header
- Employer profile page header (below company name)
- Employer profile data source footer (enhanced with base-salary-only note)

### Employer Profile Enhancements -- DONE

New sections on every employer profile page (`/employer/<slug>/`):

- **Sponsorship Breakdown card** — H-1B count, PERM count, PERM ratio (color-coded: green >=20%, yellow >=5%, red <5%). Answers "does this company actually file PERMs?"
- **Recent Filing Activity** — Last filing date per program type (H-1B / PERM) and per top-5 job titles. Falls back to fiscal year when exact dates unavailable. Answers "when did they last file?"
- **Filing Pace by Program chart** — Quarterly (or annual fallback) filing volume split by H-1B vs PERM. Shows whether sponsorship activity is growing or shrinking.
- **Processing Time stats** — Filing-to-decision latency: median, average, P25-P75 range, with per-program breakdown. Answers "how long does this company's processing take?"
- **Processing Time Trend chart** — Quarterly median processing days over time. Shows if processing is getting faster or slower.

**Note:** Processing time and quarterly filing pace require `case_submitted` and `decision_date` backfill. As of March 2026, prod has 73.8% `case_submitted` coverage (1.14M / 1.54M records) and 99.2% `decision_date` coverage — both well above the pipeline smoke-test floor of 65%. These sections are live and showing data. No manual backfill needed; `populate_case_submitted.py` runs automatically in the refresh pipeline.

### Asset Generation

You cannot launch with text alone. Create these screenshots:

- **Asset A (The Histogram):** A screenshot of Microsoft's Employer Profile showing the "Salary Distribution" chart. (Shows density/validity).
- **Asset B (The Comparison):** A screenshot of Google's stats next to a WITCH company (e.g., Infosys or Tata). You can just take two screenshots and stitch them side-by-side in Paint/Figma. Label it: "High Base + PERM" vs "Low Base + H-1B Only".
- **Asset C (The Map):** A screenshot of the "Filings by State" map/chart from a major employer to show geographic breadth.
- **Asset D (Sponsorship Breakdown):** Screenshot of the new "Sponsorship Breakdown" card showing H-1B vs PERM counts and PERM ratio.
- **Asset E (Filing Pace):** Screenshot of the "Filing Pace by Program" chart showing H-1B vs PERM trends over time.

---

## Phase 2: The Launch (Social Media)

### Step 1: Reddit (The "Sponsorship" Angle)

**Subreddits:** r/h1b, r/immigration  
**Timing:** Tuesday or Wednesday, 15:30 CET.

**Title:** I indexed 1.5M DOL records. Check which companies actually file Green Cards (PERM) vs just H-1Bs.

**Body:**

```text
Most salary sites focus on Total Comp (RSUs/Bonuses). But as an immigrant, I care about two things they often miss:
1. What is the guaranteed Base Salary floor?
2. Will this company actually sponsor my Green Card (PERM), or just keep me on H-1B?

I built a free searchable database of 1.5M Dept of Labor filings to answer this.

**Important Data Note:** This is official DOL data, which means it lists **Base Salary Only**. It excludes RSUs and bonuses. For Big Tech, the numbers will look lower than Levels.fyi/Blind.

**However, it is the most accurate source to:**
* **Verify Sponsorship Patterns:** Every employer profile now shows a Sponsorship Breakdown: H-1B count, PERM count, and PERM ratio. Some companies hire thousands on H-1B but file almost zero PERMs.
* **See Filing Activity:** Check when a company last filed, how their filing pace is changing, and their processing times.
* **Check the "Floor":** See the legal prevailing wage minimums for your role/location.
* **Filter by State:** See where companies are actually filing LCAs (e.g., are they hiring remote in Texas or just California?).

**Links (No login/signup):**
* Search Salaries: https://visa-bulletin.us/salaries/
* Employer Profiles (See PERM vs H-1B stats): https://visa-bulletin.us/employers/

Hope this helps with your due diligence.
```

---

### Step 2: LinkedIn (The "Due Diligence" Angle)

**Goal:** Reach recruiters and passive job seekers.  
**Timing:** Thursday, 14:00 CET.

**Post Text:**

```text
Due diligence is critical when evaluating a visa-sponsored role.

While sites like Levels.fyi track total compensation, they often miss the immigration reality. I've indexed 1.5 million US Dept of Labor filings to build a free database of H-1B and PERM history.

It allows you to look under the hood of a potential employer.

🔍 What you can check:
1. PERM (Green Card) Volume: Every profile shows H-1B vs PERM breakdown with a PERM ratio. Does this employer support long-term residency, or is it a "churn and burn" H-1B shop?
2. Filing Activity: When did they last file? Is their sponsorship volume growing or shrinking? What titles are they filing for?
3. Base Salary Floors: Official base pay data submitted to the government (excludes RSUs/Bonuses).
4. Location Data: Where are they actually filing LCAs?

Before you interview, check the employer's profile to see their sponsorship breakdown and filing trends.

Link: https://visa-bulletin.us/employers/

#H1B #Immigration #TechCareers #DataTransparency
```

**Attachment:** Use Asset A (The Microsoft Histogram screenshot).

---

### Step 3: Twitter/X (The "Floor vs. Ceiling" Thread)

**Timing:** Wednesday, 16:00 CET.

**Thread:**

```text
1/ Negotiating a visa-sponsored job?

You need to know the Ceiling (Total Comp) AND the Floor (Guaranteed Base).

I built a free database of 1.5M Dept of Labor records to help you find the floor and verify Green Card sponsorship.

https://visa-bulletin.us/salaries/

[Attach Asset A: Chart Screenshot]

2/ ⚠️ Crucial Context: DOL data is **Base Salary Only**.

It does not include RSUs or sign-on bonuses. If you search "Google L4", the number will look low compared to Levels.fyi.

Why use this tool then? 👇

3/ Reason 1: Sponsorship Security.

You can search any employer and see their split between H-1B (temporary) and PERM (Green Card) filings.

Avoid companies that hire heavily on H-1B but rarely file for PERM.

Check your target company here: https://visa-bulletin.us/employers/

4/ Reason 2: The "Non-Tech" Reality.

Not everyone gets RSUs. For H-1B holders in Accounting, Healthcare, or Civil Engineering, Base Salary IS Total Comp.

This data is the source of truth for 90% of industries outside of FAANG.

5/ Reason 3: Location Truth.

"We allow remote work." Do they?

Check the employer profile to see the breakdown of filings by State. If 100% of their LCAs are in SF/NY, that "Remote in Ohio" offer might be shaky.

6/ It's free, no login, no paywall. Just a project to make government data accessible.

Search 1.5M records here: https://visa-bulletin.us/salaries/
```

---

## Phase 3: The "Blind" Strategy (High Intent)

**Platform:** Teamblind.com  
**Constraint:** You need a verified corporate email to post. Since you are at Snowflake, you should have access.  
**Tactics:** Do not make a main post (it might get flagged as spam). Instead, "Snipe" active conversations.

**Search Queries on Blind:**

- "H1B transfer"
- "Lowball offer"
- "Does [Company] sponsor green card?"

**Reply Template (Customize slightly each time):**

```text
You should check their actual filing history. According to DOL data, they filed [X] H-1Bs but only [Y] PERMs ([Z]% PERM ratio). Their median base salary filing for that title was $[W]k (obviously excludes stock). Their last PERM filing was [date/FY]. You can also see how their filing pace is trending.

Full breakdown here: https://visa-bulletin.us/employer/[slug]/
```

---

## Phase 4: Niche Communities (The "Non-Tech" Blue Ocean)

This is your highest potential for "Lowball Detection" because these industries generally do not have stocks/bonuses.

**Target:** r/accounting (Big 4 salaries are huge here), r/civilengineering, r/nursing.

**Draft for r/accounting:**

**Title:** I indexed public H-1B salary data for Big 4 and mid-tier firms (Base Salary Search)

**Body:**

```text
I know salary threads are popular here. I built a tool that indexes official Dept of Labor salary filings.

Since accounting compensation is mostly base salary (unlike tech), this data is highly accurate for checking if you are being paid market rate for your level (Senior, Manager, etc.).

You can search:

Deloitte/EY/PwC/KPMG: See the exact base salaries they listed on visa applications.

By State: Compare NY vs FL salaries.

Link: https://visa-bulletin.us/salaries/?q=accountant

(It's free, no login).
```

---

## Phase 5: Media Outreach (The "Data Drop")

**Strategy:** Do not pitch the "Tool." Pitch a **"Trend"** found in your data.

**Subject Line:** Data Tip: 2025 H-1B Base Salaries flatlining in [City/Sector]

**Email Draft:**

```text
Hi [Name],

I maintain a database of 1.5 million H-1B and PERM filings sourced from the Dept of Labor.

I was analyzing the recent data and noticed a trend that might fit your coverage on [Immigration/Tech Hiring]:

Trend: While filing volumes are high, the median Base Salary for "Software Engineers" in [State/Company] has [stagnated/dropped/increased] by [X]% compared to 2024.

I've indexed this data publicly if you want to verify or explore other companies.

Database: https://visa-bulletin.us/salaries/

Example Profile (Microsoft): https://visa-bulletin.us/employer/microsoft-corporation/

Data Note: This reflects Base Salary only (excludes RSUs), which provides a clear look at fixed labor costs without the noise of stock market fluctuations.

Happy to pull specific cuts of data (e.g., by city or specific job title) if you need them for a piece.

Best,
[Your Name]
```

**Who to send this to (The "Tech/Labor" Beat):**

- Natasha Mascarenhas (The Information / TechCrunch alumni) - Covers labor/startups.
- Pranav Dixit (Engadget/Generic Tech) - Often covers immigrant tech worker angles.
- The "Tips" Line at Rest of World: stories@restofworld.org (They cover the immigrant tech experience heavily).
- Editor at "H-1B grader" or similar blogs: They might link to you as a resource.

---

## Summary Checklist

- [x] UI: Add "Base Salary Only" disclaimer text on `/salaries/` and employer profiles.
- [x] UI: Sponsorship Breakdown card (H-1B vs PERM counts + ratio) on employer profiles.
- [x] UI: Recent Filing Activity section (last filing per program/title) on employer profiles.
- [x] UI: Filing Pace by Program chart (H-1B vs PERM trend) on employer profiles.
- [x] UI: Processing Time stats and trend chart on employer profiles.
- [x] DB: Composite indexes for filing-date-based queries (migration 0040).
- [ ] DB: Backfill `case_submitted` and `decision_date` on prod (run `populate_case_submitted.py`). Until then, processing time and quarterly pace sections are hidden.
- [ ] Assets: Screenshot Microsoft profile (Chart), Google vs WITCH (Comparison), Sponsorship Breakdown, Filing Pace.
- [ ] Reddit: Post to r/h1b at 15:30 CET.
- [ ] Blind: Find 3 recent threads about "Sponsorship" and drop a comment with data.
- [ ] Twitter: Post thread with chart image.
- [ ] Niche: Post to r/accounting with the "Big 4" angle.
