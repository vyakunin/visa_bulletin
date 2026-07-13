# Story (a) — H-1B multi-registration: 8% → 25%, and it wasn't the big outsourcers

**Lever-3 link-bait data story. Target surface:** `/analysis/h1b-multi-registration-lottery-gaming/`
**Status:** PUBLICATION DRAFT — every figure verified against live prod `i129_petition` 2026-07-13; confounds red-teamed in `RIGOR_REVIEW.md` (fable pass). Pool aggregates from USCIS published registration statistics.
**Attribution (Apache-2.0, required):** "sourced from USCIS, obtained by Bloomberg" (Bloomberg v. DHS FOIA release; same microdata as Borjas, NBER w34793).
**Universe (must appear on the page):** FY2021–2024, cap-subject lottery petitions, **selected-and-filed** I-129s (not the full registration pool). Frozen FOIA snapshot. Aggregates only — per-beneficiary keys are FOIA-redacted.

---

## Headline

Among **filed** H-1B petitions, the share tied to a beneficiary that multiple employers had registered in the lottery **tripled in four years — 8.2% (FY2021) → 25.5% (FY2024)**. USCIS's own registration data shows the underlying pool went further: **over half of FY2024 lottery registrations were multi-entries.** And the concentration is the opposite of the common assumption — it lives in the long tail of small staffing firms, not Infosys, TCS, or Amazon.

## The trend (among selected-and-filed petitions)

| FY | Filed petitions | Multi-registered | Rate |
|----|-----------------|------------------|------|
| 2021 | 99,610 | 8,148 | **8.2%** |
| 2022 | 89,535 | 15,159 | **16.9%** |
| 2023 | 91,832 | 20,892 | **22.8%** |
| 2024 | 91,864 | 23,401 | **25.5%** |

`ben_multi_reg_ind = 1` means USCIS flagged the beneficiary as appearing in more than one employer's registration that lottery year. It is USCIS's marker for *potential* abuse — not an adjudication of fraud, and the employer that ultimately filed is not necessarily the party that multi-registered the person.

## It's a behavioral change, not a composition shift

India's share of filings was essentially flat (64% → 67% → 70% → 67%), so the rise isn't a country-mix effect. The rate rose *within* every origin group:

| Multi-reg rate among filed petitions | FY21 | FY22 | FY23 | FY24 |
|---|---|---|---|---|
| India-born | 10.5% | 23.4% | 30.0% | **34.9%** |
| China-born | 5.4% | 4.6% | 8.1% | **10.1%** |
| All other | 2.9% | 2.9% | 3.9% | **4.2%** |

## The real cut: India × IT-services staffing

A bare "India 24.6% vs China 6.9%" is true but under-specified. The phenomenon is an India × IT-staffing interaction (NAICS 5415, computer-systems-design services), pooled FY21–24:

| | IT services (NAICS 5415) | Other industries |
|---|---|---|
| India-born | **33.5%** (n=156,643) | 9.7% (n=93,082) |
| Other-born | 6.9% (n=20,543) | 4.6% (n=102,573) |

India-born beneficiaries *outside* IT services run ~10% (still double other countries); India × IT-services reaches **45.4% by FY2024**. The sector is half the story.

## The inversion: small staffing shops, not Big Tech

The reflex is to blame the large outsourcers. The data says the opposite. Multi-registration rates among the biggest filers:

Amazon 3.6%, Infosys 3.1%, TCS 4.7%, Cognizant 4.5%, Microsoft 3.3%, IBM 3.1%.

The extreme rates are tiny staffing firms — Aclat Inc. 88 of 88 petitions (100%), Snowstack LLC 96.8%, R2 Technologies 91.9%. A clean size gradient (employers bucketed by total FY21–24 filings):

| Employer size (filings) | Employers | Petitions | Multi-reg rate |
|---|---|---|---|
| 1–9 | 54,807 | 105,504 | 20.4% |
| 10–49 | 4,656 | 91,430 | **35.2%** |
| 50–199 | 551 | 46,972 | 19.8% |
| 200–999 | 98 | 38,537 | 4.4% |
| 1,000+ | 29 | 90,398 | **3.2%** |

**1,815 employers with ≥10 filings and a ≥50% multi-reg rate account for 46% of all multi-registered petitions.** Employers filing fewer than 50 petitions hold 79% of them. The gaming lived in thousands of small staffing firms, not the household-name outsourcers.

## The pool was worse than the filings show

Our number counts *filed* petitions, which understates the lottery pool: many multi-registered beneficiaries were selected but never filed. USCIS's registration-level statistics:

| Cap FY | Eligible registrations | Multi-reg share of registrations |
|---|---|---|
| 2021 | 269,424 | 10.4% |
| 2022 | 301,447 | 29.9% |
| 2023 | 474,421 | 34.8% |
| 2024 | 758,994 | **53.9%** |

The pool share rose *faster* (10.4% → 53.9%, 5.2×) than our filed-petition rate (8.2% → 25.5%, 3.1×) — so selection bias makes our figure **conservative**, not inflated.

## The "after": the FY2025 rule

This is the "before" picture of the FY2025 **beneficiary-centric** rule (one lottery entry per person regardless of how many employers register them). USCIS's own numbers close the arc: multi-registered *registrations* fell **408,891 → 47,314 (−88%)** in one year, and total eligible registrations dropped from 759k to 470k. The gaming the trend documents is the exact behavior the rule was written to end.

## Hard caveats (on the page)

- Every rate is "among selected-and-filed petitions" unless labeled as the registration pool.
- Aggregate only — individual "one person → N shell companies" chains cannot be reconstructed (FOIA-redacted keys).
- "Multi-registered" is USCIS's flag for potential abuse, not proven fraud. If naming small high-rate employers, print the flag definition + n beside the table (or publish the size gradient without names).
- Coverage: FY2021–2024, cap-subject lottery petitions, frozen snapshot.

## Deep-link targets for outreach

Trend + pool tables → this page's anchors. Broader H-1B pay context → `/salaries/`. Forward context: the Dec-2025 weighted-selection proposed rule (Federal Register 2025-23853).

## Journalist hook (outreach email — Tier-3, held for approval)

"USCIS never published the multi-registration rate over time. From the FOIA'd I-129 microdata it tripled — 8% to 25% of filed petitions FY21→FY24 — and USCIS's own registration data puts the pool past 50%. The surprise: it's small staffing firms with 90–100% rates, not the big outsourcers (Infosys 3.1%, Amazon 3.6%). Method + tables: <url>."
