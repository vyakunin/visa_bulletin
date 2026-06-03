# People Search — Build Scope (named PERM applicant search)

> ## ⛔ DATA PREMISE DISPROVEN (2026-06-02) — feature NOT buildable as scoped
>
> Verified directly against the live DOL disclosure files (New-Form PERM
> FY2024_Q4, FY2025_Q4, FY2026_Q2): **the foreign-worker beneficiary name is NOT
> present in any PERM disclosure file DOL publishes.** Evidence:
> - The new ETA-9089 PERM files have 135–137 columns and carry only
>   **employer-POC, attorney (`ATTY_AG_*`), and preparer (`DECL_PREP_*`)** names —
>   no beneficiary name column.
> - Each row only flags `FW_INFO_APPX_A_ATTACHED = Y`; the worker's name is on
>   **Appendix A, which DOL does not publish for PERM** (it publishes Appendix A
>   for CW-1 / H-2B / LCA only — there is no `PERM_Appendix_A` file on the
>   disclosure page).
> - Published Appendix A files don't contain names regardless: the LCA Appendix A
>   is 5 columns (`CASE_NUMBER`, # exempt workers, institution, field of study,
>   degree date). "Appendix A" in disclosure = supplemental info, not identities.
>
> **The 2026-06-01 "premise corrected → feasible" claim below was wrong:** it
> conflated the ETA-9089 *form* (which collects the name) with the *published
> disclosure data* (which never releases it). There is no public DOL source of
> PERM beneficiary names tied to cases, so a named-applicant search cannot be
> built from data we ingest. **Everything below is retained for the record only.**
>
> **Re-verified 2026-06-02 (owner pushback — "I saw my name"):** downloaded the
> live DOL files and grepped every cell. Old-form PERM FY2008–FY2014 (25–27 cols:
> employer/job/wage/country-of-citizenship/class-of-admission — **no name column
> at all**), new-form PERM FY2024 (135 cols) and FY2026 Q2 (137 cols): zero
> beneficiary-name column in any; the only person-name columns are employer-POC,
> attorney/agent, and preparer. H-1B/LCA record layout confirmed identical — only
> employer/contact/attorney/preparer names; the worker appears only as a *count*.
> A grep for the owner's surname returned **0 hits across all PERM years
> FY2008–FY2014 + FY2024 + FY2026**. Premise stays disproven across both form
> versions and the H-1B program. (Not row-grepped: FY2015/16 PERM + the full H-1B
> data files — same nameless layouts, so structurally cannot contain a name.)
>
> **Viable pivot (same files):** an attorney / law-firm search IS feasible —
> `ATTY_AG_FIRST/MIDDLE/LAST_NAME` + `ATTY_AG_LAW_FIRM_NAME` are in every PERM row
> (and LCA has analogous attorney fields). Professionals acting commercially, so
> none of the doxxing/brand risk of naming applicants. Awaiting owner direction.

> **Decision (owner, 2026-06-01):** build it. The earlier feasibility/ethics
> review (kept as an appendix below) leaned against a public named-search
> feature; the owner has weighed that and decided to proceed. This doc is now an
> **engineering scope**, not a should-we review.
>
> **Decisions locked (owner, 2026-06-02)** — all four §7 questions resolved:
> 1. **Separate `PermApplicant` table** (PII segregated from the hot table).
> 2. **Person pages INDEXABLE** — owner override of the noindex recommendation.
>    Rationale: it's publicly available government data; the goal is to make it
>    accessible and capture long-tail search traffic. The reversibility-asymmetry
>    + doxxing/brand risk was raised and explicitly accepted. The per-case
>    `suppressed` opt-out + a takedown path are now the primary harm mitigation
>    (see §5); ship them on day one.
> 3. **Open to all** — throttle-only, no gating.
> 4. **Coverage accepted** — PERM-only, FY2024+, H-1B never named.

**Status:** scoped + decisions locked, not started.
**Coverage reality (state up front):** names exist **only** in the revised
**PERM ETA-9089** disclosure files (FY2024+). LCA/H-1B files never name the
beneficiary. So this feature covers **PERM (green-card labor-cert) applicants
from FY2024 onward only** — not H-1B workers, not pre-FY2024 PERM. Set
expectations accordingly: it is a partial index by construction.

---

## 0. What we already have vs. what's missing

| Piece | State today |
|---|---|
| Source files with names | ✅ already downloaded (revised ETA-9089, FY2024+) |
| Name columns parsed into the per-row dict | ✅ `read_excel_rows` reads every column |
| Name columns mapped/persisted | ❌ `PERM_COLUMN_MAPPINGS` doesn't list them → discarded |
| DB field for applicant name | ❌ none on `SalaryRecord` |
| Name search index | ❌ |
| Search API + UI | ❌ (but employer/job-title autocomplete precedent exists) |

The whole build = **stop discarding the name columns, persist + index them,
expose a guarded search**. No new data source, no scraping.

---

## 1. Data layer

**Recommended: a separate `PermApplicant` model, not inline fields on
`SalaryRecord`.** Keeps PII physically segregated from the 1.5M-row hot table,
so it can be access-controlled, feature-gated, bulk-purged, or redacted without
touching the core analytics table or its indexes.

```python
# models/perm_applicant.py (one class per file)
class PermApplicant(models.Model):
    # 1:1 with a PERM SalaryRecord, joined on the unique case_number
    case_number    = models.CharField(max_length=50, unique=True, db_index=True)
    first_name     = models.CharField(max_length=120, blank=True)
    middle_name    = models.CharField(max_length=120, blank=True)
    last_name      = models.CharField(max_length=120, blank=True)
    full_name_norm = models.CharField(max_length=300, db_index=True)  # normalized for search
    suppressed     = models.BooleanField(default=False)  # opt-out kill switch per case
    ingest_version = models.ForeignKey("IngestVersion", on_delete=models.CASCADE, ...)
```

- `full_name_norm` = lowercased, accent-folded, whitespace-collapsed
  "last first middle" — the column the trigram index sits on.
- Migration adds the table + a **GIN trigram index** on `full_name_norm`,
  mirroring `models/migrations/0047_salary_record_title_trigram_indexes.py`
  (`gin_trgm_ops`). Must be `CREATE INDEX CONCURRENTLY` via
  `RunSQL(..., atomic=False)` per `deployment.md` heavy-mutation rule (don't take
  an AccessExclusiveLock next to the live 1.5M-row table).

**Alt (rejected):** inline `fw_*` fields on `SalaryRecord`. Simpler join, but
bloats the hot table + its indexes with PII that's null for ~all LCA rows and
pre-FY2024 PERM rows. Segregation wins.

## 2. Ingest

1. **Confirm the exact revised-ETA-9089 column headers first.** Run
   `scripts/ingest/inspect_source_columns.py` against a **FY2024+** PERM file
   (the existing default points at FY2020, the *old* form with no names).
   Expected headers follow the `FW_INFO_*` family already seen in
   `dol_perm_supply.py` (`FW_INFO_CTRY_OF_CIT`) — likely
   `FW_INFO_FIRST_NAME` / `FW_INFO_LAST_NAME` / `FW_INFO_MIDDLE_NAME` or the
   Appendix-A long forms. **Do not hardcode until verified against a real file.**
2. Add an `applicant_first/middle/last` block to `PERM_COLUMN_MAPPINGS`
   (`lib/parsing/salary/db_importer.py`) listing all observed header variants.
3. In `dol_perm.py` `transform()` (~line 220): after the existing
   `SalaryRecord` is built, if name columns are present, build/emit a
   `PermApplicant` keyed by the same `case_number`. Guard on presence — older
   files yield no names → no `PermApplicant` row. Use the framework's batched
   writer, not per-row saves.
4. LCA plugin: untouched (no names there).

## 3. Backfill

Only revised PERM files carry names, so backfill is bounded — not a full
re-ingest:

- Targeted `scripts/oneoff/backfill_perm_applicant_names.py`: re-read just the
  FY2024+ PERM source files, pull `case_number` + name columns, upsert
  `PermApplicant` (batched, `ignore_conflicts`). Avoids re-running the whole
  pipeline. ~minutes for a handful of FY files.

## 4. Search API + UI

- **Autocomplete endpoint** `/api/applicant-autocomplete/` mirroring
  `company_autocomplete_view` (registered in `webapp/urls.py`): trigram
  similarity on `full_name_norm`, top-N, rate-limited, excludes `suppressed`.
- **Results / person view**: name → the public case facts already in
  `SalaryRecord` (employer, job title, SOC, wage, prevailing wage, worksite,
  dates, status). Reuse the salary-search rendering.
- **Search page** `/people/` mirroring `salary_search_view`
  (`webapp/views/salary/search.py`).

## 5. Abuse / SEO controls (engineering — ship WITH the feature, not after)

- **Indexability — DECIDED 2026-06-02: person pages ARE indexable** (owner
  override; goal is accessibility + search traffic). Still implement an
  `X-Robots-Tag` / `<meta robots>` toggle wired to an env var (default
  `index,follow` per the decision) so it can be flipped to `noindex` instantly
  without a template redeploy — this is the single biggest harm lever and must
  stay one env flip away. Because pages are indexed, the **`suppressed` opt-out
  and a takedown path become load-bearing**, not optional: a person who asks to
  be removed must drop out of results immediately (hidden from search + the page
  410/noindex'd) so Google de-indexes it.
- **Rate-limit** `/api/applicant-autocomplete/` and `/people/` at nginx (mirror
  the existing bot rate-limit map in `deployment/nginx/`).
- **Feature flag** (env, e.g. `PEOPLE_SEARCH_ENABLED`) so the whole surface can
  be toggled/killed instantly without a template redeploy.
- **Opt-out**: `suppressed` flag per `PermApplicant` (case_number → hidden).

## 6. Effort + phasing

| Phase | Work | Est. |
|---|---|---|
| 1. Data + ingest + backfill | model, concurrent-trigram migration, mapping, transform, backfill script | ~1–1.5 d |
| 2. Search API | autocomplete endpoint + rate-limit + feature flag | ~0.5–1 d |
| 3. UI + SEO controls | `/people/` page, results render, noindex/sitemap exclusion | ~1 d |
| **Total** | | **~3–3.5 d** |

(Matches the earlier ~3–5 d ballpark.)

## 7. Decisions before Phase 1 — ALL RESOLVED (owner, 2026-06-02)

1. ✅ **Separate `PermApplicant` table** (PII segregated). Inline rejected.
2. ✅ **Person pages indexable** (`index,follow` default), env-toggle to `noindex`
   retained. Owner override of the noindex recommendation — see locked-decisions
   block at top + §5.
3. ✅ **Open to all** — throttle/rate-limit only, no gating.
4. ✅ **Coverage accepted** — PERM-only, FY2024+ only, H-1B never named.

No open decisions remain; Phase 1 is unblocked.

---

## Appendix — risk review (owner-acknowledged, retained for the record)

The owner has decided to build despite these; kept so the tradeoffs aren't lost.

- **Legal:** GDPR/CCPA-CPRA treat name + immigration status as personal /
  sensitive personal information; FCRA risk if third parties use profiles for
  employment/housing/credit decisions; state anti-doxxing statutes. Mitigated
  (not eliminated) by: public government record, PERM-only, noindex, opt-out,
  rate-limit, feature-flag kill switch.
- **Brand / growth channel:** the Reddit promo channel (CivilCandidate1349;
  r/immigration already bans us) could read "search immigrants by name" as
  doxxing → bans + trust loss with the anxious audience the site serves. The
  `noindex` default + PERM-only scope + low-key framing are the levers that keep
  it from reading as a surveillance tool.
- **Search-engine permanence:** the reason person pages default to `noindex`.

## Sources

- DOL ETA-9089 Appendix A "Foreign Worker Information" + PERM record layout
  (FY2024+ revised form carries First/Middle/Last name).
- Internal: `lib/ingest/plugins/dol_perm.py`,
  `lib/parsing/salary/db_importer.py` (`PERM_COLUMN_MAPPINGS`),
  `models/salary.py`, `models/migrations/0047_*` (trigram pattern),
  `webapp/views/employers/` (autocomplete), `webapp/views/salary/search.py`,
  `scripts/ingest/inspect_source_columns.py`.
