# Story (c) — H-1B lottery odds depended on how many times you were registered

**Lever-3 link-bait data story. Target surface:** `/analysis/h1b-lottery-odds-by-year/`
**Status:** PUBLICATION DRAFT — built from USCIS published registration statistics (our DB holds only selected+filed petitions, not the pool). Conditional-odds design red-teamed in `RIGOR_REVIEW.md`.
**Sources:** USCIS H-1B Electronic Registration statistics FY2021–2026 (uscis.gov is Akamai-blocked to non-browser clients; figures mirrored by WSM Immigration, Gibney, and Ogletree/NatLawReview). Microdata corroboration: "sourced from USCIS, obtained by Bloomberg."
**Universe:** cap-subject H-1B registration lottery. These are odds of **selection**, not of getting a visa (selected registrations still must be filed and approved).

---

## Headline

Before the 2024 rule change, your H-1B lottery odds weren't a single number — they depended on how many employers registered you. In FY2024, a single-registration beneficiary had about a **25%** chance of selection; the average multi-registered beneficiary (~4.3 registrations) had about **70% — a 2.8× advantage**. The FY2025 beneficiary-centric rule deleted that asymmetry: **29% for everyone**, and ~415,000 duplicate entries evaporated.

## Layer 1 — the per-registration selection rate

Selections ÷ eligible registrations, from USCIS:

| Cap FY | Eligible registrations | Selected | Per-registration rate |
|---|---|---|---|
| 2021 | 269,424 | 124,415 | 46.2% |
| 2022 | 301,447 | 131,924 | 43.8% |
| 2023 | 474,421 | 127,600 | 26.9% |
| 2024 | 758,994 | 188,400 | 24.8% |
| 2025 | 470,342 | ~135,137 | ~28.7% per reg (**28.9% per beneficiary**) |
| 2026 | 343,981 | 120,141 | ~34.9% |

**Caveat that rides this table:** FY2021–22 rates are inflated because USCIS ran multiple selection rounds when many selectees never filed. "Selected" is not "got an H-1B."

## Layer 2 — the real story: odds per beneficiary, by registration count (pre-FY25)

Selection was uniform across registrations, so a beneficiary with *k* registrations had roughly 1 − (1 − p)^k odds:

| Cap FY | p (per reg) | k = 1 | k = 2 | k = 3 | k = 5 |
|---|---|---|---|---|---|
| 2023 | 26.9% | 26.9% | 46.6% | 61.0% | 79.2% |
| 2024 | 24.8% | 24.8% | 43.5% | 57.5% | 76.0% |

FY2024 concretely: the average multi-registered beneficiary held ≈4.3 registrations (408,891 multi-reg registrations ÷ ~95,897 multi-reg beneficiaries, using USCIS's ~446,000 unique-beneficiary figure), for **≈70% odds vs 24.8% for a single registration — a 2.8× advantage.** That asymmetry is exactly what the FY2025 rule removed: every beneficiary now has identical odds regardless of employer count (28.9% in FY25, ~35% in FY26, because the pool shrank ~415k once duplicate entries stopped paying off).

## Layer 3 — corroboration from the FOIA microdata

Our selected-and-filed petitions show the multi-registration share rising 8.2% → 25.5% (FY21→24) while the registration-pool share rose 10.4% → 53.9% — demonstrating both the over-selection advantage and the lower filing propensity of speculative multi-registrations. (See story (a).)

## Caveats (on the page)

- "Odds of **selection**," never "odds of a visa."
- FY21/22 per-registration rates are inflated by multiple non-filing rounds.
- The k-conditional table uses the binomial identity 1 − (1 − p)^k (independence approximation; finite-population correction is negligible at k ≤ 10 out of 759k). The only estimated input — ~4.3 average registrations — traces to USCIS's own published ~446k unique-beneficiary count.
- Never publish a bare "your odds were X% in FY2024" without the single-vs-multi conditioning; the unconditional number was practically meaningless pre-FY25, which is the whole point.

## Deep-link targets for outreach

The three exhibits (per-FY rate, k-conditional table, FY25/26 before-after) → this page's anchors. Method + microdata → story (a) and `/salaries/`.

## Journalist hook (outreach — Tier-3, held for approval)

"H-1B 'lottery odds by year' is the wrong frame. Pre-2024, odds depended on how many employers registered you: ~25% with one, ~70% for the average multi-registered beneficiary — a 2.8× gap the beneficiary-centric rule erased (29% for everyone, 415k duplicate entries gone). Three exhibits from USCIS's own numbers: <url>."
