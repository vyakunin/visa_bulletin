# r/greencard post — publish Tue 2026-06-09 (14:00–16:00 UTC)

(Rescheduled 2026-05-22 from Sat 5/30 → Tue 6/9 — Sat dropped per "prime days only" Tue/Wed/Thu, W3 spreads campaign over 3 weeks. Note: r/greencard tone is casual approval-story so weekday timing matters less than for tech subs, but Tue still gives the best US-morning visibility window.)

r/greencard is 65k subs, median top-10 score 48, 515 comments across top 10. Tone is casual celebration ("JUST GOR APPROVED IN MY GREEN CARD" — all caps, typos, exclamation) BUT importantly: tool posts CAN land. Top 10 this month includes "USCIS just gave my green card tracker app direct API access — looking for beta testers" — that's the template to match.

Dec 2025 our greencard post got 1↑/0 — almost certainly AutoMod / timing fail. This re-attempt uses the casual + tool-tester template instead of the analytical one.

## Title

Built a green card priority date predictor + database of every H-1B / PERM filing — looking for testers + feedback

(Matches the "looking for beta testers" template that landed in their top 10 this month. Casual, tool-explicit, two-product framing because both halves matter to this audience.)

## Flair

None (top 10 doesn't use flair).

## Body

Hi r/greencard — built two things and they connect, looking for people who'll try them and tell me what's broken.

**1) Priority date predictor**

For every EB category × country (and FB too — F1 through F4), the model predicts where the next bulletin's cutoff will land, and shows you which signals went into the prediction. There's a public accuracy archive of every past prediction vs the real cutoff — that's the page to open first because it's the only honest way to judge if the model is worth trusting.

Honest about limits: works well on slow-moving categories (India EB-3, EB-2 India), rough at fiscal-year boundary, and useless at predicting USCIS policy moves before they're announced.

**2) Employer + salary database**

Indexed every DOL H-1B + PERM disclosure — 1.5M records, 287k employers. You can look up a specific company and see:

• Certified base wages by role, by year, by state — the LCA floor an employer swore to under penalty of perjury
• H-1B filing volume per role and year
• Approval rate
• Top job titles they sponsor and median salary for each

Most useful when an offer comes in and you want a hard floor on the base salary to negotiate against. RSUs/bonuses aren't in DOL data, so this is the floor, not the total — but it's a number the employer legally certified, not a glassdoor data point.

**The two halves connect**

Pick the company → look at their certified wages for your role + state → cross-check with what your priority date is likely to do in the prediction model. Together they sketch what an offer is really worth.

Free, no signup, no email gate. Specific links in the first comment so this stays readable.

What I'd love: poke around, tell me what's broken or missing. Especially: a category where the prediction has been wrong, or a feature that would change your decisions.

## First comment (post within ~60s, sticky)

Support (if this saves you time and you want to keep it running):
• Buy me a coffee: https://buymeacoffee.com/vyakunin
• GitHub Sponsors: https://github.com/sponsors/vyakunin

Specific pages, as promised:
• EB predictions + accuracy archive: https://visa-bulletin.us/predictions/employment_based/2026-6/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• FB predictions + accuracy archive: https://visa-bulletin.us/predictions/family_sponsored/2026-6/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• How the model works (methodology): https://visa-bulletin.us/analysis/how-my-prediction-model-works/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• Top sponsors leaderboard (by H-1B volume): https://visa-bulletin.us/employers/rankings/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• Example employer profile (Google): https://visa-bulletin.us/employer/google-llc/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• Example job-title page (Software Engineer): https://visa-bulletin.us/job-title/software-engineer-161559609/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard
• Per-state salaries (e.g. California): https://visa-bulletin.us/salaries/by-state/CA/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=greencard

UTM tracking: utm_content=greencard (each sub in this campaign tagged separately).

## Pre-flight checklist (Monday 2026-06-01)

- [ ] r/greencard rules re-checked (AutoMod removed Dec 2025 post — verify what specifically triggers it now)
- [ ] Check account karma + age against r/greencard's threshold (sub appears to have stricter AutoMod than r/USCIS or r/immigration based on Dec failure)
- [ ] All URLs return 200 Mon morning
- [ ] No commenter tags (Dec post had 0 comments)
- [ ] Posting window: 14:00–16:00 UTC Tuesday (US morning rush)
- [ ] First comment within ~60s, sticky from OP "..." menu
- [ ] Verify single send (Reddit compose double-fire race)
- [ ] If r/immigration + r/EB2 posts landed cleanly, that's social proof that the AutoMod issue is sub-specific — could modmail r/greencard with the prior posts as evidence if this one gets filtered

## Why this sub gets the "looking for testers" framing

The May 2026 top 10 has a successful tool post: "USCIS just gave my green card tracker app direct API access — looking for beta testers". Same template = "I built X, looking for testers, here's what it does, free." That's the proven path through r/greencard's mod culture. Avoids the analytical/clinical tone of r/EB2 (wrong audience match) and the policy-aware tone of r/immigration (this sub is more upbeat about individual cases, less policy-anxious).

## What if it gets AutoMod-filtered again

Most likely cause: link count or specific domain. v3.1 structure (1 link in body, rest in comment) is designed to minimize this. If filtered:
1. Modmail r/greencard mods with the r/immigration + r/EB2 post URLs as evidence of similar content landing cleanly on adjacent subs.
2. Wait 48h for response, do NOT repost.
3. If denied with reason: fold into a future variant. If denied without reason or silent removal: take the L, the audience reach isn't worth ban risk.
