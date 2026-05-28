# r/USCIS follow-up post — publish Tue 2026-05-26

Adapted from `REDDIT_FOLLOWUP_2026-05-20.md` v3.1 (the post that was prepared for r/h1b but pulled after the r/h1b mod team silently removed v1 on 2026-05-21). r/USCIS is an independent mod team (zero human-mod overlap with r/h1b) and the December 2025 USCIS post got real engagement (17↑ / 33 comments), so the r/h1b removal does NOT carry over.

**Voice rules carry over:** 1st-person ABOUT THE MODEL ok, 1st-person STAKE NOT ok, lead with what changed, be honest about limits, no "best/most accurate/guaranteed", donations stay in the first comment (not the body).

**Adjustments vs r/h1b v3.1:**

1. Intro paragraph references the **r/USCIS** December thread, not r/h1b.
2. Tagged commenters trimmed to those who actually commented on the **r/USCIS** December post (u/Most_Bother8759, u/blyubird, u/arika1447, u/Former_Inflation3504). r/h1b-only commenters (Few_Criticism_9715, _rogue_1, ThisCorgi4904, Salt-Progress1354, throwaway0845reddit) removed — tagging them in an r/USCIS thread would look like astroturfing.
3. Body link count: 1 (the original r/USCIS thread back-ref). Everything else moves to the first comment, same anti-AutoMod structure as r/h1b v3.1.

---

## Title

Built a model that predicts the next visa bulletin — open to critique

(Selected 2026-05-22 after rejecting two earlier options: "(December follow-up)" suffix implied too much context, and "Update for everyone who asked about better predictions" leaned on prior-post context. This title leads with the tool, signals openness to feedback, no archive/accuracy language, no "check out my" anti-pattern.)

**Flair:** Resource (verify r/USCIS allows it Tuesday morning before posting)

---

## Body

Hi everyone — back with an update on visa-bulletin.us. In December I posted a visualizer for 10 years of bulletin movement here (https://www.reddit.com/r/USCIS/comments/1pbpki2/i_visualized_10_years_of_visa_bulletin_priority/) — the projection logic was a naive extrapolation, and several of you called that out:

u/blyubird: estimates should be based on the backlog, visa availability, ROW demand, I-140 trends, projected spillovers — not just past dates

u/Most_Bother8759: find out all the measurable variables that actually affect the delay/approval timeline

u/arika1447: combine historical USCIS data + historical bulletin movements; predict on quarterly data

u/Former_Inflation3504: when EB-1 India = 2050 and EB-2 = 2036, something is wrong — trends are not linear

Fair points. I rebuilt the prediction system around them.

What's new on the prediction side (specific page links in the first comment so the post stays clean):

• Full methodology write-up explaining the signals and their weights.

• Public accuracy archive: model prediction vs real DOS cutoff, every category, every month, as far back as the data goes. This is the page worth opening first — it's how I keep myself honest.

• For each prediction, the page shows which signals contributed and how much weight each got — so a "100% no-change baseline" is a clear flat-line warning.

• Where it's still solid: long-stalled categories with steady recent movement (e.g. India EB-3 / EB-2).

• Where it's still rough: anything near an October cutoff (USCIS demand shocks the model can't see), EB-5 reserved buckets (low volume), and any month where DOS announces a policy change.

I grade this against reality every month. If the accuracy archive is wrong for your category, tell me which.

What else I shipped — DOL salary database (new since the December post):

I indexed 1.5M DOL H-1B + PERM disclosure records (the certified-wage filings every sponsor has to make). You can search them by company, role, or state — example pages in the first comment.

Caveat that bears repeating: this is base salary only (what employers swore to pay under penalty of perjury on the LCA). It excludes RSUs / bonuses / sign-on. If you're benchmarking Big Tech, Levels.fyi is closer to total comp; this is the certified floor — the number the employer is legally on the hook for.

The two halves connect: pick a company you're interviewing with → see what they certified for your role + state → compare to what your priority date is likely to do under the prediction model. (Note added 2026-05-28 — the original published version of this post on r/USCIS included a PERM-as-GC-signal framing here that has since been retired across the campaign per `.claude/rules/perm_messaging.md`; PERM filings have collapsed in 2026 and the framing is no longer informative.)

If this saves you time, there's a support link at the top of the first comment.

Feedback: poke around, tell me what's helpful, what's broken, happy to improve anything.

Thanks to everyone who took the time to comment on the December thread — I read all of them. Hope to see more!

---

## First comment (post immediately after body lands; sticky from OP "..." menu)

Support (if this saves you time and you want to keep it running):
• Buy me a coffee: https://buymeacoffee.com/vyakunin
• GitHub Sponsors: https://github.com/sponsors/vyakunin

Specific pages, as promised in the post:
• 2026-06 predictions + accuracy archive: https://visa-bulletin.us/predictions/employment_based/2026-6/
• How the model works (methodology): https://visa-bulletin.us/analysis/how-my-prediction-model-works/
• Example employer profile (Google): https://visa-bulletin.us/employer/google-llc/
• Example job-title page (Software Engineer): https://visa-bulletin.us/job-title/software-engineer-161559609/
• Per-state salaries (e.g. California): https://visa-bulletin.us/salaries/by-state/CA/

---

## Pre-post checklist (Tuesday 2026-05-26 morning)

- [ ] r/USCIS rules re-checked for self-promo / tool-link policy (mod list as of 2026-05-22: AmIStillOnFire, BeefyTheCat, renegaderunningdog, ep2789, uiulala, AutoModerator, bot-bouncer — 7 mods, more conservative than r/h1b's 4)
- [ ] All linked URLs return 200 (verify Tuesday morning, not on Friday — the SEO push pages may shift)
- [ ] Tagged usernames spell-check: u/Most_Bother8759, u/blyubird, u/arika1447, u/Former_Inflation3504 (re-hover each on Reddit before submit)
- [ ] Account karma + age check for u/CivilCandidate1349 on r/USCIS specifically (sub may have its own threshold)
- [ ] Posting window: aim for **~22:00 UTC Tuesday** (afternoon Pacific / morning India / matches the December r/USCIS post's engagement window)
- [ ] If r/h1b mods reply to modmail between now and Tuesday with substantive feedback, fold that into the draft before firing
- [ ] After post lands: post the first comment within ~60s, then sticky it from the OP "..." menu
- [ ] Verify single send via outbox (per the "single-click semantics" rule) — Reddit's compose UI can double-fire on Enter

## What NOT to do on r/USCIS

- ❌ Tag r/h1b-only commenters (Few_Criticism_9715, _rogue_1, ThisCorgi4904, Salt-Progress1354, throwaway0845reddit) — they didn't comment on the USCIS thread
- ❌ Reference the r/h1b removal in the body — irrelevant noise to USCIS readers and signals "got rejected elsewhere, retrying here"
- ❌ Cross-post to r/h1b same day — wait until the r/h1b mod conversation resolves
- ❌ Post r/greencard variant in parallel — December r/greencard got 1↑/0 comments, likely AutoMod-buried, not worth the spam-filter risk
