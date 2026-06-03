# Immigration Attorney / Law-Firm Database — Scoping (2026-06-02)

Owner-approved direction after the named-applicant people-search was disproven
(`PEOPLE_SEARCH.md`) and the broker-DB path was deemed out of scope
(`PEOPLE_SEARCH_MARKET_RESEARCH.md`). Goal: a database of immigration attorneys
& firms with **volume, specialization, success rates, contact info, and (ideally)
pricing** — built mostly from data we already ingest, low legal risk (these are
professionals acting commercially, not vulnerable applicants).

**TL;DR:** Strong fit. The richest fields are already in our LCA + PERM files
(just parsed-and-discarded today). We can ship volume + **certification/denial
success rates** + deep specialization from our own data, enrich contact/standing
from public bar directories, and differentiate vs the incumbent (MyVisaJobs) on
**outcomes + specialization granularity**, which they don't emphasize. Pricing is
the one genuinely weak input. Core build ~1 week reusing existing infra.

---

## 1. What we can derive from data we ALREADY ingest (no new source)

Confirmed against the live DOL record layouts (2026-06-02):

**LCA / H-1B disclosure (FY2020+)** carries per case:
`AGENT_ATTORNEY_FIRST/LAST/MIDDLE_NAME`, `AGENT_ATTORNEY_EMAIL_ADDRESS`,
`AGENT_ATTORNEY_PHONE`, `AGENT_ATTORNEY_ADDRESS/CITY/STATE/POSTAL`,
`LAWFIRM_NAME_BUSINESS_NAME`, plus `CASE_STATUS`, employer, SOC, job title,
wage, worksite, dates.

**PERM new-form (FY2024+)** adds even more: `ATTY_AG_*` name + email + phone +
address + `ATTY_AG_LAW_FIRM_NAME` + **`ATTY_AG_STATE_BAR_NUMBER`** +
**`ATTY_AG_GOOD_STANDING_STATE/COURT`** + FEIN, plus `CASE_STATUS`,
`FW_INFO_CTRY_OF_CIT` (country), SOC, wage, worksite.

Older files (pre-2020 LCA, old PERM) give attorney **name + firm only** (good for
historical volume, no contact).

**Derivable metrics per attorney AND per firm:**
| Metric | From | Notes |
|---|---|---|
| **Volume** | count of LCA + PERM cases by FY | the table-stakes metric (MyVisaJobs has this) |
| **Success / certification rate** | `CASE_STATUS` = Certified / Denied / Withdrawn / Certified-Expired | **the differentiator.** Strongest on **PERM** (real adjudication). LCA is near-rubber-stamp → H-1B "success rate" is a weak signal; lead with PERM cert-rate + be honest about LCA. |
| **Specialization — filing type** | H-1B (LCA) vs PERM/green-card mix | |
| **Specialization — job/industry** | SOC code + job title + employer NAICS | "does immigration for tech / healthcare / academia" |
| **Specialization — country** | PERM `FW_INFO_CTRY_OF_CIT` | "files a lot for India/China applicants" |
| **Specialization — employer** | which employers they file for | cross-links to our employer pages |
| **Geography** | attorney state + worksite states | |
| **Wage band handled** | offered wage + PW level | seniority proxy |
| **Trend** | year-over-year volume + cert-rate | growing/shrinking, improving/declining |
| **Contact** | email, phone, address, firm | LCA FY2020+ & PERM FY2024+ |
| **Bar number + good standing** | PERM new-form | links to bar directory enrichment |

Engineering note: attorney + firm names need **entity resolution** (same firm
spelled many ways, attorney name variants). We already have employer-clustering
infra (`lib/business/salary/employer_clustering.py`) — reuse it for attorney/firm.

---

## 2. What we can enrich from EXTERNAL public sources

| Source | Adds | Linkage / cost |
|---|---|---|
| **State bar directories** (44 states + DC online) | License status, discipline history, admission year, sometimes practice area/languages | Link via `STATE_BAR_NUMBER` (PERM) or name+state. Heterogeneous per-state, scrape/lookup. ([LawyerLegion state bar list](https://www.lawyerlegion.com/promote-your-law-practice/directories-by-state-bar)) |
| **ABA National Lawyer Regulatory Data Bank** | Public disciplinary actions, national | Aggregated discipline |
| **AILA member directory** (ailalawyer.com) | Immigration-specialization credibility signal | Public search ([AILA](https://www.ailalawyer.com/)) |
| **Avvo / Martindale / Justia** | Ratings, reviews, profile, contact | Public profiles; scraping/ToS care |
| **Firm websites** | Services, occasional flat-fee pricing | Crawl |

---

## 3. What is NOT readily available

- **Pricing** — not structured or public. Some firms publish flat fees; Avvo /
  ContractsCounsel show ranges. Best we can do is partial (scrape firm sites /
  crowdsource / show typical market ranges). **Set expectation: pricing will be
  sparse/best-effort, not comprehensive.**
- **True outcome quality beyond DOL** — USCIS does not publish attorney-level
  I-129/I-140 approval or RFE rates. Our "success" = DOL labor-cert outcome only.
  Be explicit about that scope.

---

## 3b. Coverage limits — which visa types leave a public attorney trail

Only **DOL labor programs** publish case-level data with attorney names. That is
the entire universe we can mine for volume/outcome:
- **PERM** (EB-2/EB-3 green-card labor cert), **H-1B / H-1B1 / E-3** (LCA),
  **H-2A / H-2B** (temp worker — low relevance to our audience), **CW-1**, **PWD**.

Everything else is adjudicated by **USCIS** (petitions) or **DOS** (consular),
which publish **only aggregate statistics — no case-level rows, no attorney
names**:
- **O-1, EB-1A/B, EB-2 NIW** (these *skip* PERM → no DOL trace at all), **L-1,
  marriage/family (I-130/I-485), K-1, EB-5, asylum, naturalization.**

**Implication:** our DB covers attorneys doing PERM + H-1B — i.e. most
*employment-based* immigration practice. It will **under-count boutiques** focused
on O-1 / EB-1 / NIW / family, who leave no public case trail. For those areas the
only thing available is **self-reported** practice-area tags (AILA/Avvo) — no
volume, no success data. Add them as a clearly-labeled "self-reported practice
areas" field, distinct from DOL-measured metrics, so we don't imply outcome data
we don't have.

## 4. Competition

- **MyVisaJobs** — the incumbent. Already has **law-firm AND attorney reports by
  H-1B + PERM volume + avg salary**, per-firm/attorney pages with contacts +
  reviews (e.g. Fragomen 40,940 LCAs FY2025, $155k avg). Strong, established.
  ([MyVisaJobs law-firm report](https://www.myvisajobs.com/reports/h1b/law-firm/),
  [attorney report](https://www.myvisajobs.com/reports/h1b/attorney/)).
  **Our edge vs them:** (a) **cert/denial success rates** (they emphasize volume,
  not outcomes); (b) **specialization cross-tabs** (by country × SOC × employer);
  (c) **bar standing/discipline** integration; (d) it lives inside a tool the
  applicant already uses for wages + bulletin predictions.
- **h1bdata.info / h1bgrader / h1bsalary** — sponsor/wage focused, weak on attorneys.
- **AILA / Avvo / Martindale** — directories with ratings but **no volume/outcome
  data**. Opposite gap.
- **Unowned gap to capture:** "which attorney/firm actually gets PERMs *certified*
  (fast, high rate) for people like me — my country, my job, my employer-type —
  and how do I reach them, and are they in good standing."

---

## 5. Features users will benefit from

1. **Attorney/firm leaderboard** filterable by filing type, country, SOC/job,
   employer, state, wage band, FY.
2. **Profile page** (attorney + firm): volume trend, PERM cert/denial rate, top
   employers, top job categories, countries served, median wage, geography,
   contact, bar status/discipline, AILA membership.
3. **"Find an attorney" wizard**: enter your category/country/employer/job →
   ranked matches by *relevant* volume + cert rate (not just raw volume).
4. **Compare** two/three attorneys or firms side by side.
5. **Cross-links** from existing employer + wage + prediction pages ("law firms
   that file for Google", "top firms for EB-2 India").
6. Reviews / pricing (later, best-effort).

---

## 6. Effort

**Reuse:** ingest framework, employer-clustering (→ attorney/firm resolution),
autocomplete + search, profile-page + leaderboard patterns, trigram indexes.

**New work / phasing:**
- **P1 (~2–3d):** persist attorney + firm entities + contact fields (currently
  parsed-then-discarded — same one-line-mapping fix noted in `PEOPLE_SEARCH.md`);
  attorney/firm entity resolution; basic volume + PERM cert-rate aggregates;
  firm/attorney profile + leaderboard + search/autocomplete.
- **P2 (~2–3d):** specialization cross-tabs (country × SOC × employer), wage
  bands, YoY trends, "find an attorney" wizard, cross-links from employer/wage pages.
- **P3 (ongoing enrichment):** bar status/discipline (44 states, heterogeneous —
  per-state scrape/lookup keyed on bar number), AILA membership, Avvo ratings,
  pricing (hard). Open-ended.
- **P3 (optional) — court-litigation signal.** Petition work (H-1B/PERM/O-1/EB-1/
  family) is adjudicated *administratively* by USCIS/DOL and never touches a court,
  so court records add **no filer volume**. But federal **litigation** names the
  attorney of record publicly: mandamus/APA suits to force USCIS on delayed cases
  + circuit-court petitions for review (mostly removal/asylum). Mine via
  **CourtListener / RECAP (Free Law Project API)** — free, queryable, avoids
  PACER per-page fees. Yields a "litigates against USCIS" badge (useful for users
  stuck in backlogs), but it's a small slice skewed to removal-defense + delay
  suits, not affirmative petitions. EOIR immigration-court data (DOJ) exists only
  via FOIA/TRAC, attorney-level mining is hard + redacted. Niche enrichment, not core.

**Total core (P1+P2): ~1 week.** Enrichment (P3) is incremental.

**Caveats / risk:**
- Lower legal risk than applicant search — attorneys/firms are professionals
  acting commercially (public bar membership, public contact). Still: offer a
  simple opt-out/correction path; show DOL-sourced facts, attribute clearly.
- Lead success metric with **PERM cert-rate**; flag LCA "approval" as near-100%
  so we don't imply a fake quality signal.
- Attorney/firm name resolution is the main engineering risk — budget for it.

---

## 7. Recommendation

Build **P1 + P2** (~1 week). It fills a real, unowned gap (outcomes +
specialization vs MyVisaJobs' volume-only), reuses our infra, is low-risk, and
strengthens the core site by cross-linking employers ↔ wages ↔ firms. Treat
pricing + reviews as best-effort later; don't gate launch on them.

## Sources
MyVisaJobs law-firm/attorney reports; AILA / Avvo / Martindale directories;
LawyerLegion state-bar directory list + ABA Data Bank; DOL LCA FY2024 +
PERM new-form FY2024 record layouts (verified live 2026-06-02).
