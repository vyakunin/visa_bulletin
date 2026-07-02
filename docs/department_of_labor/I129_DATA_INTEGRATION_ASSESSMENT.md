# I-129 Petition Data — Integration Assessment

**Date:** 2026-06-29 · **Status:** **LIVE ON PROD (2026-07-02).** Both data halves
graduated + verified: I-129 pay-comparison (372,841 rows) and the USCIS Data Hub
approval-rate (355,969 rows / 205,127 linked). Employer + role pages render the
sections on prod.
**Spike verified against live prod + the real dataset.**

**Update 2026-07-02 (later) — USCIS Data Hub approval data GRADUATED TO PROD.**
Ran the FY2019–2024 Data Hub ingest off-prod on the minipc staging stack (after a
fresh prod→staging reseed): **355,969 `UscisEmployerApproval` rows**, linker
`--target uscis` matched **205,127/355,969 rows (57.6%)** — lower than i129's ~85% due
to the long tiny-employer tail, but all high-volume employers match. Spot-check diff
(staging vs prod, google-llc) showed the ONLY delta = the new approval-rate section
(98.4% initial, 9,905 petitions FY19–24); broad top-URL diff gate byte-identical.
Graduated via `cutover.sh --data 1dd2f9a` (same image → data-only, no code change) —
**first live `--data` cutover.** The cutover process was killed mid-run (after the DB
resync completed, before the connector cut-back); the cut-back (homeserver web+redis
flush → restart `shared_cloudflared` → drop staging prod-connector → smoke → resume
ingest) was completed by hand and the end-state verified (google/microsoft/amazon
render the section, homeserver sole prod connector, bubba back, ingest resumed, CF
edge purged). See "Robustness follow-up" below.

**Update 2026-06-30 — Phase-1 data load VALIDATED ON STAGING (off-prod).** Ran the
full Bloomberg FY21–24 ingest into the minipc staging DB: **372,841 `I129Petition`
rows** (FY21 99,610 / FY22 89,535 / FY23 91,832 / FY24 91,864). **Worksite_record
join rate 97.7% / 99.7% / 99.6% / 99.5%** by FY (the doc's 96.2% below was the
certified-only subset). FY2024 wage delta reproduces: mean actual **$126,194** vs
LCA-posted **$101,593** = **+$24,601 (+24%)**, median actual $98,000 ≈ LCA $95,000
(same Borjas gap — median≈, mean ~20%+ above). Two ingest bugs fixed en route
(commits b7593b2, bed3bc8): GitHub-raw URL case canonicalization (discover
lowercases → 404), and uscis must use the `bulk_create` load path (the COPY
preflight assumes the SalaryRecord wage schema). **DONE — i129 data live on prod
(372,841 rows), graduated via the reseed→ingest→`cutover.sh --data` path.**

**Update 2026-07-02 — Lever 1 employer-side built.** (a) The actual-pay comparison
now renders on **`/employer/<slug>/`** too, scoped by a new
`I129Petition.employer_cluster` FK (migration 0053) that
`lib/business/i129/employer_linker.py` backfills — mapping `employer_name` →
`EmployerCluster` by NORMALIZED name (exact match ≈ 0 rows: USCIS "Infosys Limited"
vs LCA "INFOSYS TECHNOLOGIES LIMITED" both normalize to `infosy`), highest-LCA-volume
cluster winning ties. Backfill = `scripts/i129/backfill_employer_links.py` (heavyweight
Path-2 → run off-prod on staging). (b) The **approval-rate half's ingest foundation is
built**: `UscisEmployerApproval` model (migration 0054) + `uscis_datahub` plugin
(parses the real UTF-16 / TAB / leading-line-number-column files) + `SourceType
.H1B_EMPLOYER_HUB`, registered in `run_pipeline`. Data is fetchable from the GitHub
mirror `JohnBroberg/H1B_Hub` (`data/Employer_Information_<YYYY>.csv`) — the uscis.gov
download is Akamai-anti-bot-walled (403 to non-browser clients). **DONE 2026-07-02:
FY2019–24 ingest + `--target uscis` link + the `/employer/` approval-rate section are
all live on prod** (see the 2026-07-02 update at top). All code build + suite green;
tests cover the pay-comparison scoping, the linker, and the Data Hub parse.

## Robustness follow-up (2026-07-02 first live `--data` cutover)

`cutover.sh --data` completed the DB resync (homeserver DB fully consistent) but its
process was killed before the connector cut-back — so `shared_cloudflared` was left
stopped and the staging prod-connector left up (prod stayed served by the minipc; no
vb outage, but bubba stayed down and ingest stayed paused until the manual cut-back).
The EXIT-trap recovery did NOT fire (SIGKILL skips traps). Cause: the cutover was
launched as a `setsid` child while a separate background monitor loop was polling it;
killing the monitor appears to have taken the cutover with it. **Fix for next time:**
run `cutover.sh` as a blocking foreground call (or a hardened nohup/disown that can't
be reaped by a monitor's process-group kill), and never share a process group between
the cutover and its watcher. Consider a `cutover.sh --resume` that detects "resync
done, cut-back pending" and finishes steps 5–7 idempotently.

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

### Wage delta — COMPUTED 2026-06-29 (the headline number)

Full FY2024 join (not a sample): 62,383 distinct petition cases → **60,001 (96.2%)**
matched to **certified** `worksite_record` rows; per-case actual pay (`BEN_COMP_PAID`,
hourly annualized ×2080) vs the LCA-posted `wage_annual` vs annualized `prevailing_wage`.

| | actual paid | LCA-posted | prevailing floor |
|---|---|---|---|
| **median** | $99,720 | $96,000 | $87,194 |
| **mean** | $124,653 | $104,368 | — |

- **Actual vs LCA-posted:** 71.8% pay actual ≈ posted (±1%); **26.3% pay *above* the
  posted LCA wage** (16.2% >10% above); only 1.9% below. **Median ratio = 1.000** — the
  median worker is paid exactly the LCA position wage — but the **mean is +$20,285
  (+19.4%)**, so the gap lives entirely in the upper quartile (equity-aside cash base).
- **Actual vs prevailing floor:** 21.1% at/below the floor, 41.1% within 5%, 51.4%
  within 10%; median actual is 9.3% above the floor. The floor-clustering story persists
  at the individual-pay level, not just the LCA-posted level.
- **This is the direct answer to Borjas's open LCA-vs-actual question** (NBER w34793):
  for the median, actual = posted; in the mean, actual runs ~19% higher. No free
  competitor surfaces this. Caveat for any published comparison: base wage ≠ total comp
  (no equity/bonus), so cross-employer "who pays more" claims are unsupported.

Verified-join recipe lives in the spike scratchpad (`analysis2.sql` / `analysis3.sql`);
prod staging tables dropped after the run.

## Other government-published sources (verified 2026-06-29)

The I-129 record-level data is NOT routinely published — Bloomberg's is a one-time FOIA
release. But two adjacent sources ARE government-direct, and one is *live*:

- **USCIS H-1B Employer Data Hub** (CSV, **FY2009 → FY2026 Q2**, updated quarterly):
  first-decision **approval/denial counts per employer × FY × NAICS × city/state/ZIP**,
  initial vs continuing. **No wages, no beneficiary demographics, no LCA join key.**
  → Source the **approval-rate feature (FIRST_DECISION)** from THIS, not Bloomberg — it's
  live, gov-direct, back to FY2009, and carries no FOIA/aggregation caveat. Bloomberg is
  needed only for **actual pay + demographics**, which the Data Hub lacks.
  `uscis.gov/tools/reports-and-studies/h-1b-employer-data-hub`
- **USCIS "Characteristics of H-1B Specialty Occupation Workers"** (annual PDF, FY24
  latest): aggregate tables — median/25th/75th compensation by occupation, country of
  birth, sex, education, age. PDF-only, pre-aggregated, **not joinable** → corroboration /
  a context citation, not ingestible microdata.
- USCIS H-1B **registration statistics** (annual report) — aggregate lottery counts only.
- **DOL** publishes LCA (what we ingest) + PERM — **not I-129**.

### Beneficiary de-identification in the Bloomberg release (verified 2026-06-29)

Every per-beneficiary linking key is **100% FOIA-redacted** (exemptions b3/b6/b7c):
`bcn` (beneficiary confirmation #), full `ben_date_of_birth`, and `RECEIPT_NUMBER` are
**0 populated** across all 350,103 single-reg + 408,891 multi-reg FY2024 rows. The
beneficiary survives only as `country_of_birth` + `ben_year_of_birth` (age) + `gender` —
**no name, no DOB, no passport, no synthetic ID.** Named entities are only the
**employer** (company) and the **agent** (attorney). Consequence for the multi-reg story:
USCIS pre-computes `ben_multi_reg_ind=1` (the entire `multi_reg` file = the multi-
registered set), so we can publish the multi-reg **rate** by year/employer/country, but
**cannot reconstruct individual "one person → N shell-company" chains** — the linking key
is withheld. Multi-reg gaming is an **aggregate** story, not named/linked individuals.
(This also means "publish aggregates only" is partly enforced by the data itself.)

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
  96–98% join, **computed the actual-vs-posted-vs-prevailing wage delta** (see "Wage
  delta — COMPUTED" above). This doc. Build tracked in Notion (Project=visa_bulletin):
  the **Phase-1 ingest GATE** ticket + 3 lever tickets (Lever 1 page enrichment, Lever 2
  pSEO demographic clusters, Lever 3 link-bait data stories).
- **Phase 1 — ingest CODE DONE (2026-06-29):** `models/i129.py` `I129Petition` model
  (normalized `dol_eta_case_number` — **non-unique**: a single LCA covers multiple
  beneficiaries, ~1.7k shared case numbers in FY2024 alone, so uniqueness would drop
  co-beneficiaries — annualized `comp_paid_annual`/`pay_annual`, `wage_amt`/`unit`,
  demographics, dates, H-1B-dependent/willful-violator flags) + ingest plugin
  `lib/ingest/plugins/uscis_i129.py` (downloads + concatenates the split zips, extracts
  the CSV, streams it, keeps only rows with a real DOL ETA case number = the joinable
  petition set). Migrations `0050`/`0051`, registered in `run_pipeline`, unit tests green
  (`tests/test_i129_plugin.py`). Joins to `worksite_record.case_number`.
  **REMAINING: the data load is a heavyweight Path-2 task** — run the ingest OFF-PROD on
  staging (`bazel run //scripts/ingest:run_pipeline -- discover --domain uscis` then
  `run --domain uscis`), validate counts + the ~96% worksite join, then graduate the DATA
  via `cutover.sh --data` (per `branching.md`). Not a direct-prod run.
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
