# Reddit follow-up post — 2026-05-20

Built off feedback from the December 2025 launch posts. Structure per user
ask: link back to original post → thank commenters who asked for better
projections (tag them) → coming back with a model I trust → also implemented
salary DB, direct links → donations close.

**Voice rules carry over from REDDIT_DRAFTS_2026-05-20.md:** 1st-person
ABOUT THE MODEL ok, 1st-person STAKE NOT ok, lead with what changed, be
honest about limits.

**Target sub:** r/h1b (primary — that's where the original 129↑ / 71-comment
post lives). Could cross-post to r/USCIS as well (17↑ / 33 comments there
too) with a tweaked intro that references the USCIS thread instead. Same
body otherwise.

---

## Original posts being followed up on

- r/h1b "For everyone on H1B waiting for EB2/EB3: I built a tool to visualize the backlog movement" — 2025-12-01, 129↑, 71 comments
  https://www.reddit.com/r/h1b/comments/1pbpp95/for_everyone_on_h1b_waiting_for_eb2eb3_i_built_a/
- r/USCIS "I visualized 10 years of Visa Bulletin priority dates to see real movement trends" — 2025-12-01, 17↑, 33 comments
  https://www.reddit.com/r/USCIS/comments/1pbpki2/i_visualized_10_years_of_visa_bulletin_priority/

## Commenters asking for better predictions / projections (to tag)

Substantive, actionable feedback (best candidates to tag):

| Handle | Sub | Score | Ask |
|---|---|---:|---|
| u/Most_Bother8759 | USCIS | 1↑ | "1. Find out all the measurable variables that affect the delay/approval timeline…" |
| u/blyubird | USCIS | 5↑ | "Estimate should be based on the backlog, visa availability, ROW demand, i140 trends, projected spillovers…" |
| u/arika1447 | USCIS | 2↑ | "use historical USCIS data, historical bulletin movements, predict future based on quarterly data" |
| u/ThisCorgi4904 | h1b | 6↑ | "Would love to see the math behind projections — a delta chart showing days movement per month" |
| u/Few_Criticism_9715 | h1b | 2↑ | "trend isn't going to work for backlogged country like India. Use pending I-140 data in forecast." |
| u/_rogue_1 | h1b | 2↑ | "projection should weight recent velocity heavier than earlier trends as backlog decelerates" |
| u/Former_Inflation3504 | USCIS | 2↑ | "EB1 India = 2050, EB2 = 2036. Ridiculously wrong. Trends are not linear." |
| u/Salt-Progress1354 | h1b | 1↑ | "Awesome tool. How accurate is it?" |
| u/throwaway0845reddit | h1b | 7↑ | Reported a specific bug (EB3 India: PD 09/2013, tool said Dec 2025 estimate when actual was already Dec 2025) |

## Verified direct links (200 OK on prod, 2026-05-20)

- Predictions + accuracy archive: https://visa-bulletin.us/predictions/employment_based/2026-6/
- Employer profiles (each shows H-1B vs PERM count, approval rate, median salary, YoY growth):
  - https://visa-bulletin.us/employer/google-llc/
  - https://visa-bulletin.us/employer/meta-platforms-inc/
  - https://visa-bulletin.us/employer/amazoncom-services-llc/
  - https://visa-bulletin.us/employer/microsoft-corporation/
  - https://visa-bulletin.us/employer/accenture-llp/
  - https://visa-bulletin.us/employer/tata-consultancy-services-limited/
- Employer directory + rankings: https://visa-bulletin.us/employers/  ·  https://visa-bulletin.us/employers/rankings/
- Per-state salary pages: https://visa-bulletin.us/salaries/by-state/CA/  ·  /WA/
- Salary search + job-title directory: https://visa-bulletin.us/salaries/  ·  https://visa-bulletin.us/job-titles/

## Screenshots (sit alongside this doc)

- `vb_predictions.png` — June 2026 accuracy archive (model prediction vs real cutoff, per category × country)
- `vb_google_employer.png` — Google LLC profile (11,936 filings, 97.7% approval, $130,792 median)
- `vb_salaries.png` — salary-search landing page

Reddit allows up to 20 images in a post; pick 1-2 that best support the prediction-model claim. Predictions screenshot is the strongest. Optional secondary: Google employer profile (proves the salary DB integration; Reddit will understand it instantly).

---

## DRAFT — r/h1b version

**Title:** Update for everyone who asked about better predictions: rebuilt the model + added the H-1B/PERM salary database

**Flair:** Resource

**Body:**

Hi everyone — back with an update on https://visa-bulletin.us/. In December I posted a tool that visualized 10 years of bulletin movement and extrapolated forward in a pretty naive way ([original thread](https://www.reddit.com/r/h1b/comments/1pbpp95/for_everyone_on_h1b_waiting_for_eb2eb3_i_built_a/)). The feedback was direct and useful — several people pointed out the projection logic was too simple to be trusted:

- u/blyubird and u/Most_Bother8759: predictions should look at backlog, visa availability, ROW demand, I-140 trends, projected spillovers — not just past dates
- u/Few_Criticism_9715 and u/_rogue_1: a flat trend doesn't work for India backlog; need to weight recent velocity heavier
- u/arika1447: combine historical USCIS data + quarterly bulletin movement
- u/ThisCorgi4904: show the math — a per-month delta chart of how much movement happened
- u/Former_Inflation3504: when the EB-1 India projection says 2050 and EB-2 says 2036, something is wrong (trends are not linear)
- u/Salt-Progress1354: how accurate is it, actually?

Fair points. I rebuilt the prediction system around them.

**What's new on the prediction side:**

Full methodology write-up: https://visa-bulletin.us/analysis/how-my-prediction-model-works/. Short version:

- There's a public **accuracy archive** that shows model prediction vs real DOS cutoff, every category, every month, for as far back as the data goes. This is the page worth opening first — it's how I keep myself honest. Link: https://visa-bulletin.us/predictions/employment_based/2026-6/ (then "Prediction accuracy archive" to walk through past months).
- For each prediction, the page shows which signals contributed and how much weight each got — so "100% no-change baseline" is a clear flat-line warning.
- Where it's still solid: long-stalled categories with steady recent movement (e.g. India EB-3 / EB-2).
- Where it's still rough: anything near an October cutoff (USCIS demand shocks the model can't see), EB-5 reserved buckets (low volume), and any month where DOS announces a policy change (no way to anticipate).

I grade this against reality every month. If the accuracy archive is wrong for your category, tell me which.

**What else I shipped — DOL salary database (new since the December post):**

I indexed 1.5M DOL H-1B + PERM disclosure records (the certified-wage filings every sponsor has to make). You can search them by company, role, or state:

- Employer profile shows H-1B vs PERM count, approval rate, median salary, YoY growth, top roles, by state. Examples:
  - https://visa-bulletin.us/employer/google-llc/
  - https://visa-bulletin.us/employer/meta-platforms-inc/
  - https://visa-bulletin.us/employer/amazoncom-services-llc/
  - https://visa-bulletin.us/employer/accenture-llp/
  - https://visa-bulletin.us/employer/tata-consultancy-services-limited/
- Top-sponsors leaderboard: https://visa-bulletin.us/employers/rankings/
- Per-state salary pages (useful when an offer says "remote" but you want to see where the filings actually went): https://visa-bulletin.us/salaries/by-state/CA/, https://visa-bulletin.us/salaries/by-state/WA/
- Job-title directory — every role aggregated across employers (median salary, top sponsors, salary distribution): https://visa-bulletin.us/job-titles/
- Full salary search: https://visa-bulletin.us/salaries/

Caveat that bears repeating: this is **base salary only** (what employers swore to pay under penalty of perjury on the LCA). It excludes RSUs / bonuses / sign-on. If you're benchmarking Big Tech, Levels.fyi is closer to total comp; this is the certified floor — the number the employer is legally on the hook for.

The two halves connect: pick a company you're interviewing with → see what they certified for your role + state → compare to what your priority date is likely to do under the prediction model.

If this saves you time: development tools, hosting, and my time will be easier to justify if you support me. https://buymeacoffee.com/vyakunin or [github.com/sponsors/vyakunin](https://github.com/sponsors/vyakunin). Either is appreciated. Either is fine if not.

Feedback: poke around, tell me what's helpful, what's broken, happy to improve anything.

Thanks to everyone who took the time to comment on the December thread — I read all of them. This is the second pass.

---

## r/USCIS variant (intro change only)

For the cross-post to r/USCIS, replace the first paragraph with:

> Hi everyone — back with an update on https://visa-bulletin.us/. In December I posted a visualizer for 10 years of bulletin movement here ([original thread](https://www.reddit.com/r/USCIS/comments/1pbpki2/i_visualized_10_years_of_visa_bulletin_priority/)) — the projection logic was a naive extrapolation, and several of you called that out:

The rest of the body stays the same.

---

## Pre-post checklist (per voice rules + previous draft)

- [ ] All linked URLs return 200 (verified 2026-05-20)
- [ ] No "best" / "most accurate" / "guaranteed" language (clean)
- [ ] No first-person stake claim ("waiting on EB-2 too") (clean)
- [ ] Tagged usernames spelled correctly — re-check by hovering each on Reddit before submit
- [ ] r/h1b subreddit rules permit "Resource" flair + link-out (last checked Dec 2025 — re-verify)
- [ ] Posting window: aim for ~22:00 UTC (afternoon Pacific / morning India) like the original post
- [ ] r/USCIS cross-post: wait 6+ hours after r/h1b primary, swap intro paragraph per above
