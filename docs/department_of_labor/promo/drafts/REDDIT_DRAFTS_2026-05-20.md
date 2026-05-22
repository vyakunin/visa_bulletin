# Reddit Promotion Drafts — 2026-05-20

**Voice rules (per feedback memory):**
- First-person ABOUT THE MODEL is OK: "I built a model that..." / "I have a tool that..."
- First-person STAKE-IN-GAME is NOT OK: never "same boat — H1B/EB2", "I'm waiting too", etc.
- Lead with data and value. Soft mention of the site. No "check out my site!!!"
- Be honest about limits: what the data is, what it isn't, where the model is weak.

**Posting cadence:** stagger posts across the day (don't blast 3 in 1 hour). Wait 2-3h between subs.

**Pre-flight checklist for each post (user does or asks me to verify):**
- Sub's self-promo rules (most allow "I built X, here's what it does" if value-first)
- Mod-pinned post about tools/resources
- Recent posts: don't dup an active thread on the same topic
- Reddit account karma + age (most subs require positive karma + 30+ days)

---

## Post 1 — r/h1b (~120k members, very active, tolerates useful tools)

**Title:** Free H-1B employer + salary search (1.5M records, DOL data) — what to add?

**Flair (if required):** "Resource" or "Discussion"

**Body:**

I built a search tool over the DOL's public H-1B/PERM disclosure data. You can pull up any employer and see what they filed for, the roles, the wages they certified.

Some numbers from the current data:

- **Top H-1B sponsors (latest reporting batch):** Amazon 302, Meta 208, Google 164, EY 116, Microsoft 109, Tesla 99
- **Highest avg certified wages among the big sponsors:** SkyWest Airlines $245K, Meta $219K, Google $201K, JPMorgan $199K, Macquarie $189K
- Total: 1.5M salary records across 287K employers, going back several fiscal years

It's at visa-bulletin.us — `/employers/` for the directory, `/salaries/` for the search, `/employers/rankings/` for the leaderboard. Free, no signup.

Honest about what it is and isn't:

- ✅ DOL-disclosed wages — what employers swore to pay under penalty of perjury on LCAs/PERMs
- ✅ Real employer names, locations, job titles as filed
- ❌ Not actual offer letters / take-home / bonuses
- ❌ Doesn't include roles that don't require an H-1B or PERM filing

What's missing that you'd actually use? Wage growth per employer over time? Better job-title clustering (so "Software Engineer III" and "SWE III" roll up)? Location heatmaps? Genuinely asking — happy to add what's useful.

---

## Post 2 — r/immigration (~250k members, broad)

**Title:** I built a visa bulletin prediction model — June 2026 predictions + a backtest of past predictions vs reality

**Flair:** "Discussion" or "Resource" (sub-dependent)

**Body:**

I got tired of guessing where my priority date would land next month, so I built a model that fits historical priority-date movement and projects forward each month.

What's on the site (visa-bulletin.us):

- **Predictions for the *next* bulletin** for every EB category × country (EB-1, EB-2, EB-3, EB-4, EB-5) and family-sponsored (F1–F4). June 2026 predictions are up now.
- **Backtest:** model prediction vs what actually came out, month by month. This is the page worth looking at first — it tells you which categories the model is accurate on, and which it consistently misses.
- **"How it works"** explainer — what data goes in, what assumptions, where it breaks.

Where the model is solid: long-stalled categories (e.g. India EB-3 has moved in a narrow band for years and the model picks that up easily).

Where it's a coin flip: anything near a fiscal-year cutoff (USCIS demand spikes the planner can't see), and EB-5 reserved categories (low volume, lumpy movement).

It's public-data only (DOS bulletins, DOL disclosures). Free, no signup, no email. Not selling anything — built it for myself, and putting it out because other people seem to want the same view.

Feedback welcome, especially: which categories you've seen the model miss badly. If you spot a bad prediction in the backtest I want to know about it.

---

## Post 3 — r/EB2 OR r/USCIS OR cross-post variant for India EB heavy audience

(Pick ONE of: r/EB2 if it's active, r/USCIS, or a cross-post to r/h1b with adjusted title)

**Title:** India EB-2 / EB-3 priority date model — June 2026 + a backtest showing where it's been right and wrong

**Body:**

A more India-EB-specific framing of the same model: it tracks the EB-2 and EB-3 India priority dates month by month and projects where they're heading.

What I'm finding from the backtest:

- **EB-3 India** is the most predictable: range of error on the next month's cutoff is consistently small. Model says (link to predictions page for actual call) for June 2026.
- **EB-2 India** is harder — every time DOS does a "retrogression to manage demand" the model has to re-learn the new floor for several months.
- **The big misses** all happen around October (new fiscal year) when USCIS adjusts visa allocations. The model has no way to anticipate that until the first month of the new FY publishes.

Page is at visa-bulletin.us/predictions/employment_based/ — pick India in the country dropdown to see the per-category month-by-month chart. Backtest is on the same page.

Honest framing: it's a statistical model. It's not "insider info" and it can't account for policy changes mid-year. If anyone has caught the model being badly wrong, I want to know — that's the kind of feedback that improves the next version.

---

## Optional Post 4 — r/cscareerquestions (HIGH risk for self-promo flag)

**Note:** This sub is strict on self-promo. Only post if there's a thread asking specifically about H-1B salary data, and link as a tool answer rather than a post. Do NOT submit as a top-level post.

**Reply template (only if a relevant thread exists):**

> If you want the actual filed H-1B + PERM wages by employer, visa-bulletin.us aggregates them from DOL disclosure data. Free, no signup. Useful for negotiating because you can see the exact wages [Employer] certified for [Role] across the last few years.

---

## Posts NOT to make (red-flagged)

- ❌ r/AskHR — wrong audience
- ❌ r/personalfinance — too broad, will be removed
- ❌ Cross-posts to 3+ subs same day — Reddit's spam filter will catch it
- ❌ Anything claiming "best" / "most accurate" / "guaranteed" predictions
- ❌ Anything implying the model has insider information
- ❌ Any first-person stake claim ("I'm in line too", "as a fellow waiter")

## Sequence + timing for tomorrow

Suggested order (so the highest-risk post is last, after lower-risk ones have proven traction):

1. **r/immigration** (morning Pacific = ~16:00 UTC): broadest, lowest self-promo sensitivity
2. **r/h1b** (afternoon Pacific = ~22:00 UTC, evening Eastern, morning India): peak h1b engagement
3. **r/EB2 or India-EB sub** (evening Pacific = ~03:00 UTC next day = morning India): India primary audience
4. **r/cscareerquestions** reply if and only if a relevant thread surfaces — don't initiate

Spacing: 2-3h minimum between posts. Don't post to two subs in the same 30-min window — Reddit's anti-spam will flag.

## Open questions for the user before posting

- What Reddit account should posts go from? (account age + karma must be sufficient for each sub)
- Has the user already posted on visa-bulletin.us in any of these subs in the last ~30 days? (avoid re-promoting same content)
- Comfortable with auto-flair "Resource" / "Tool" on subs where required, or want manual review per post?
