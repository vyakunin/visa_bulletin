# Story (b) — The H-1B "gender pay gap" is a sorting story, not an unequal-pay story

**Lever-3 link-bait data story. Target surface:** `/analysis/h1b-gender-pay-gap-decomposition/`
**Status:** PUBLICATION DRAFT — figures verified against live prod `i129_petition` 2026-07-13; the raw "~4% gap" headline was RED-TEAMED OUT (see `RIGOR_REVIEW.md`), reframed to the decomposition.
**Attribution:** "sourced from USCIS, obtained by Bloomberg" (Bloomberg v. DHS FOIA release; same microdata as Borjas, NBER w34793).
**Universe:** FY2021–2024, cap-subject **new-hire lottery** petitions, selected-and-filed. Pay = **employer-reported I-129 rate of pay** (`BEN_COMP_PAID`), prospective and base-only — not payroll earnings, no equity/bonus/hours. Aggregates only.

---

## Headline

In the **same job title**, H-1B women and men are paid essentially the same: an adjusted gap of **+0.3% at the mean, −0.9% at the median** across 388 title×year strata (107,000 petitions). The much-quoted raw gap — and the far larger 16–25% raw gaps among Chinese- and other-born workers — is about **which jobs** men and women hold, not different pay for the same job.

## What the raw numbers look like (and why they mislead)

Trimmed to $20k–$1M (raw values run from $0.01 to $169M, so trimming is mandatory):

- Men: mean $102,766 / median $94,000 (n = 244,503)
- Women: mean $98,014 / median $90,057 (n = 119,682)
- Raw gap: **+4.8% mean, +4.4% median** — and narrowing over time (+6.9% FY21 → +3.9% FY24).

Taken alone, that reads like a pay-equity story. It isn't. H-1B base pay is anchored to the Labor Condition Application position wage, so within a given role there is little room for two workers to be paid differently — the aggregate gap has to come from *composition*.

## The decomposition

Comparing men and women **within the same job title** (title × fiscal year strata, ≥20 of each gender, weighted by stratum size):

| Comparison | Strata | Petitions | Adjusted gap |
|---|---|---|---|
| Within job title | 388 | 107,068 | **+0.29% mean / −0.85% median** |
| Within employer | 275 | 93,245 | +5.3% mean |
| Within title × employer | 401 | 50,121 | +1.0% mean |

The 4% raw gap essentially disappears within identical titles. Within an employer it *widens* — because at a given company men and women hold different, differently-leveled titles; hold the title fixed too and it collapses back to ~1%.

## The most striking result: the 25% "Chinese-born gap" vanishes

| Origin | Raw mean gap | Raw median gap | Adjusted (within title) |
|---|---|---|---|
| India-born (n=244,517) | +0.9% | +0.5% | **−0.2%** |
| China-born (n=53,075) | **+16.4%** | **+25.4%** | **+0.7%** |
| Other-born (n=66,593) | +15.4% | — | +2.9% |

India-born workers — two-thirds of the sample — show ~0 gap even before controls, which is what drags the overall figure down to 4%. The eye-catching 16–25% raw gaps among Chinese- and other-born beneficiaries collapse to ≤3% once you compare the same job. Occupational sorting, not unequal pay.

Education explains nothing (the raw gap persists within Bachelor's/Master's/Doctorate), and age composition works *against* the raw gap (men are older, and older bands show the *smallest* gaps).

## Mandatory caveats (on the page)

- **Titles encode seniority.** "Senior Software Engineer" is a title; equal pay *within* a title does not rule out gendered differences in *reaching* the senior title. The classic controlled-gap critique cuts both ways, and we say so.
- **Base pay only.** The I-129 reports prospective base compensation — no equity or bonus, which is exactly where tech-sector gender gaps tend to concentrate. This is a floor-wage comparison, not total comp.
- **Employer-reported, prospective.** `BEN_COMP_PAID` is the rate of pay stated on the petition, not verified payroll.
- **Sample.** New-hire cap-lottery petitions, FY21–24. 33.5% of rows have a blank job title (a redaction-era source artifact); the decomposition uses the non-blank subsample, and a representativeness check confirms the raw gap is nearly identical in the blank (+5.5%) and non-blank (+4.5%) halves, so it isn't cherry-picking. (Treating "blank" as its own stratum would fake a +3.1% "within-occupation" gap — a trap we flag explicitly.)

## The related "actual vs posted wage" number — read it correctly

The FOIA data also lets us compare reported pay to the LCA-posted position wage. Lead with the **median: the ratio is exactly 1.000** — the typical H-1B worker's reported pay equals the posted wage, and 71.8% are within ±1% of it. The oft-cited "+19–24%" is a **mean** effect driven entirely by the upper quartile. "H-1B workers are paid ~20% above the posted wage" is not a defensible summary; "the typical worker is paid the posted wage, and about one in four is paid above it, sometimes well above" is. (Whether that mean premium is a big-tech composition artifact needs the heavy LCA join — specified as off-prod staging SQL, not yet run.)

## Follow-up angles

- Occupational segregation as its own piece: female share by title (Software Engineer 28%, Senior SWE 20%, Architect 23% vs Data/Business Analyst 45–47%) with median pay per title.
- Field-of-study cut (same stratified method).
- Off-prod: does the above-posted-wage premium itself split by gender within employer?

## Journalist hook (outreach — Tier-3, held for approval)

"Everyone quotes a raw H-1B gender pay gap. In the FOIA'd I-129 microdata it's ~4% — but it vanishes to +0.3% within the same job title, and the dramatic 25% raw gap among Chinese-born workers collapses to under 1%. It's occupational sorting, not unequal pay for the same role. Full decomposition + caveats: <url>."
