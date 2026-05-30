# r/cscareerquestions post — publish Sun 2026-05-31 (14:00–16:00 UTC)

⚠️ HIGHEST RISK in the campaign. r/cscareerquestions is 2.35M subs (top posts 2-3k↑) but strict on self-promo and prone to mod removal. Posting here at all is a calculated risk — we mitigate by leading with the DATA, framing as analysis-with-source, not as a tool-pitch.

Sunday posting is suboptimal for tech subs (engagement is much lower than weekday morning ET). **Recommend pushing to Mon 6/1 morning if user prefers safety over fitting strictly into "next week".**

## Title

Analyzed 1.5M DOL H-1B + PERM filings — what top tech employers certify on the LCA (base-wage floor by role, employer, state)

## Flair

Verify Sunday — sub uses "Experienced", "New Grad", "Meta", "Student". Probably "Meta" (= meta-discussion about the industry) or no flair. **DO NOT use "Resource"** if it exists — that flair is a self-promo signal here.

## Body

Pulled the entire DOL H-1B + PERM disclosure dataset (1.5M records, 287k employers, FY2008–2026) to look at one question: what do top tech employers actually certify on the LCA — the base-wage floor they swore to under penalty of perjury, by role + employer + state.

A few patterns from the data:

**1) That floor is public and searchable.**

It's the legal minimum for the role at that location — not the offer, but the number they can't pay below. Pull exactly what [Employer] certified for [Software Engineer III in California] by year and quote it back in a negotiation.

Big Tech sponsors with the deepest filing history (useful for FY2024–2026 wage comparisons): Google, Meta, Amazon, Microsoft, Apple, Nvidia, Oracle, Salesforce, JPMorgan Chase, Capital One. Large staffing / consultancy operations (Cognizant, Wipro, Infosys, HCL, Tata Consultancy) also show up at high H-1B volume — useful if you're comparing offers against a body-shop counter.

**2) Certified wages span a wide band even at the "same" company / role.**

Across software-engineer titles (FY2022+), the 25th–75th percentile of certified base wages runs about $113k–$158k — roughly 1.4×, and wider at individual employers. Geography explains some (Bay Area > Austin > Atlanta), but seniority + role specialization explain more.

**3) Filing volume held steady ~100k–130k a year, FY2016–FY2024.**

The most recent fiscal years (FY2025–26) look low in the data only because DOL is still publishing those disclosures — that's a reporting lag, not a demand signal, so don't read a drop into them.

The full data and per-employer / per-role / per-state breakdowns are at visa-bulletin.us. Free, no signup, no ads. Methodology / column definitions in the first comment along with specific page links.

What I'd appreciate: if you spot a company profile where the numbers look wrong (employer-name clustering misses, role-misclassification), comment with which one. That's the most useful kind of feedback.

## First comment (post within ~60s, sticky)

Support (if this saves you time and you want to keep it running):
• Buy me a coffee: https://buymeacoffee.com/vyakunin
• GitHub Sponsors: https://github.com/sponsors/vyakunin

Data sources + methodology:

• Top sponsors leaderboard (by H-1B volume): https://visa-bulletin.us/employers/rankings/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions
• Search salaries: https://visa-bulletin.us/salaries/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions
• Example employer profile (Google): https://visa-bulletin.us/employer/google-llc/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions
• Example body-shop comparison (Tata Consultancy): https://visa-bulletin.us/employer/tata-consultancy-services-limited/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions
• SWE example role: https://visa-bulletin.us/job-title/software-engineer-161559609/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions
• Per-state CA salaries: https://visa-bulletin.us/salaries/by-state/CA/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=cscareerquestions

Caveat that bears repeating: certified wages are base salary only — RSUs, bonuses, sign-on are NOT in DOL data. Use levels.fyi for total-comp comparison; use this for the guaranteed floor an employer swore to pay.

## Pre-flight checklist (Sun 2026-05-31)

- [ ] r/cscareerquestions self-promo rules RE-READ in full (this is the highest-risk sub of the campaign)
- [ ] If a moderator pinned post about tools / data posts exists, follow its guidance literally
- [ ] All URLs return 200 with UTM intact
- [ ] Posting window: 14:00–16:00 UTC Sunday (low traffic but lower mod presence; tradeoff)
- [ ] First comment within ~60s, sticky from OP menu
- [ ] Verify single send via outbox
- [ ] Data findings in the body MUST be accurate — re-verify the wage ranges + top-employer lists against the salary search page Sunday morning, do NOT post outdated numbers
- [ ] If mods remove within 30 min, DO NOT repost or modmail aggressively — accept the L, document in this file

## Risk mitigations baked into this draft

1. Body leads with FINDINGS, not the tool. The tool appears as data source 8 paragraphs in.
2. No promo language ("free, no signup" appears once, mid-paragraph).
3. Donations link is in the first comment (sticky), not in body.
4. UTM tracking is in the comment links only — body has no link wall.
5. Numbers in the body MUST be verifiable from the site at post time (re-check Sun morning).

## Recommended alternative: Mon 6/1 morning posting

If user prefers safety: push to Mon 2026-06-01 10:00-12:00 ET (14:00-16:00 UTC). r/cscareerquestions weekday morning engagement is 5-10× weekend. Cost: 1 day past "next week".
