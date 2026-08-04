# Authoring HTML for /analysis/ blog pages

`/analysis/<slug>/` pages are `BlogPost` rows whose `content` is HTML rendered raw
(`{{ post.content|safe }}`) inside `blog/post_detail.html` → `<div class="blog-content
fs-5 text-break">`. Two rendering traps have bitten these pages; both are cheap to
avoid up front.

## Trap 1: `.text-break` breaks numbers / % / codes mid-token in tables

The `.blog-content` wrapper carries Bootstrap's **`.text-break`** = `word-break:
break-word !important`, which lets the browser break **inside a single token** when a
table column is narrow on mobile. Symptoms seen on real phones (390px): `34.9%` →
`34.` / `9%`, `16.9%` → `16.9` / `%`, `FY21` → `FY2` / `1`. It looks broken and
undermines a data page.

**Fix — already wired, keep it wired:** `post_detail.html` (`extra_head`) contains

```css
.blog-content table td, .blog-content table th {
    overflow-wrap: normal !important;   /* beats .text-break's !important */
    word-break: normal !important;      /* single tokens stay whole; headers still wrap between words */
}
```

This covers **every** `/analysis/` post (the monthly narrator's tables in
`generate_initial_blog_posts.py` *and* authored data stories) because they all render
through this one template. When authoring a NEW blog HTML surface that does *not* use
`post_detail.html`, replicate the guard there.

- **Static check (guards regressions):** `tests/test_blog_table_wrap_guard.py`
  (`bazel test //tests:test_blog_table_wrap_guard`) asserts the template still resets
  `word-break` on `.blog-content table` cells. Cheap, deterministic, no browser.
- **What the static check CANNOT prove** (a browser can): that the CSS actually wins
  the cascade at a given viewport. Confirm the true end-state with a computed-style
  read at mobile width (`verify_end_state.md`):
  ```python
  # Playwright, viewport 390px: a rate cell must compute word-break: normal
  getComputedStyle(cell).wordBreak === "normal"   # and single-line height
  ```
- The i129 story generator (`scripts/oneoff/generate_i129_story_posts.py`) also
  prepends the same rule per-post (`_TABLE_STYLE`) as belt-and-suspenders — so its
  content renders correctly even before/without a template deploy (the DB row is
  self-contained + deploy-order-independent). Redundant with the template guard by
  design; don't "clean it up".
- **That in-body `<style>` block is why `_text_excerpt` strips `<style>`/`<script>`
  ELEMENTS WHOLE, not just their tags** (`webapp/views/blog_views.py`). The excerpt
  feeds `<meta name="description">`, `og:`/`twitter:description` and the JSON-LD
  `BlogPosting.description`; a tag-only strip left the CSS text behind, so all three
  story pages shipped ~120 characters of `.blog-content table td{overflow-wrap:…}`
  before the first real word of every SERP snippet and social unfurl (found + fixed
  2026-08-04, `97fc396`). The two guards are coupled: keep the `<style>` prepend AND
  the element-level strip, or the description regresses. Pinned by
  `tests/test_blog_excerpt.py`, which is the thing to read before touching either.
  It is invisible to any rendering test — the page looks perfect; the corruption is
  only in the head.

## Trap 2: a data story must state the claim it counters, and read in isolation

A "myth-busting" data story (the common shape for link-bait: *"X is actually Y, not
Z"*) must **name the widely-held claim explicitly before rebutting it**, or the opener
reads as arguing with someone the reader can't see. A reader landing cold from search
has no shared context — the piece must supply it.

- ❌ Opening straight into the rebuttal: *"In the same job title, women and men are paid
  essentially the same… the much-quoted raw gap is about which jobs…"* — assumes the
  reader already knows the "raw gap" narrative being knocked down.
- ✅ State the common claim first, attribute it, then turn: *"A widely-cited figure says
  H-1B women earn several percent less than men (and far more for some origins). Taken
  at face value it reads as unequal pay. In this data it's almost entirely occupational
  sorting — here's the decomposition."*

Checklist for any counter-a-claim page:
1. **First** paragraph articulates the claim/narrative being addressed (what people
   believe, ideally who says it / where it comes from), so the page stands alone.
2. **Then** the finding + why the naive reading misleads.
3. No mid-argument openers that presuppose context (`the much-quoted…`, `it isn't…`,
   `not X but Y`) before the claim itself is on the page.
4. Re-read the lead as a stranger arriving from a SERP: is the subject and the thing
   being corrected clear without the headline? (The headline is not guaranteed context —
   it can be truncated in a share card.)

### No editorial / internal-process voice in the published copy

Caveats and section headings are written TO the reader, never as notes-to-ourselves
about what the piece *should* do. The tells are first-person-plural editorial verbs and
process labels:

- ❌ Headings: `Mandatory caveats`, `Hard caveats (on the page)`, `read it correctly`,
  `read them correctly` — process/imperative-to-self. → ✅ `Caveats`, `What this
  comparison does and doesn't show`, `A related figure: …`, `How to read these numbers`.
- ❌ In-body meta: `…and we say so`, `a trap we flag explicitly`, `Lead with the
  median`, `we relabel`, `note that we`. → ✅ just make the point: `…the same limitation
  that applies to any controlled pay-gap number`; `…which is why they're excluded`; `The
  median tells the honest story: …`.
- `our data` / `our number` / `our petitions` (a publication referring to its own
  dataset) is fine — that's reader-facing. The ban is on the *editorial-decision* voice
  (`we flag`, `we say so`, `mandatory`, `lead with`), not first-person dataset ownership.

This is the public-content register of `be_human_in_drafts.md` / `llm_tell_avoidance.md`
applied to data pages: write TO a cold reader, lead with the concrete claim, no
scaffolding that assumes a prior turn.

## Trap 3: don't attribute a change to one cause when many things moved

A before/after that coincides with a policy/rule change is **not proof the change caused
it** — and a rigor-branded data page must not imply it did. When a number drops (or
rises) right after a rule, ask what *else* happened in the same window before writing
"the rule did this":

- ❌ *"USCIS's numbers close the arc: eligible registrations dropped 759k → 470k. The
  gaming this documents is the exact behavior the rule was written to end."* — pins the
  whole pool drop on one rule when the FY2026 registration fee ($10 → $215), a cooler
  tech-hiring market, and enforcement all moved registrations in the same period.
- ✅ Separate the mechanically-linked effect from the confounded one, and name the
  confounders: *"the multi-registration collapse tracks the rule's mechanism (duplicates
  stopped paying off); the broader drop in how many people register reflects several
  2025 changes at once — the fee increase, a softer market — not this one measure. The
  raw before/after is not a clean natural experiment."*

Rule of thumb for these pages: claim causation only for the effect that is
*mechanically* tied to the change (here: uniform per-beneficiary odds → multi-entry
incentive gone). For everything else that merely *coincided*, say "coincided with" /
"alongside" and list the other movers. This is `be_human_in_drafts.md` §11 (no invented
causal dependencies) applied to published data stories.

## Origin
2026-07-13 — the i129 FOIA data stories: (1) `34.9%` / `FY21` broke mid-token on mobile
in every table (Bootstrap `.text-break`), fixed template-wide + static-tested; (2) the
gender-gap story opened mid-rebuttal ("*is a sorting story, not an unequal-pay story*")
without stating the raw-gap claim it counters — Vladimir: *"starts as if arguing with
someone… make sure we explicitly articulate the claims we are countering and the article
reads fine in isolation."*
