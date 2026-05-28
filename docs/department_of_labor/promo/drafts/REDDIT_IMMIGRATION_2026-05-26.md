# r/immigration post — publish Tue 2026-05-26 (14:00–16:00 UTC)

Replaces the original r/USCIS Tuesday slot (pivoted 2026-05-22). r/immigration is the broadest target: 259k subs, median top-10 score this month = 405, 2.5k comments across top 10. No flair pressure. Tone is policy-aware + personal-story heavy; deportation / USCIS-changes threads dominate. Tool posts must arrive value-first.

## Title

Built a model that predicts the next visa bulletin (EB + FB) — looking for cases where it's wrong

(Includes both employment + family bulletin categories because this sub spans both audiences, unlike the EB-only r/EB2 variant.)

## Flair

None (verify Tuesday — sub doesn't appear to enforce flair on top posts).

## Body

A lot of the posts here in the last month have been about policy uncertainty: green card cuts, vetting holds, deportations. Predicting priority-date movement under that kind of policy noise is hard — but the model I've been running tries anyway, and grades itself against reality every month.

A few honest things up front:

• It's a statistical model on public data (DOS bulletins, DOL disclosures). It can't see USCIS internal decisions or policy shifts before they're announced.

• It works well on long-stalled categories (India EB-3, EB-2 India for the most part) where the floor changes slowly.

• It's bad at any month where DOS announces a policy change, at fiscal-year boundary (October), and at low-volume categories (EB-5 reserved, F4 some countries).

• There's a public accuracy archive: prediction vs reality, every category × country, every month, as far back as the data goes. That's the page worth opening first — if the model's been wrong for your category, I want the example.

I also indexed every DOL H-1B and PERM disclosure (1.5M records). Most useful as a salary reference — you can look up an employer and see the certified base wages they've filed for a given role / state / year. Base salary only, no RSUs or bonuses, but it's the floor an employer swore to under penalty of perjury, so it's negotiation-grade.

Both halves are free, no signup, no email gate. Specific links in the first comment so this post stays readable.

What I'd most appreciate: tell me a category × country × month where the prediction was wrong, and what actually happened. The accuracy archive shows the misses, but the comments are where I figure out which kinds of misses matter.

## First comment (post within ~60s of body, sticky from OP menu)

Support (if this saves you time and you want to keep it running):
• Buy me a coffee: https://buymeacoffee.com/vyakunin
• GitHub Sponsors: https://github.com/sponsors/vyakunin

Specific pages, as promised in the post:
• 2026-06 predictions + accuracy archive: https://visa-bulletin.us/predictions/employment_based/2026-6/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration
• How the model works (methodology): https://visa-bulletin.us/analysis/how-my-prediction-model-works/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration
• Family-sponsored predictions: https://visa-bulletin.us/predictions/family_sponsored/2026-6/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration
• Example employer profile (Google): https://visa-bulletin.us/employer/google-llc/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration
• Example job-title page (Software Engineer): https://visa-bulletin.us/job-title/software-engineer-161559609/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration
• Per-state salaries (e.g. California): https://visa-bulletin.us/salaries/by-state/CA/?utm_source=reddit&utm_medium=social&utm_campaign=may2026_promo&utm_content=immigration

UTM scheme: utm_source=reddit / utm_medium=social / utm_campaign=may2026_promo / utm_content=immigration (each sub gets its own utm_content value; GoatCounter shows query strings as path so each sub's clicks group separately in the dashboard).

## Pre-flight checklist (Tuesday 2026-05-26)

- [ ] r/immigration self-promo rules re-checked (mod team appears small + permissive)
- [ ] All URLs return 200 Tue morning
- [ ] No commenter tags (no prior post here — tagging without prior context = astroturf)
- [ ] Posting window: 14:00–16:00 UTC (10:00–12:00 ET) — top posts cluster on weekday mornings ET
- [ ] First comment within ~60s of body, sticky immediately
- [ ] Single send via outbox (Reddit compose has double-fire race on Enter)
- [ ] Add FB predictions link to comment (this sub spans family-based too)

## Why this sub gets the "policy-aware" intro

r/immigration's top 10 this month is heavy on deportation / vetting hold / policy news. Walking in with a pure tool pitch would feel tone-deaf. Acknowledging "the policy noise is real, here's a model that tries anyway" reads as serious + matches what's on their front page.
