# PERM messaging guidance

**Do not pitch PERM filing count, PERM-to-H-1B ratio, or "this employer files PERMs" as a signal of green card sponsorship in any outbound copy (Reddit, blog posts, HN, social, press, partnership decks, ads).**

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

2026-05-28: User flagged during /listen_chat review of immigration + developersIndia drafts about to publish — "Perm is not a thing anymore, virtually no one files them, scene is a mess. Drop this point" — applied to all drafts and codified here so future drafts don't reintroduce it.
