# I-129 Data Stories — Rigor Review (quantitative red-team)

**Date:** 2026-07-13 · **Reviewer role:** quantitative social scientist / labor economist pass
over stories (a) multi-registration, (b) gender pay gap, (c) lottery odds.
**Data:** prod `i129_petition` (372,841 rows, FY2021–2024, cap-subject selected-and-filed
I-129 petitions; all queries below run 2026-07-13 read-only on prod). External aggregates:
USCIS published registration/selection statistics (per-FY table mirrored by
[WSM Immigration](https://www.wsmimmigration.com/immigration-law-insights/2024/uscis-releases-fy-2025-h-1b-registration-statistics/),
[Gibney](https://www.gibney.com/alerts/immigration-by-the-numbers-key-stats-on-fy-2025-h-1b-cap-lottery-and-h-1b-alternatives/),
[Ogletree/NatLawReview FY2026](https://natlawreview.com/article/h-1b-registration-numbers-fy-2026-h-1b-cap-reveal-increase-selection-rate);
original source: USCIS "H-1B Electronic Registration Process" page, Akamai-blocked to non-browser clients).
**Attribution required everywhere:** "sourced from USCIS, obtained by Bloomberg" (Apache-2.0,
Bloomberg v. DHS FOIA release; same microdata as Borjas, NBER w34793).

**Universe reminder (must appear on every story page):** FY2021–2024, cap-subject lottery
petitions only, **selected-and-filed** petitions (NOT the 1.8M registration pool), frozen FOIA
snapshot. Per-beneficiary linking keys are 100% FOIA-redacted → aggregates only.

---

## Story (a) — Multi-registration trend

### 1. Confounds identified

1. **Selection bias in the denominator.** We observe selected+filed petitions. Pre-FY2025 the
   lottery was registration-based, so a beneficiary with k registrations had ≈ 1−(1−p)^k odds of
   selection — multi-registered beneficiaries are mechanically over-selected relative to the
   beneficiary pool, and the *composition of filed petitions* ≠ the pool.
2. **Country composition.** Is the trend an artifact of India's share of filings rising?
3. **Industry/employer composition.** Is "India 24.6%" a country effect or an IT-services
   (NAICS 5415) staffing-sector effect?
4. **Mega-filer concentration.** Is the rise driven by a few large employers?
5. **Flag semantics.** `ben_multi_reg_ind=1` = the beneficiary appeared in >1 employer's
   registration that lottery year. It is not proof of fraud, and the *filing* employer is not
   necessarily the party that multi-registered the person.

### 2. Analyses run (SQL + results)

**(i) FY trend — verified exact.**
```sql
SELECT fiscal_year, COUNT(*), SUM(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END),
       ROUND(100.0*AVG(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END),1)
FROM i129_petition GROUP BY 1 ORDER BY 1;
```
FY21 99,610/8,148 = **8.2%** · FY22 89,535/15,159 = **16.9%** · FY23 91,832/20,892 = **22.8%** ·
FY24 91,864/23,401 = **25.5%**. Matches the draft.

**(ii) Composition test — within-country trends** (India share of filings is FLAT: 64.1% →
67.2% → 70.2% → 66.7%, so the trend cannot be a country-mix shift).
`country_of_birth` holds ISO3 codes (`IND`, `CHN`) — a `LIKE 'INDIA%'` predicate silently
matches nothing and collapses every row into "Other":
```sql
SELECT CASE WHEN country_of_birth='IND' THEN 'India'
            WHEN country_of_birth='CHN' THEN 'China' ELSE 'Other' END AS grp,
       fiscal_year, COUNT(*),
       ROUND(100.0*AVG(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END),1)
FROM i129_petition GROUP BY 1,2 ORDER BY 1,2;
-- India share of filings per FY:
SELECT fiscal_year, ROUND(100.0*AVG(CASE WHEN country_of_birth='IND' THEN 1 ELSE 0 END),1)
FROM i129_petition GROUP BY 1 ORDER BY 1;
```

| Multi-reg rate among filed petitions | FY21 | FY22 | FY23 | FY24 |
|---|---|---|---|---|
| India-born (n≈60–64k/yr) | 10.5% | 23.4% | 30.0% | **34.9%** |
| China-born (n≈11–17k/yr) | 5.4% | 4.6% | 8.1% | **10.1%** |
| All other (n≈16–18k/yr) | 2.9% | 2.9% | 3.9% | **4.2%** |

The rise is *within* every group (India 3.3×, China 1.9×, other 1.4×) — a behavioral change,
not composition.

**(iii) Industry decomposition — India × NAICS 5415 (IT services), FY21–24 pooled.**
IT services is `naics_code LIKE '5415%'` (prefix, not equality — the column carries full
6-digit codes):
```sql
SELECT country_of_birth='IND' AS india, naics_code LIKE '5415%' AS it_svc, COUNT(*),
       ROUND(100.0*AVG(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END),1)
FROM i129_petition GROUP BY 1,2 ORDER BY 1 DESC,2 DESC;          -- pooled 2x2
SELECT fiscal_year, country_of_birth='IND', naics_code LIKE '5415%',
       ROUND(100.0*AVG(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END),1)
FROM i129_petition GROUP BY 1,2,3 ORDER BY 2 DESC,3 DESC,1;      -- per-FY
```


| | NAICS 5415 | Other NAICS |
|---|---|---|
| India-born | 33.5% (n=156,643) | 9.7% (n=93,082) |
| Other-born | 6.9% (n=20,543) | 4.6% (n=102,573) |

And per FY: India×5415 rose 15.0% → **45.4%**; India×other 4.8% → 15.6%; other×5415 3.9% → 9.4%;
other×other 4.2% → 6.2%. **The phenomenon is an India × IT-staffing interaction**: India-born
beneficiaries outside IT services run ~10% (still 2× other countries), while India×IT-services
reaches 45% by FY24. "India 24.6%" as a bare country stat is technically true but
under-specified — the sector is half the story.

**(iv) Mega-filer test — INVERTED.** Top employers by multi-reg petition count:
Amazon 483 multi/13,569 filed (**3.6%**), TCS 387/8,247 (4.7%), Infosys 350/11,421 (**3.1%**),
Cognizant 292/6,439 (4.5%), Microsoft 144/4,349 (3.3%), IBM 101/3,232 (3.1%). The extreme rates
are tiny staffing shops: Aclat Inc. 88/88 (**100%**), Snowstack LLC 91/94 (96.8%), Petadigit LLC
92/100 (92.0%), R2 Technologies 114/124 (91.9%), Tek Leaders 81/84 (96.4%).

**Size gradient** (employer bucketed by total FY21–24 filings). Bucketing is on raw
`employer_name`, NOT `employer_cluster_id` — a firm spelled two ways (e.g. "Tek Leaders,
Inc." 84 filings and "Tek Leaders Inc." 51) counts as two employers, which is what the
published table reflects:
```sql
WITH e AS (SELECT employer_name, COUNT(*) n,
                  SUM(CASE WHEN ben_multi_reg_ind THEN 1 ELSE 0 END) m
           FROM i129_petition GROUP BY 1)
SELECT CASE WHEN n>=1000 THEN '1000+' WHEN n>=200 THEN '200-999'
            WHEN n>=50 THEN '50-199' WHEN n>=10 THEN '10-49' ELSE '1-9' END AS bucket,
       COUNT(*) AS employers, SUM(n) AS petitions, ROUND(100.0*SUM(m)/SUM(n),1) AS pct
FROM e GROUP BY 1 ORDER BY MIN(n);
-- concentration: 1,815 employers with >=10 filings and a >=50% rate
SELECT COUNT(*), SUM(m), ROUND(100.0*SUM(m)/(SELECT SUM(m) FROM e),1)
FROM e WHERE n>=10 AND m::numeric/n>=0.5;
-- share of all multi-reg petitions held by employers under 50 filings (79.4%)
SELECT ROUND(100.0*SUM(m) FILTER (WHERE n<50)/SUM(m),1) FROM e;
```


| Employer size (filings) | Employers | Petitions | Multi-reg rate |
|---|---|---|---|
| 1–9 | 54,807 | 105,504 | 20.4% |
| 10–49 | 4,656 | 91,430 | **35.2%** |
| 50–199 | 551 | 46,972 | 19.8% |
| 200–999 | 98 | 38,537 | 4.4% |
| 1,000+ | 29 | 90,398 | **3.2%** |

**1,815 employers with ≥10 filings and a ≥50% multi-reg rate account for 31,288 of 67,600
multi-reg petitions (46%)**; employers under 50 filings hold 79% of all multi-reg petitions.
The famous large outsourcers are NOT the drivers — the pattern lives in the long tail of small
staffing firms.

**(v) Selection-bias quantification** (vs USCIS published pool aggregates):

| Cap FY | Eligible registrations | …of multi-reg beneficiaries | Pool multi-reg share (registrations) | Our filed-petition multi share |
|---|---|---|---|---|
| 2021 | 269,424 | 28,125 | 10.4% | 8.2% |
| 2022 | 301,447 | 90,143 | 29.9% | 16.9% |
| 2023 | 474,421 | 165,180 | 34.8% | 22.8% |
| 2024 | 758,994 | 408,891 | **53.9%** | 25.5% |
| 2025 (rule change) | 470,342 | 47,314 | 10.1% | — (outside our data) |

Direction of bias, FY2024 worked example: unique beneficiaries ≈446,000 (USCIS), so multi-reg
beneficiaries ≈ 446,000 − 350,103 single = **95,897 (21.5% of beneficiaries)**, averaging
408,891/95,897 ≈ **4.3 registrations each**. Under uniform per-registration selection
(p = 188,400/758,994 = 24.8%), a 4.3-registration beneficiary had ≈ 1−0.752^4.3 ≈ 70% selection
odds → expected multi share among selected *beneficiaries* ≈ 44%. Observed among *filed
petitions*: 25.5%. Two conclusions:
- Relative to the **registration pool** (53.9%) our filed-petition rate massively
  UNDER-states multi-registration; relative to the **beneficiary pool** (21.5%) it mildly
  over-states it (mechanical over-selection, partly offset by lower filing).
- Implied relative filing propensity: selected multi-reg beneficiaries converted to a filed
  petition at very roughly **half the rate** of single-reg selectees (25.5% observed vs ~44%
  expected) — consistent with speculative registrations that never intended to file. This is a
  derived estimate stacking three approximations (uniform selection, USCIS's ~446k unique
  count, petition≈beneficiary); publish only as an explicitly rough, arithmetic-shown aside,
  or omit.
- **The trend is NOT a selection-bias artifact**: the pool-level registration share rose even
  faster (10.4% → 53.9%, 5.2×) than our filed-petition rate (8.2% → 25.5%, 3.1×).

### 3. Verdicts

- **DEFENSIBLE:** the tripling trend (with denominator labeled); the within-country and
  within-sector rises; the small-staffing-firm concentration + size gradient; the FY25 rule
  before/after (USCIS's own numbers: multi-reg registrations 408,891 → 47,314, −88%).
- **SOFTEN:** "India 24.6% vs China 6.9%" → present the India×IT-services interaction and the
  per-FY within-India rise (10.5%→34.9%); a bare country table invites an ecological misread.
  Every rate must say "among selected-and-filed petitions."
- **DROP:** any "1 in 4 petitions gamed the lottery" phrasing (flag ≠ proven gaming; USCIS
  calls it potential abuse); any implication that Infosys/TCS/Cognizant-class filers drive it
  (the data shows the opposite — 3–5% rates); do NOT extrapolate the 25.5% to "the lottery"
  (the registration pool figure is 53.9% and it's USCIS's own number — cite it instead).

### 4. Adjusted numbers to publish

The FY-trend table as-is (labeled), the within-country per-FY table, the India×5415 2×2, the
employer-size-gradient table, the pool-vs-filed comparison table above, and the FY25/26 USCIS
aggregates as the "after" picture.

### 5. Follow-up angles

- "Who files for multi-registered beneficiaries" — the size gradient is itself a headline
  (the gaming lived in thousands of small staffing shops, not Big Tech or big outsourcers).
- Wage differential: multi-reg petitions' median pay vs single-reg within the same title
  (are multi-reg placements lower-paid?). One bounded GROUP BY, worth adding.
- Post-rule corroboration: FY25/FY26 USCIS aggregates close the arc (multi-reg share of
  eligible registrations 53.9% → 10.1%; and the Dec-2025 weighted-selection proposed rule,
  [Federal Register 2025-23853](https://www.federalregister.gov/documents/2025/12/29/2025-23853/weighted-selection-process-for-registrants-and-petitioners-seeking-to-file-cap-subject-h-1b),
  as forward context).

### 6. Recommended framing + headline

**Headline:** "Multi-registered beneficiaries went from 8% to 25% of filed H-1B petitions in
four years — and USCIS's own pool data says over half of FY2024 lottery *registrations* were
multi-entries. The gaming lived in small staffing firms, not the big outsourcers."
Frame as the "before" picture of the FY2025 beneficiary-centric rule, with the flag's exact
definition adjacent, both denominators (filed petitions vs registration pool) shown, and the
size-gradient table as the novel contribution.

---

### 7. Re-verification log

Story (a)'s figures are hardcoded literals in `scripts/oneoff/generate_i129_story_posts.py`,
so this section is the only record of how they were derived — re-run §2's SQL, never a
hand-rolled variant.

| Date | Result |
|---|---|
| 2026-07-13 | Original derivation (all figures above). |
| 2026-07-31 | Re-verified against live prod: FY trend, within-country, India share, India×5415 pooled + per-FY, size gradient, named large filers, named small firms, 1,815-employer concentration (46.3%), under-50 share (79.4%) — **all match to the published decimal, zero drift**. Published page body identical prod vs staging. |

---

## Story (b) — Gender pay gap

### 1. Confounds identified

Occupation sorting, country-of-birth mix, age, education, employer mix, sample trimming,
34% blank job titles (redaction/source artifact, worse in FY21–22), base-pay-only (no
equity/bonus/hours), and selected-and-filed sample. Also a **labeling issue**: the pay field.

**Labeling correction (important):** `comp_paid_annual` is I-129 `BEN_COMP_PAID` —
"beneficiary's rate of pay per year" as reported by the employer ON THE PETITION. It is
prospective, employer-reported compensation, not payroll-verified earnings. Our `pay_annual`
column is *derived from it* in ingest (`pay_annual = comp_paid_annual OR annualize(wage_amt)` —
`lib/ingest/plugins/uscis_i129.py:306`), so the two are identical by construction (verified:
367,487/367,487 equal rows) and NO in-table "stated vs paid" comparison exists. Call it
**"pay reported on the I-129 petition"**, never "what workers actually earned."

Sample hygiene: `comp_paid_annual` populated 98.6% (367,487); trimmed to $20k–$1M (drops 3,080
below + 222 above, keeps 364,185 = 99.1%) — raw values include $0.01 and $169.5M, so trimming
is mandatory. `gender` is complete two-value male/female.

### 2. Analyses run (SQL + results)

**(i) Raw gap (trimmed):** male mean $102,766 / median $94,000 (n=244,503) vs female mean
$98,014 / median $90,057 (n=119,682) → **+4.8% mean, +4.4% median**. Untrimmed medians
$93,730/$90,000 (matches the draft's numbers; the draft's ~4% is reproducible). Gap by FY:
+6.9% (FY21) → +5.1% → +3.8% → +3.9% (FY24) — narrowing.

**(ii) Composition covariates by gender:** men are OLDER (mean 32.7 vs 30.8), MORE India-born
(70.7% vs 59.3%), MORE IT-services (52.0% vs 38.4%). Since India-born and IT-services petitions
pay LESS, male composition tilts toward lower-paying segments — i.e., naive intuition about
"controls will shrink the gap" is not guaranteed; they could widen it.

**(iii) Within-occupation adjusted gap** (strata = UPPER(job_title) × FY, blanks excluded,
≥20 per gender per stratum; weighted by stratum size):
```sql
WITH s AS (SELECT UPPER(job_title) t, fiscal_year fy, gender g, comp_paid_annual c
           FROM i129_petition
           WHERE comp_paid_annual BETWEEN 20000 AND 1000000 AND job_title <> ''),
st AS (SELECT t, fy,
         COUNT(*) FILTER (WHERE g='male') nm, COUNT(*) FILTER (WHERE g='female') nf,
         AVG(c) FILTER (WHERE g='male') mm, AVG(c) FILTER (WHERE g='female') mf,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY c) FILTER (WHERE g='male') medm,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY c) FILTER (WHERE g='female') medf
       FROM s GROUP BY 1,2
       HAVING COUNT(*) FILTER (WHERE g='male')>=20 AND COUNT(*) FILTER (WHERE g='female')>=20)
SELECT COUNT(*), SUM(nm+nf),
       ROUND(100.0*SUM((nm+nf)*(mm-mf))/SUM((nm+nf)*mf),2)   AS adj_mean_pct,
       ROUND((100.0*SUM((nm+nf)*(medm-medf))/SUM((nm+nf)*medf))::numeric,2) AS adj_med_pct
FROM st;
```
→ 388 strata, 107,068 petitions covered: **adjusted mean gap +0.29%, adjusted median gap
−0.85%** (women marginally higher). The 4% raw gap **essentially disappears within identical
job titles.**
- Pitfall found & fixed en route: 124,967 rows (33.5%) have a BLANK `job_title` (44%/40% in
  FY21/22, 25–27% in FY23/24 — a redaction-era source artifact). Including the blank "title" as
  a stratum fakes a +3.1% "within-occupation" gap because it is really an uncontrolled pool.
  Representativeness check: the raw gap is nearly identical in the nonblank (+4.5% mean) and
  blank (+5.5% mean) subsamples, so restricting to nonblank titles does not cherry-pick.

**(iv) Within-employer** (≥20/20, nonblank subsample): 275 strata, 93,245 covered →
**+5.34%** (slightly larger than raw). **Within title×employer** (≥10/10, nonblank): 401
strata, 50,121 covered → **+0.99%**. Read: within a given employer, men and women hold
different (differently-paid/leveled) titles; within the same title the pay difference is ≈0–1%.

**(v) By country of birth (raw, then adjusted):**

| Group | Male mean / median | Female mean / median | Raw mean gap | Title-adjusted gap (≥10/10 strata) |
|---|---|---|---|---|
| India (n=244,517) | $96,974 / $90,418 | $96,133 / $90,000 | **+0.9%** | **−0.21%** |
| China (n=53,075) | $117,202 / $119,715 | $100,689 / $95,450 | **+16.4%** (median +25.4%) | **+0.73%** |
| Other (n=66,593) | $116,517 / $109,800 | $100,945 / $89,000 | **+15.4%** | **+2.92%** |

The headline-grabbing 16–25% raw gaps among China-born and other-born collapse to ≤3% within
job title — occupation sorting, not unequal pay for the same job. India-born (2/3 of the
sample, gap ≈0 even raw) drags the aggregate gap down to 4%.

**(vi) Education & age:** the gap persists WITHIN education level (Bachelor's +6.1% mean,
Master's +4.9%, Doctorate +9.6% mean / +8.5% median) — education explains nothing. By age band
the mean gap shrinks from +7.9% (<28) to +0.7% (33–38), +4.1% (39+); female median is actually
higher in the 33–38 band. Age composition (men older) works *against* the raw gap, not for it.

### 3. Verdicts

- **DROP as headline:** "H-1B women are paid ~4% less" as an inequity/discrimination-flavored
  claim. It does not survive: the gap is +0.3% mean / −0.9% median within identical job titles,
  and the raw gap is dominated by occupation + country composition.
- **DEFENSIBLE (and better):** the decomposition itself. "H-1B men and women in the same job
  title are paid essentially the same; the modest 4% overall gap — and the striking 16–25% raw
  gaps among Chinese- and other-born beneficiaries — comes from *which jobs* men and women
  hold, not different pay in the same job."
- **SOFTEN / mandatory caveats:** (1) job titles encode seniority ("Senior SWE"), so equal pay
  within title does NOT rule out gendered title/level attainment — the classic
  controlled-gap critique cuts both ways and must be stated; (2) base salary on the petition
  only — no equity/bonus (where tech gender gaps often live), no hours; (3) new-hire
  lottery petitions only, FY21–24; (4) 33.5% blank titles (representativeness check reported);
  (5) employer-reported prospective pay (labeling correction above).
- **Actual-vs-LCA-posted framing (+19–24% mean):** must lead with the MEDIAN (ratio 1.000 —
  the typical worker's reported pay equals the LCA posted wage exactly; 71.8% within ±1%);
  the mean gap is entirely upper-quartile. "H-1B workers are paid 20% above the posted wage"
  is NOT a defensible summary; "one in four is paid above the posted wage, and those premia
  are large" is. Whether the mean premium is a big-tech composition artifact needs the heavy
  join — run OFF-PROD on staging (see §Off-prod SQL).

### 4. Adjusted numbers to publish

Raw +4.8% mean / +4.4% median (trimmed $20k–$1M); within-title +0.29% mean / −0.85% median
(388 strata, 107k petitions); within-employer +5.3%; within title×employer +1.0%; the
three-country panel above; gap by FY (6.9%→3.9%).

### 5. Follow-up angles

- Occupational segregation as its own story: female share by title (Software Engineer 28.4%,
  Senior SWE 19.7%, Architect 22.8% vs Data/Business Analyst 45–47%) with median pay per title.
- Field_of_study cut (same stratified method).
- Full-time flag as an extra control (H-1B is overwhelmingly full-time; quick check).
- Off-prod: gender split of the actual-vs-LCA premium (do men capture more above-posted pay
  within the same employer?) — genuinely novel if it survives controls.

### 6. Recommended framing + headline

**Headline:** "In the same job title, H-1B women and men are paid the same — the gender gap in
H-1B pay is a story about which jobs, not unequal pay. (And the 25% raw gap among Chinese-born
workers vanishes under the same lens.)" This is more citable than the dropped 4% claim, harder
to debunk, and the seniority caveat is stated, not hidden.

---

## Story (c) — Lottery odds (design; not computable from our DB)

### 1. Why our DB can't do it

We hold only selected-and-filed petitions (`status_type=1` on 372,837/372,841 rows). Odds
require the registration pool → use USCIS's published aggregates (below), with our microdata
only as corroboration of who ended up filing.

### 2. The honest construction

**Layer 1 — per-registration selection rate** (selections ÷ eligible registrations, USCIS):

| Cap FY | Eligible | Selected (all rounds) | Per-registration rate |
|---|---|---|---|
| 2021 | 269,424 | 124,415 | 46.2% |
| 2022 | 301,447 | 131,924 | 43.8% |
| 2023 | 474,421 | 127,600 | 26.9% |
| 2024 | 758,994 | 188,400 | 24.8% |
| 2025 | 470,342 | 135,137 regs / 127,624 beneficiaries | ~28.7% per registration; **28.9% per beneficiary** |
| 2026 | 343,981 | 120,141 | ~34.9% |

Caveat that MUST ride the table: FY21/22 rates are inflated by multiple selection rounds run
because many selectees never filed; "selected" ≠ "got an H-1B" (petitions must still be filed
and approved). These are odds of *selection*, nothing more.

**Layer 2 — the real story: odds per BENEFICIARY conditional on registration count (pre-FY25).**
Selection was uniform over registrations, so P(selected) ≈ 1−(1−p)^k for k registrations:

| Cap FY | p (per reg) | k=1 | k=2 | k=3 | k=5 |
|---|---|---|---|---|---|
| 2023 | 26.9% | 26.9% | 46.6% | 61.0% | 79.2% |
| 2024 | 24.8% | 24.8% | 43.5% | 57.5% | 76.0% |

FY2024 concretely: the average multi-registered beneficiary held ≈4.3 registrations
(408,891 regs ÷ ~95,897 multi-reg beneficiaries, from USCIS's ~446,000 unique-beneficiary
figure) → ≈**70% selection odds vs 24.8% for a single-registration beneficiary — a 2.8×
advantage**. That asymmetry is what the FY2025 beneficiary-centric rule deleted: from FY25 every
beneficiary has identical odds regardless of employer count (28.9% in FY25, ~35% in FY26,
because the pool shrank by ~415k once duplicate entries stopped paying).

**Layer 3 — corroboration from our microdata:** the multi-reg share of filed petitions
(8.2%→25.5%) vs the pool share (10.4%→53.9%) demonstrates both the over-selection and the
lower filing propensity of multi-reg selectees (story-a §2.v).

### 3. Verdicts

- **DEFENSIBLE:** all Layer-1/2 numbers (pure USCIS aggregates + a transparent binomial
  identity); the 2.8× FY24 multi-reg advantage; the FY25 equalization.
- **SOFTEN:** always "odds of selection," never "odds of getting an H-1B visa"; state the
  independence approximation (1−(1−p)^k) and that the ~4.3 average uses USCIS's rounded
  ~446k unique-beneficiary figure.
- **DROP:** any bare "your odds were X% in FY2024" without the single-vs-multi conditioning —
  the unconditional number was practically meaningless pre-FY25, which IS the story.

### 4. Recommended framing + headline

**Headline:** "Before 2024's rule change, H-1B lottery odds depended on how many employers
registered you: ~25% with one registration, ~70% for the average multi-registered beneficiary.
The beneficiary-centric rule made it 29% for everyone — and 415,000 duplicate entries
evaporated." Present as three exhibits: per-registration rates by FY, the k-conditional table,
and the FY25/26 before/after.

---

## Off-prod SQL (staging only — heavy `worksite_record` join; do NOT run on prod)

For the story-(b) actual-vs-posted follow-ups, on the staging stack (`vb_stg_postgres`,
prod-copy DB), materialize once then aggregate:

```sql
-- 1) One-time temp join (heavy: worksite_record is millions of rows)
CREATE TEMP TABLE i129_lca AS
SELECT i.id, i.gender, i.employer_name, i.fiscal_year, i.comp_paid_annual,
       w.wage_annual AS lca_posted
FROM i129_petition i
JOIN worksite_record w ON w.case_number = i.dol_eta_case_number
WHERE i.comp_paid_annual BETWEEN 20000 AND 1000000
  AND w.wage_annual BETWEEN 20000 AND 1000000;
ANALYZE i129_lca;

-- 2) Is the +19-24% mean premium a composition artifact? Premium by employer size/decile
WITH e AS (SELECT employer_name, COUNT(*) n FROM i129_lca GROUP BY 1)
SELECT CASE WHEN e.n>=1000 THEN '1000+' WHEN e.n>=100 THEN '100-999' ELSE '<100' END AS size,
       COUNT(*),
       ROUND(AVG(j.comp_paid_annual - j.lca_posted)) AS mean_premium,
       ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY j.comp_paid_annual/j.lca_posted))::numeric,3) AS med_ratio
FROM i129_lca j JOIN e USING (employer_name) GROUP BY 1;

-- 3) Gender split of the premium, within employer strata (mirror the on-prod stratified method)
SELECT gender, COUNT(*), ROUND(AVG(comp_paid_annual - lca_posted)) AS mean_premium,
       ROUND((percentile_cont(0.5) WITHIN GROUP (ORDER BY comp_paid_annual/lca_posted))::numeric,3) AS med_ratio
FROM i129_lca GROUP BY 1;
```

---

## Reviewer's red-team — strongest objection per headline

**(a)** *"Your denominator is selected petitions; the lottery favored multi-registrants, so the
trend is mechanical."* — Survives, decisively: USCIS's own registration-pool share rose FASTER
(10.4%→53.9%) than our filed-petition rate (8.2%→25.5%); selection bias makes our numbers
conservative for the pool. Second objection — *"you're smearing Indian workers / big
outsourcers"* — pre-empted by publishing the within-sector split (India outside IT services:
~10%) and the inverted mega-filer table (Infosys 3.1%, Amazon 3.6%). Residual risk: naming
small 90–100% multi-reg employers reads as a fraud accusation; if named, print the flag
definition beside the table, show n, and say USCIS's flag ≠ adjudicated wrongdoing (or publish
the size-gradient without names).

**(b)** *"A 4% gap headline is trivially debunked: control for occupation and it's gone —
you're one regression away from embarrassment."* — Correct, which is why the 4%-gap headline is
DROPPED and the decomposition IS the story. The inverse objection to the new headline —
*"within-title equality just means the inequality moved into title attainment"* — is
acknowledged in the text as a limitation, not hidden. Third objection — *"petition pay isn't
real pay"* — addressed by the labeling correction (employer-reported I-129 rate of pay) and by
the base-pay-≠-total-comp caveat (no equity: the field where tech gender gaps concentrate).

**(c)** *"Selection odds aren't visa odds, and FY21/22 rates are inflated by non-filing."* —
Stated on the table itself; the story's claims are strictly about selection. The binomial
approximation is exact enough at these magnitudes (finite-population correction is negligible
at k≤10 of 759k) and the only estimated input (~4.3 avg registrations) traces to USCIS's own
published unique-beneficiary count.

## Bottom line

- Story (a): publish, strengthened — add the pool comparison, within-cell trends, and
  small-firm concentration; keep "multi-registered," never "fraud."
- Story (b): flip the headline — the 4% gap claim dies under controls; the composition
  decomposition (and the vanishing 25% China-born gap) is the durable, novel finding.
- Story (c): publish from USCIS aggregates with the conditional-odds table as the centerpiece;
  our microdata is corroboration, not the source.
