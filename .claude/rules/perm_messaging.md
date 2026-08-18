# PERM messaging guidance

**Do not pitch PERM filing count, PERM-to-H-1B ratio, or "this employer files PERMs" as a signal of green card sponsorship — in outbound copy (Reddit, blog posts, HN, social, press, partnership decks, ads) or on the site itself (page copy, stat tiles, captions, chart labels, meta descriptions, JSON-LD).**

The site is the strongest form of the claim, not a milder one: it makes it about a named company, under our own byline, on a page a search engine indexes and a recruiter or candidate reads as a verdict. So the same words that get cut from a draft get cut from a template.

The framing was load-bearing in the Mar–May 2026 promo drafts; it has to be retired.

## Why

As of mid-2026 PERM filings have collapsed: very few employers are filing PERMs at all, the scene around the program is a mess (policy chaos, processing-time uncertainty, employer reluctance), and the per-employer PERM count is no longer informative about whether a company will actually sponsor a green card. Pitching "PERM ratio = real GC intent" reads outdated to the audience and bakes in a claim the data doesn't currently support.

## How to apply

**Strip these claims wherever they appear:**

- "PERM = the green card route" / "PERM is real GC sponsorship" / "H-1B-only means no GC path"
- "PERM-to-H-1B ratio = sponsorship intent / commitment"
- "Companies that file PERMs are the ones actually moving people through" / "low PERM ratio = no GC progress"
- Sub-bullet finds like "High PERM ratio (≥40%): X, Y, Z" / "Low PERM ratio (<15%): body shops"
- Comment-link copy like "Top sponsors leaderboard (ranked by PERM activity)" / "Top sponsors by PERM activity"
- "Pick the company → check whether they file PERMs in your category" framing
- "Employers that actually file PERMs (real EB-2 sponsors) vs only H-1Bs"

**Keep neutral / factual mentions:**

- "Indexed every DOL H-1B and PERM disclosure (1.5M records)" — describes data scope, fine.
- "Data source: public LCA and PERM disclosure files" — fine.
- "Search by visa program (H-1B vs PERM)" — fine, that's a UI filter the user can apply.
- Title hashtags / SEO tokens that include `PERM` — fine, they describe the dataset, not a sponsorship-intent claim.
- A per-employer PERM filing COUNT, and a plain description of what PERM is ("labor certification, the first green card step") — fine, both are facts about the disclosure record. It is the RATIO, and any caption reading it as intent, that is retired.

The line on the site: a count, a program label, or a dataset-composition percentage inside a table of programs is factual. A percentage promoted to a headline tile, or any caption telling the reader what the number says about a company, is the claim.

**Lead with the salary-floor framing instead.** The certified base wage on the LCA is the durable selling point: under penalty of perjury, by role + employer + state, useful for negotiation. That's the one factual claim that holds independent of how the PERM program is doing month-to-month.

**Sponsor leaderboards** still exist and are fine to link to — just describe them by H-1B volume, not by PERM activity ("Top sponsors by H-1B volume", not "Top sponsors by PERM activity").

## Where to push back

If a generated draft contains the retired framing, edit before publishing — do not ship.

If a user prompt asks for "show me PERM-sponsoring companies" as a feature, point them at this rule and ask whether they want to:
- describe the leaderboard as H-1B volume (default), OR
- explicitly include the PERM-collapsed caveat in the pitch (less common; only when the audience is sophisticated enough that the caveat helps rather than confuses).

## Files touched on 2026-05-28 to apply this rule

- `docs/department_of_labor/promo/drafts/REDDIT_*.md`
- `docs/department_of_labor/promo/scheduled/reddit_*.yaml`

Older promo strategy docs (`IMPLEMENTED_FEATURES_AND_PROMO_STRATEGY.md`, `REVISED_LAUNCH_STRATEGY.md`) describe the data scope and pre-2026 framing; they're historical and not used for active outbound — left alone unless re-activated.

## Origin

2026-08-18: The employer profile carried the retired claim in the product. Every `/employer/<slug>/` page rendered a "Green Card Ratio" percentage under "Higher = stronger green card commitment" — 240,106 pages, 14,731 of them showing 0.0% in red against a named company. The rule's scope named outbound copy only, so the UI had never been swept. Scope widened to the site; the ratio and the caption removed, the H-1B and PERM counts kept (ticket `3b862b8d409f81679112ec651be79fa6`).

2026-05-28: User flagged during /listen_chat review of immigration + developersIndia drafts about to publish — "Perm is not a thing anymore, virtually no one files them, scene is a mess. Drop this point" — applied to all drafts and codified here so future drafts don't reintroduce it.
