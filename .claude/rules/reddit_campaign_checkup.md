# Reddit Promo Campaign Checkup

How to "check in on the Reddit posts" for the visa-bulletin.us promo campaign. The
campaign posts from the Reddit account **CivilCandidate1349** via the `reddit_post`
MCP / `submit_reddit_via_browser.py`, scheduled through launchd. Drafts + the
scheduled YAMLs live in the PRIVATE repo
`~/cursor_projects/visa_bulletin_platform/marketing/{drafts,scheduled}/` (moved
out of the public repo 2026-06-01 — marketing is private). The launchd
run-scripts (`agent_infra/scripts/_run_reddit_*.sh`) read the scheduled YAMLs
from that private path.

Run all four sections every checkup, in order. Report a compact phone-formatted
digest (per `~/.claude/rules/chat_formatting.md`): lead with health, then perf, then
the unreplied-comment drafts, then the next-to-schedule approvals.

## No-go subreddits (do NOT schedule or post)

These subs have removed/banned CivilCandidate1349's promo and explicitly disallow
advertising. Don't draft, schedule, or re-post to them; don't modmail-appeal
(repeat violations escalate to account ban):

- **r/immigration** — post removed + locked; account permanently banned there.
- **r/EB2** — post `1tuwd0k` (2026-06-02) removed by EB2-ModTeam within ~11 min:
  "EB2 does not allow advertising and frequent violators will be banned." No
  account ban yet, but one more promo post would trigger it. The deep links +
  donation block read as an ad here.
- **r/h1b** — earlier promo removed (see §1 written-off list).

When a new sub is being considered, dry-run first and check its rules/AutoMod for
a no-advertising / no-self-promotion clause before scheduling.

## 1. Health (Reddit)

Per recent post: score, upvote ratio, comment count, removed/locked state.

Reddit blocks the public `.json` over `curl` (returns an HTML shell). Read it from the
**logged-in Playwright session** instead (profile `~/.config/mcp-chrome-profile` =
CivilCandidate1349). Navigate to `https://old.reddit.com/` once, then `browser_evaluate`
a `fetch('https://old.reddit.com/comments/<id>.json?limit=200&raw_json=1')`. The
post object gives `score`, `upvote_ratio`, `num_comments`, `locked`,
`removed_by_category`/`banned_by` (removed).

Known post IDs (extend as the campaign grows): USCIS `1togz6h`, immigration `1tq6dy5`
(removed+locked), developersIndia `1tqzncq`, IndianH1Bs `1try18z`. Current submitted
list: `https://old.reddit.com/user/CivilCandidate1349/submitted/` (via Playwright, not curl).

Removed+locked posts (immigration, h1b) are written off — don't modmail-appeal
(escalates ban risk, per `~/.claude/rules/browser.md`).

## 2. Performance (Reddit + GoatCounter)

- **Reddit:** score + ratio + comment engagement (from §1).
- **GoatCounter:** Reddit-attributed referral traffic. Token `~/tokens/goatcounter.token`,
  patterns in `.claude/rules/analytics.md`. Reddit shows up as referrers
  `www.reddit.com`, `com.reddit.frontpage` (mobile app), and `reddit`.
  ```bash
  GC_TOKEN="$(cat ~/tokens/goatcounter.token)"
  curl -sS -H "Authorization: Bearer $GC_TOKEN" \
    "https://vyakunin.goatcounter.com/api/v0/stats/toprefs?start=<YYYY-MM-DD>&end=<YYYY-MM-DD>&limit=15"
  ```
  GC strips query strings (commit 641f495), so per-post `utm_content` is NOT separable
  in GC — report the Reddit referrer total + trend, compared against Google/Direct for
  context. Reddit is consistently incremental, not a traffic spike — say so.

## 3. Unreplied comments — draft immediately

From each post's `.json` (§1), flag top-level comments NOT authored by
CivilCandidate1349 and NOT AutoModerator that have no reply from CivilCandidate1349.
**Draft a reply for each immediately** and surface it for approval — posting is
Tier 3 (`~/.claude/rules/automation_safety.md`), so draft-only, never auto-send.
On approval, post via `reddit_post` MCP `reddit_reply_to_comment`, then verify in the
outbox per `browser.md` single-click semantics.

Skip / recommend-skip off-topic political rants (not about the tool) — engaging just
opens a politics thread. Note them so the user can override.

## 4. Next posts to schedule — show drafts for approval

Compare `scheduled/*.yaml` (future `scheduled_time`) against actual launchd jobs:
```bash
launchctl list | grep -i reddit          # jobs that will actually fire
ls ~/Library/LaunchAgents/ | grep -i reddit
```
**A YAML existing does NOT mean it's scheduled** — past campaign posts shipped with
no launchd plist (the schedule step got skipped). For each upcoming YAML with no job,
flag it as "drafted but NOT scheduled — won't fire."

Show the drafts (compact summary: sub, date, lead/angle; full body on request) for
**approval**. Scheduling a public post is Tier 3 — never auto-schedule unprompted.

Only after approval, schedule each via the campaign's launchd pattern (NOT
`schedule_reddit_post.py`, which is the unused PRAW path — this account posts via the
browser): create `agent_infra/scripts/_run_reddit_<name>_<YYYY-MM-DD>.sh` (model it on
an existing `_run_reddit_*.sh` — it kills stale playwright, then
`uv run submit_reddit_via_browser.py --config <yaml>`, then Telegram-pings success/fail)
plus `~/Library/LaunchAgents/com.user.reddit_<name>_<num>.plist` with a
`StartCalendarInterval`, then `launchctl load` it. **launchd fires in LOCAL Mac time**:
Berlin is UTC+2 in summer (CEST), so a 14:00-UTC slot = Hour 16 in the plist — always
recompute the offset (`date`). Verify with `launchctl list | grep reddit`.
**Flair gotcha:** subs that gate submit on a required post flair (r/EB2, r/USCIS,
r/immigration) fail with `rc=4` ("submit did not redirect") if no flair commits.
As of 2026-06-02 `submit_reddit_via_browser.py` **auto-picks a reasonable flair**
when `flair_text` is unset on a gated sub (topic-match → generic catch-all →
first safe flair; never a personal-status flair like Approved/Denied/I-485) and
Telegram-notifies which it chose. Still prefer setting `flair_text` explicitly in
the YAML for control, and dry-run new (sub+content) combos to enumerate flairs.
The r/EB2 2026-06-02 post (`flair_text: null`) hit this — posted manually with
"Visa Bulletin" flair; the auto-pick fix landed the same session.

## Email-triggered proactive mode (the standing subscriptions)

Reddit emails CivilCandidate1349's notifications to vyakunin@gmail.com from
`noreply@redditmail.com`. As of 2026-06-03 the three campaign-monitoring filters
forward to **`vyakunin_visa_bulletin_platform_bot`** (moved off the core VB bot —
Reddit/F5Bot is marketing, and marketing lives in the platform project). Rules in
`agent_infra/gmail_dispatcher/rules/visa_bulletin_platform.yaml`, managed via the
`email_subscriptions` MCP (run it from the `visa_bulletin_platform` cwd):

- **`reddit-replies`** — `subject:"replied to your"` minus AutoModerator → comment/post
  replies.
- **`reddit-messages`** — `subject:("new message" OR "mentioned you" OR "wants to chat")`
  minus AutoModerator → DMs, modmail (mute/ban/removal notices), username mentions.
- **`f5bot-mentions`** — `from:admin@f5bot.com subject:"F5Bot found something"` → keyword
  hits on Reddit/HN/Lobsters. F5Bot account: f5bot.com, login `vyakunin@gmail.com`, password
  at `~/tokens/f5bot` (mode 600; reset 2026-05-30 — not in LastPass). Keywords are literal
  case-insensitive substrings (no OR; one phrase per alert). **Every enabled keyword carries
  the `no-url=/r/immigration/` flag** — CivilCandidate1349 is permanently banned there, so
  alerts from that sub are useless noise (the free `no-url=/r/<sub>/` flag does the exclusion;
  trailing slash matters so it doesn't catch r/immigrationlaw). When revising keywords to
  match current functionality, cover BOTH product surfaces: prediction (priority date /
  visa bulletin forecast) AND the salary/employer DB (h1b salary, lca wage, certified wage).
  Full strategy + current keyword inventory: `~/cursor_projects/visa_bulletin_platform/marketing/BLIND_THREAD_MONITORING.md`.

When one fires, the dispatcher forwards it and `listen_chat_receiver` auto-spawns a
listener in the **`visa_bulletin_platform`** project (the bot the filters now route
to), not `visa_bulletin`. Note this campaign-checkup playbook still lives in the
`visa_bulletin` rules tree, so the platform-spawned listener won't auto-load it —
relocate or symlink it into `visa_bulletin_platform/.claude/rules/` if the
proactive-handling steps below need to fire reliably there. **That listener should
act proactively, not just ack:** pull
the actual Reddit thread (§1 Playwright fetch of the `/comments/<id>.json` or the
message), then **draft a reply suggestion for approval** (§3) — or, for a modmail
mute/ban/removal, summarize the action + recommend next step (do NOT modmail-appeal a
ban). Verify a reply already isn't there before drafting (per `reddit_post` MCP usage).

## Style gate (every draft, before it fires)

Run every draft body through the style rules and fix violations:
- **No first-person immigration stake** — never "EB-2 ROW myself", "my PD", "same
  boat". Builder/analyst framing only. See `~/.claude/rules/llm_tell_avoidance.md` +
  memory `feedback_marketing_no_first_person_lie`. (A live post shipped with
  "(EB-2 ROW myself)" on 2026-05-30 — fixed after the fact.)
- **No LLM tells** — drop performed-honesty labels ("Honest about limits", "with no
  apologies"), defensive meta ("presented as findings rather than a pitch"), and the
  banned pre-fact framing in `llm_tell_avoidance.md`.
- **PERM framing** — describe sponsor leaderboards by **H-1B volume**, never
  "PERM activity / PERM-as-GC-signal". See `.claude/rules/perm_messaging.md`.
- **Donation block** ("Buy me a coffee" / Sponsors) in the first comment matches the
  "asking for money" spam trigger some subs cite (r/immigration removal). On
  high-risk subs, flag it for the user rather than assume it's safe.

## Draft style — corrections log (update on every user edit)

When Vladimir corrects a draft, fold the lesson in here so the next draft starts closer.
Standing rules learned from his edits:

- **Replies/comments: short. One small paragraph by default.** He repeatedly cuts
  multi-point structure ("too much repetitive", "I don't like these blocks",
  "go much shorter, one small paragraph"). A comment answering one question = one tight
  paragraph, not a numbered pitch. Reserve the structured multi-section format for
  top-level *posts*, not comment replies.
- **Honesty over overpromising on prediction accuracy.** When a category is genuinely
  hard to predict (EB-3 Rest of World, anything demand/policy-driven), say so plainly:
  "I'm not aware of a reliable prediction for X — tried hard to build one from open data,
  it's almost entirely unpredictable." Then point to the **historical trend** (what the
  cutoff actually did) rather than implying the model forecasts it well. Don't sell a
  forecast the model can't deliver.
- **Drop canned benefit blocks.** No "when it's useful in a career conversation: •…•…"
  lists. One plain line instead ("you can check your job title or an employer to see how
  they've been doing recently").
- **The model is new — ~3 real live predictions so far.** Don't overstate the accuracy
  archive or imply a long track record. Frame as new, "appreciate any feedback".
- **No first-person immigration stake** (see Style gate above) — builder/analyst voice only.
- **Key links go in the POST BODY, not only the first comment.** The CivilCandidate1349
  account has low site/subreddit karma, so its first comment is unreliable — it gets
  AutoMod-filtered or can't be posted at all in stricter subs, leaving the body's "links in
  the first comment" pointer dead. Put the 1–2 *key* deep links inline in the body (use
  clean URLs without UTM — GC strips query strings anyway per `analytics.md`, so UTM adds
  spam signal for zero analytics gain). **The donation block also goes at the BOTTOM of the
  body** (Vladimir's call 2026-05-31) — same low-karma reasoning: an unreliable first
  comment that never posts is worse than the "asking for money" spam-signal risk. Keep only
  secondary/extra deep links in the first comment as a bonus-if-it-posts. Cap body deep
  links low (≤2, excluding the 2 donation links) to limit the self-promo AutoMod hit.
  **Exception: subs with a documented
  AutoMod-removal history** (e.g. r/greencard, whose v3.1 pattern mandates zero deep links
  in body) get only the bare `visa-bulletin.us` domain in the body, not deep links — flag
  the tension to the user rather than overriding the anti-AutoMod design.

## Origin
2026-05-30 — user asked for a documented checkup after a live r/IndianH1Bs post shipped
with a fabricated "EB-2 ROW myself" stake and the next 4 posts turned out to be drafted
but never scheduled. Draft-style corrections log added same day after he asked for a rule
that captures his edits.
