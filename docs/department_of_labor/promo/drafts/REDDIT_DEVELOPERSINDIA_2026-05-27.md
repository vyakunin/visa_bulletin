# r/developersIndia post — publish Wed 2026-05-27 (target 02:00–04:00 UTC = morning India)

r/developersIndia is 1.54M subs, "wholesome community" tone, tool posts land well (top 10 includes "Built an app to compare Swiggy/Zomato"). India-heavy audience = direct overlap with H-1B/PERM filers. Goldmine for the employer + salary surfaces.

Frame is DIFFERENT from the immigration drafts: this audience cares about which US companies actually hire on H-1B and what they pay — NOT priority-date predictions. (Do NOT pitch PERM count as a GC-sponsorship signal — see `.claude/rules/perm_messaging.md`. PERM filings have collapsed in 2026; the ratio is no longer informative.)

## Title

Indexed 1.5M DOL H-1B + PERM filings — search which US companies actually sponsor for your role (free, no signup)

## Flair

Verify Tuesday — sub has many flairs; "Tools" or "Resource" if available, otherwise no flair.

## Body

Built a free database of every H-1B and PERM filing the US Department of Labor has published. 1.5M records across 287k employers, going back several fiscal years.

What's useful in it (especially when you're evaluating a US offer or planning to switch):

• **Certified salary by role + employer + state** — what the company swore to pay you under penalty of perjury on the LCA. Excludes RSUs / bonuses (those aren't in DOL data), so it's the floor, not the total comp. Useful for negotiation: you can see exactly what [Employer] certified for [Software Engineer III in California] across the last few years.

• **H-1B filing volume per employer** — which US companies are actually hiring on H-1B in your role, and how that's trended. Examples on the site: Google, Meta, Amazon, Microsoft, Tata Consultancy, Accenture.

• **Per-state salaries** — useful when an offer says "remote" but you want to see where the company's filings actually went.

Honest about what it isn't:

• Not actual offer letters — base salary only, no RSUs / bonuses / sign-on.
• Doesn't include roles that didn't need an LCA filing (so non-sponsorship-track roles are invisible).
• A few employers file under multiple legal-entity names (we cluster these, but coverage isn't perfect — flag mismatches in comments).

Free, no signup, no email, no ads. Links in the first comment.

What I'd appreciate: tell me which employer's data looks wrong, or which features are missing. Particularly interested in: better job-title clustering ("SWE III" vs "Software Engineer III" rollup), wage growth per employer over time, location heatmaps. Comments here drive what I build next.

## First comment (post within ~60s, sticky)

Support (if this saves you time and you want to keep it running):
• Buy me a coffee: https://buymeacoffee.com/vyakunin
• GitHub Sponsors: https://github.com/sponsors/vyakunin

Specific pages, as promised:
• Top sponsors by H-1B volume: https://visa-bulletin.us/employers/rankings/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• Search salaries (by company / role / state): https://visa-bulletin.us/salaries/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• Example employer profile (Google): https://visa-bulletin.us/employer/google-llc/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• Example employer (Tata Consultancy): https://visa-bulletin.us/employer/tata-consultancy-services-limited/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• Example job-title (Software Engineer): https://visa-bulletin.us/job-title/software-engineer-161559609/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• Per-state salaries (California): https://visa-bulletin.us/salaries/by-state/CA/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=developersindia
• (Also have a visa bulletin priority-date predictor with a backtest, separate from the salary DB — happy to share that link if anyone's curious)

## Pre-flight checklist (Wed 2026-05-27)

- [ ] r/developersIndia self-promo rules re-checked (sub has detailed rule pinned post — re-read Wednesday morning)
- [ ] All URLs return 200 with the UTM params intact
- [ ] Posting window: 02:00–04:00 UTC Wednesday (= 07:30–09:30 IST = peak Indian morning commute / pre-work)
- [ ] First comment within ~60s, sticky from OP menu
- [ ] Verify single send via outbox
- [ ] Do NOT lead body with the visa bulletin predictions — that's a different audience need; mention only as PS in the comment

## UTM scheme

- utm_source=reddit (where the click came from)
- utm_medium=social
- utm_campaign=may2026_promo (this fan-out)
- utm_content=developersindia (which sub)

GoatCounter shows query strings in the path, so the 6 paths above will each appear separately in the dashboard, broken down by sub. Verify visibility in GC after first 100 clicks — if query strings get normalized away, we'll need to bake the tracking into the path itself (e.g. /salaries/?ref=reddit-devindia → /salaries/r-devindia/).

## Why this sub gets the salary-DB pitch (NOT the predictions pitch)

r/developersIndia is filled with people currently working/about-to-work in the US tech industry. They care about: which company actually sponsors, what they pay, how their offer compares. They do NOT care (today) about EB-2 India priority date math — they're earlier in the funnel. Save the priority-date pitch for r/EB2 / r/immigration / r/greencard where it's the right product.
