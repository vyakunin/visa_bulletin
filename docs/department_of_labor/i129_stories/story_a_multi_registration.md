# Story (a) — Multi-registration in the H-1B lottery tripled, FY2021→FY2024

**Lever-3 link-bait data story. Target surface:** `/analysis/h1b-multi-registration-lottery-gaming/`
**Status:** DRAFT — numbers verified against live prod `i129_petition` 2026-07-13.
**Source/attribution (Apache-2.0, required):** "sourced from USCIS, obtained by Bloomberg" (Bloomberg v. DHS FOIA release, NBER w34793 dataset).

---

## Verified numbers (prod, 2026-07-13)

Share of **filed H-1B petitions** whose beneficiary was flagged by USCIS as
multi-registered (`ben_multi_reg_ind`), by fiscal year:

| FY | Filed petitions | Multi-registered | Rate |
|----|-----------------|------------------|------|
| 2021 | 99,610 | 8,148 | **8.2%** |
| 2022 | 89,535 | 15,159 | **16.9%** |
| 2023 | 91,832 | 20,892 | **22.8%** |
| 2024 | 91,864 | 23,401 | **25.5%** |

**Headline: the multi-registration rate tripled in four years — from 1-in-12 filed
petitions (FY2021) to 1-in-4 (FY2024).**

Concentrated by country of birth (FY21–24 combined, petitions with ≥3,000 filings):

| Country | Filed petitions | Multi-reg rate |
|---------|-----------------|----------------|
| India | 249,725 | **24.6%** |
| China | 54,486 | 6.9% |
| South Korea | 4,231 | 3.8% |
| Taiwan | 4,537 | 3.5% |
| Mexico | 3,748 | 0.7% |
| Canada | 4,129 | 0.6% |

India-born beneficiaries drive essentially the entire trend: a 24.6% multi-reg rate
vs 6.9% for China and under 4% everywhere else.

## Framing (honest, no overclaim)

- USCIS itself flagged the multi-registration surge as the reason it moved to a
  **beneficiary-centric selection** for the FY2025 lottery (one entry per beneficiary
  regardless of how many employers register them). The FY2021→FY2024 curve above is the
  "before" picture that rule was written to end. **This is the datapoint the policy
  change was aimed at.**
- Say "multi-registered," not "fraud." `ben_multi_reg_ind=1` means the beneficiary
  appeared in multiple employers' registrations that year — USCIS treats the spike as
  abuse-driven, but a minority reflects genuine multiple job offers. State the flag's
  definition; let the trend speak.

## Hard caveats (must appear on the page)

- **Aggregate only.** The per-beneficiary linking keys (confirmation #, DOB, receipt #)
  are 100% FOIA-redacted, so we publish the *rate* by year/country — we cannot and do
  not reconstruct individual "one person → N shell-company" chains.
- **Coverage: FY2021–2024, cap-subject lottery petitions only.** Frozen FOIA snapshot,
  not a live feed. Denominator = selected-and-filed I-129 petitions (not the full 1.8M
  registration pool, which we don't hold).
- Label the coverage window prominently so it's never mistaken for current.

## Deep-link targets for outreach (each claim → a verifiable URL)

- The trend table → this page's own anchor.
- "India-concentrated" → the country-rate table on this page.
- Supporting salary context → `/salaries/` (LCA base-wage DB) for the broader H-1B pay picture.

## Journalist hook (for the outreach email, Tier-3 — held for approval)

"USCIS never published the multi-registration rate over time. We computed it from the
FOIA'd I-129 microdata: it tripled from 8% to 25% between FY2021 and FY2024, almost
entirely India-driven — the exact abuse the FY2025 beneficiary-centric rule was written
to stop. Full method + table: <url>."
