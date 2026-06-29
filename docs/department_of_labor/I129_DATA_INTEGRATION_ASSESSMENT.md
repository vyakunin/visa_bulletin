# I-129 Petition Data — Integration Assessment

**Date:** 2026-06-29 · **Status:** assessment / proposal (no code yet)
**Spike verified against live prod + the real dataset.**

## TL;DR

Bloomberg published the FOIA-obtained USCIS **I-129 petition + H-1B registration**
data (FY2021–2024) openly on GitHub under **Apache-2.0**. It carries the **actual
beneficiary pay** and rich beneficiary demographics — data our LCA-based platform has
never had. It joins to our existing LCA `worksite_record` at **~98%** (verified). The
unique value: surface **actual individual pay vs LCA position wage vs prevailing wage**,
plus demographic cuts (country, gender, education, field) and the lottery /
multi-registration story — none of which any free competitor shows. Hard limits:
**FY2021–2024 only, cap-subject lottery petitions only, frozen FOIA snapshot** (no live
updates), and individual-level data → **publish aggregates only** (re-identification).

## Source

- Repo: `github.com/BloombergGraphics/2024-h1b-immigration-data`
- License: **Apache-2.0**. Required attribution: *"sourced from USCIS, obtained by
  Bloomberg."* (Permits commercial use + redistribution with license notice + stated
  changes.)
- Origin: Bloomberg v. DHS FOIA litigation. USCIS systems: H-1B Registration System,
  CLAIMS3, ELIS (queried 05/2024, TRK #13139).
- This is the same I-129 data George Borjas merges in his NBER wage-gap paper (w34793).

## Two grains in the data

| Grain | Rows (FY21–24) | Has wage? | Has join key? | Key contents |
|---|---|---|---|---|
| **Registration** | 1,804,286 | ❌ no | ❌ no | beneficiary demographics, employer, `status_type` (Selected/Eligible/Created), `ben_multi_reg_ind` (multi-registration gaming flag), lottery_year |
| **Petition (I-129)** | 376,613 receipts | ✅ `WAGE_AMT`/`WAGE_UNIT`, `BEN_COMP_PAID` | ✅ `DOL_ETA_CASE_NUMBER` | worksite, job title, validity dates, basis-for-classification, education/field, country, sex, NAICS, H-1B-dependent + willful-violator flags |

Petition-level wage + join key exist **only for selected-and-filed** registrations
(~68k/yr in the FY2024 single-reg file: 350,103 rows → 85,304 SELECTED → 68,482 with a
`DOL_ETA_CASE_NUMBER`, 67,292 with `BEN_COMP_PAID`).

### Key fields (petition grain)

- `BEN_COMP_PAID` — beneficiary's rate of pay **per year** (the headline "actual pay").
  Blank when the wage is hourly; `WAGE_AMT`+`WAGE_UNIT` (YEAR/HOUR) is the raw figure —
  **we annualize hourly ourselves** (×2080) for parity with our LCA `wage_annual`.
- `DOL_ETA_CASE_NUMBER` — join key to our LCA data. **Hyphen-less** in Bloomberg
  (`I20023263363671`) vs our hyphenated `I-200-23263-363671`. Normalize by
  `'I-200-' || substr(c,5,5) || '-' || substr(c,10)` (or strip hyphens on our side).
- Demographics: `BEN_COUNTRY_OF_BIRTH`, `gender`/`BEN_SEX`, `ben_year_of_birth` (age),
  `BEN_EDUCATION_CODE`/`ED_LEVEL_DEFINITION`, `BEN_PFIELD_OF_STUDY`.
- Lifecycle: `valid_from`/`valid_to` (term), `BASIS_FOR_CLASSIFICATION`
  (A=new, E=change of employer, F=amended, …), `FIRST_DECISION`.

### Join rate — VERIFIED 2026-06-29

Sampled 1,996 FY2024 selected-petition case numbers (normalized) against prod:
**1,960 matched `worksite_record` (98.2%)**, 0 in `salary_record` (expected — the H-1B
full universe lives in `worksite_record`). ~2% miss ≈ LCA filed in a different FY than
the lottery year, or not in our ingested set. Join is production-viable.

## What it unlocks (value vs every free competitor)

Every free H-1B salary site (h1bdata.info, h1bgrader, our own `/salaries/`) shows the
**LCA offered wage** — the wage for the *position*. None show the **actual individual
pay** or beneficiary demographics. The I-129 data adds:

1. **Actual pay vs LCA-offered vs prevailing** — a three-way comparison. The LCA-vs-I-129
   gap is exactly what Borjas flagged he should examine; no public tool surfaces it.
2. **Demographic cuts** — pay by country of birth, gender pay gap within H-1B, by
   education level / field of study. Genuinely novel.
3. **Lottery + multi-registration gaming** — selection rates, `ben_multi_reg_ind`
   (the "one beneficiary, many shell registrations" abuse story). High public/SEO interest.
4. **Employer compliance signals** — H-1B-dependent + willful-violator flags per employer.
5. **Term & basis** — change-of-employer vs new vs extension mix.

## Caveats / risks

- **Coverage:** FY2021–2024 only; **cap-subject lottery** petitions only (cap-exempt
  universities/nonprofits + most extensions/transfers are out). Wage exists only for the
  ~68k/yr selected+filed; the 1.8M registration pool has no wage.
- **Frozen snapshot:** USCIS does not routinely publish I-129; this is a one-time FOIA
  release. Not extendable forward without new FOIA → a **historical enrichment, not a
  live data line.** Label coverage prominently so it's never mistaken for current.
- **Privacy / re-identification:** individual rows pair DOB + employer + wage + country.
  Source is already public, but we should **publish only aggregates** (and suppress
  small-n cells) — do not expose row-level beneficiary records.
- **Annualization:** hourly `WAGE_AMT` rows need ×2080 to compare to our `wage_annual`.

## Integration plan (phased)

- **Phase 0 — spike (DONE 2026-06-29):** downloaded FY2024, confirmed fields, verified
  98% join. This doc.
- **Phase 1 — ingest:** new `I129Petition` model (normalized `case_number`, annualized
  `comp_paid_annual`, `wage_amt`/`unit`, demographics, dates, flags). Ingest plugin reads
  the zipped CSVs (mirror `dol_lca.py` shape). FK / join to `worksite_record` on
  normalized case number. Attribution block in the model + page footer.
- **Phase 2 — "What H-1B workers are actually paid":** an aggregate analytical page —
  actual-pay vs LCA-offered vs prevailing, sliced by occupation / metro / employer /
  country / education. **Aggregates only**, small-n suppression.
- **Phase 3 — lottery & multi-registration story:** selection rates + multi-reg gaming
  page. SEO/traffic play, ties to current policy debate.

## Recommendation

Worth doing. Actual-pay + demographics is a real differentiator against every free
competitor, and the "actual vs offered vs prevailing" gap is both a product feature and a
citable headline stat. Start with **Phase 1 ingest + the headline actual-vs-offered-vs-
prevailing aggregate**. Caveat coverage (FY21–24, cap lottery) prominently everywhere it
shows.

## Related

- `WORKSITE_FILES_DESIGN.md` — the `worksite_record` (LCA full-universe) design this joins to.
- `lib/ingest/plugins/dol_lca.py` — the ingest-plugin pattern to mirror.
