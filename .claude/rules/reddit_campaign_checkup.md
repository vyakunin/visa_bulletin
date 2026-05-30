# Reddit Promo Campaign Checkup

How to "check in on the Reddit posts" for the visa-bulletin.us promo campaign. The
campaign posts from the Reddit account **CivilCandidate1349** via the `reddit_post`
MCP / `submit_reddit_via_browser.py`, scheduled through launchd. Drafts live in
`docs/department_of_labor/promo/{drafts,scheduled}/`.

Run all four sections every checkup, in order. Report a compact phone-formatted
digest (per `~/.claude/rules/chat_formatting.md`): lead with health, then perf, then
the unreplied-comment drafts, then the next-to-schedule approvals.

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
**Flair gotcha:** if the sub requires a post flair and the YAML's `flair_text` is null,
`submit_reddit_via_browser.py` fails (rc=7, the developersindia failure). Dry-run new
(sub+content) combos to enumerate flair before the scheduled fire.

## Email-triggered proactive mode (the standing subscriptions)

Reddit emails CivilCandidate1349's notifications to vyakunin@gmail.com from
`noreply@redditmail.com`. Two `email_subscriptions` filters forward them to
`vyakunin_visa_bulletin_bot` (managed via the `email_subscriptions` MCP; rules in
`agent_infra/gmail_dispatcher/rules/visa_bulletin.yaml`):

- **`reddit-replies`** — `subject:"replied to your"` minus AutoModerator → comment/post
  replies.
- **`reddit-messages`** — `subject:("new message" OR "mentioned you" OR "wants to chat")`
  minus AutoModerator → DMs, modmail (mute/ban/removal notices), username mentions.

When one fires, the dispatcher forwards it and `listen_chat_receiver` auto-spawns a
listener in this project. **That listener should act proactively, not just ack:** pull
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

## Origin
2026-05-30 — user asked for a documented checkup after a live r/IndianH1Bs post shipped
with a fabricated "EB-2 ROW myself" stake and the next 4 posts turned out to be drafted
but never scheduled.
