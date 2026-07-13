---
name: daily_checkup
description: visa_bulletin-only morning checkup — run the project's daily_checkup MCP, compose a focused digest, deliver on @vyakunin_visa_bulletin_bot. Project-scoped twin of the cross-project Kombi digest.
---

Project-scoped variant of `/daily_checkup` for visa_bulletin, shadowing the
generic `~/.claude/skills/daily_checkup/SKILL.md` with the project's own
investigation playbook + traffic KPI. As of 2026-06-03 the daily checkup is
per-project: a 7am launchd job (`agent_infra/daily_checkup/run_daily.py`) spawns
one `claude -p /daily_checkup` per project (Opus) in its own cwd, delivering to
its own bot. There is no cross-project Kombi roll-up anymore. This skill runs in
two modes:
- **Scheduled** (driver injects `/daily_checkup --scheduled` into the Redis stream;
  the visa_bulletin relay session runs this skill): gather → compose → reply.
- **Interactive**: user types `/daily_checkup` on @vyakunin_visa_bulletin_bot.

visa_bulletin always sends (never silent — never `[[SILENT]]`); the traffic KPI line
is the daily signal the user opens the chat for.

**Delivery — relay mode (see generic skill "Delivery mode").** This runs inside the
visa_bulletin **relay session**: the relay delivers your reply, so **emit the digest
as your reply text** (`🤖 `-prefixed) — do NOT curl the Bot API in relay mode (Step 4's
curl is the legacy `--headless` fallback only).
**Reply = the digest only.** First char must be `🤖 ` (the traffic-KPI line); never
preface it with plumbing narration ("Composing the digest", "Relay mode — I emit it as
my reply", "the relay delivers to the <X> bot", naming the bot/chat) — that internal
kitchen leaks into the chat. Reason about delivery silently; output only the digest.

The gather side is the same `daily_checkup_server.py` under
`~/cursor_projects/visa_bulletin/mcp/`. If a fresh enough reports JSON (≤30 min
old) exists in `agent_infra/daily_checkup/logs/`, reuse it; otherwise run fresh.

## Steps

### Step 1 — gather (reuse-or-rerun)

```bash
NEWEST=$(ls -1t ~/cursor_projects/agent_infra/daily_checkup/logs/reports_*.json 2>/dev/null | head -1)
AGE_MIN=$(( ( $(date +%s) - $(stat -f%m "$NEWEST" 2>/dev/null || stat -c%Y "$NEWEST") ) / 60 ))
if [ -z "$NEWEST" ] || [ "$AGE_MIN" -gt 30 ]; then
  cd ~/cursor_projects/visa_bulletin/mcp
  REPORT_JSON=$(uv run python -c '
import asyncio, json
from daily_checkup_server import daily_checkup
print(asyncio.run(daily_checkup()))
')
else
  REPORT_JSON=$(python3 -c "
import json
with open('$NEWEST') as f:
    r = json.load(f)
vb = next(e for e in r if e['project'] == 'visa_bulletin')
print(json.dumps(vb))
")
fi
```

Capture the `CheckupReport` (status / summary / sections / errors / generated_at).

### Step 2 — investigate before composing

The MCP returns RAW signals. Do not just paste them — **answer each red/yellow signal with the root cause + a recommended action**. Common investigations:

- **Disk pressure on homeserver** (DISK_RED_PCT=85, YELLOW=70): nearly always Docker images + build cache. SSH in and run `docker system df` to confirm; if `RECLAIMABLE > 10 GB`, recommend `docker system prune -af --volumes` and quote the reclaim figure. Don't recommend deleting /opt/stack data without confirming what owns it.
- **Staging containers exited**: usually intentional (manual experiment, dual-stack burn-in still in progress). Check `Exited (0) <N> days ago` — exit 0 means clean shutdown. Mention as a one-liner ("staging stack idle since X; restart with `cd /opt/stack/visa_bulletin_staging && docker compose up -d` if needed").
- **5xx spikes**: pull recent error lines from `docker logs vb_web --since 30m | grep -i error` before flagging.
- **Slow tail (>10s requests)**: cross-reference the path against the per-property "Performance" data. If predictions backtest is the offender, that's expected today (heavy Plotly render); flag only if it grows beyond 5–10 hits.
- **Rate-limited (nginx 429)**: ~6k+/day is normal — that's the bot subnet limiter doing its job. Surface only if `5xx > 0.5%` of total OR human-request 429s appear (filter UA for non-bot).
- **/salaries/ 4xx flood**: ~2k/day of 429 to /salaries/ is bingbot getting throttled — not a bug. Confirm with `docker logs vb_nginx --since 24h | awk '$7 ~ /^\\/salaries\\/?$/ && $9 ~ /^4/'`.
- **Traffic deltas**: positive MoM is the goal — celebrate briefly. Negative MoM ≥ 30% → 🟡, ≥ 60% → 🔴; investigate the surface-by-surface breakdown (nginx/GC). Ranking/visibility (GSC) analysis is NOT this digest's job — it lives in the visa_bulletin_platform digest; don't pull GSC or render a `gsc:` line here.

### Step 2.5 — unified ticket block (visa_bulletin)

Query the Notion follow-ups data source `d0ad4f4b-ed1c-4c69-9fa9-0202a2b0d4d2`
(`mcp__notion__API-query-data-source`) filtered to `Project=visa_bulletin`,
`Status not in (Done, Won't Do)`, sort `Due` asc. Bucket by `Due` vs today (`date
+%F`) + the `important` Subtag, same as every channel:
🔴 past due (`Due < today`) · 🟡 due today · ⭐ important (Subtag has `important`,
not already urgent) · 📅 coming week (`today < Due <= today+7`). Items `Due >
today+7` or no Due collapse to a footer line. Render this block at the top of the
digest (after the headline, before the project findings).
**Filter gotcha:** `Status`/`Project` are `select`-typed — use `{"select":{...}}`,
not `{"status":{...}}` (per `notion_followups.md`).

**ALWAYS pass `filter_properties` — the bucketed list only needs 4 fields.**
Without it the query returns full page objects (~5.5k chars each; Notes' rich_text
annotations alone are ~2.6k/ticket) — 14 tickets ≈ 19k tokens of context for a
list that renders only Title/Status/Due/Subtag. With it, ~4x smaller. Pass the
property *value IDs* exactly as they appear in the schema (percent-encoded —
verified accepted by the MCP 2026-06-13):
```
filter_properties: ["title", "er%40O", "e%7BlA", "Ev%3D%5D"]
                     Title    Status    Due       Subtag
```
**Notes on demand only.** Notes (`skQK`) is the bloat AND is rendered only for the
0–2 urgent (🔴 past-due / 🟡 due-today) tickets. Do NOT add it to
`filter_properties`. Instead, for each urgent ticket, fetch its Notes alone via
`mcp__notion__API-retrieve-a-page-property(page_id=<id>, property_id="skQK")`. A
quiet day (no urgent tickets) then loads zero Notes.

### Step 3 — compose the digest

Telegram-mobile format. One screen = one user-readable summary. Style:

- First line: `🤖 visa_bulletin checkup — <YYYY-MM-DD> <HH:MM> Berlin`
- One-sentence headline: `<emoji> <status verdict>` (🟢 all clear / 🟡 needs attention / 🔴 act now). State the most important finding right after.
- Then the unified ticket block from Step 2.5 (only the non-empty buckets).
- Traffic block (the user's #1 KPI), cycle-aware per `[[feedback_traffic_analysis_visa_bulletin]]`:
  - Headline line: `Traffic: 7d <N> views (<+/-N%> MoM cycle, <+/-N%> WoW)`.
  - Then a per-surface breakdown — **one surface per line, each row showing 7d views, share-of-total %, distinct page count, MoM%, and WoW%** (user request 2026-06-17: wants the full-coverage section-share table in every digest, with MoM/WoW). Data is in the MCP's `_build_surface_deltas` rows: `this_week` (absolute), `share_pct` (% of 7d total), `pages` (distinct paths in the bucket — the long-tail size), `delta_pct` (MoM vs `cycle_ago`), `wow_pct` (vs `prev_week`). Rows are already sorted by `this_week` desc — render in that order. Annotate the profile surfaces (`employer_profile`, `job_title_profile`) with `← tail` since their share is spread over hundreds of pages. Column header, terse, ≤50 chars/line, no wide tables:
  - 🚨 **RENDER EVERY SURFACE ROW THE MCP RETURNS — DO NOT SHORTEN.** This block keeps getting trimmed to a handful of rows; that is a recurring defect, not a formatting choice (user, 2026-06-29). The rule:
    - Emit **one line per surface for ALL rows** in `gc.surfaces` (and the matching `surface_breakdown`/`surface_latency`), in `this_week` desc order. No "top N", no "…and 4 others", no dropping the small/zero-traffic surfaces.
    - **Never cut surface rows to fit the ~3000-char cap. SPLIT into a 2nd `🤖 `-prefixed send instead** — the per-surface block is the daily KPI payload, so it has priority over single-message length. Truncating rows to stay in one message is the exact failure to avoid.
    - **`other` is a row too** — render it whenever `this_week > 0`. A large/growing `other` means a live URL surface has no `SURFACE_PATTERN` yet → flag it (`⚠️ other <N> — unclassified surface, add a bucket`) so it gets a taxonomy entry rather than hiding.
    - The taxonomy now includes the recently-launched pSEO families — `priority_date`, `occupation_salary`, `h1b_sponsors`, `spanish` (added 2026-06-29). They will appear as their own rows; render them like any other surface (they were previously swallowed by `other`).
    ```
    7d / share / pages / MoM / WoW:
    dashboard  6.0k  57%  7p   −27%/+33%
    fam-spons  2.0k  19%  7p   +7%/+17%
    employer   773   7%  659p  −11%/−15% ← tail
    job-title  471   5%  420p  −44%/−18% ← tail
    salaries   425   4%  3p    +8%/−15%
    blog       320   3%  7p    −59%/+30%
    predict    220   2%  77p   +159%/−4%
    ```
  - This is the SAME full-coverage data `scripts/gc_section_shares.py` prints (export CSV, 100% coverage). Round views (1.2k / 773) + percentages to whole numbers. Show `n/a` for share/pages/MoM/WoW when null — that means the MCP fell back to the top-100 `/stats/hits` path (export unavailable); flag it explicitly (`⚠️ top-100 only — long tail not counted this run`) rather than presenting truncated shares as real.
  - **NO GSC / SEO lines in this digest — do NOT render any `gsc:` line, not even `gsc: n/a`.** GSC/SEO reporting was removed from the visa_bulletin MCP on 2026-06-26 and moved to the **visa_bulletin_platform** digest (marketing/SEO is owned by the platform overlay, same split as F5Bot/Reddit-watch — see `daily_checkup.md`). The MCP returns no GSC section here, so there is nothing to render and a `gsc: n/a` line falsely reads as a gather-gap in a digest GSC was never in scope for. Clicks/impressions/position live in the platform digest. (If GSC is ever deliberately re-scoped back into THIS channel, that's a code change to the MCP + this skill — until then, no gsc line.)
  - **GA4 engagement block (long-click proxy; user request 2026-07-04).** The MCP returns a "GA4 engagement — organic landings" section: this-7d vs prior-7d sessions / engaged % / engaged-time-per-session for site-organic + `/job-title/*` + `/employer/*` + `/salaries`. Render it every day right after the surface breakdown, raw numbers both windows (never percentages alone). Note the engaged-time is **whole-visit** active engagement time (session-scoped, attributed to the organic landing surface — keeps counting as the user browses other pages), not time on a single page; label it `engaged/visit` so it's not misread as per-page. It flags yellow itself on a ≥10pt WoW engagement drop with N≥50 — surface that flag as a 🟡 finding. Watch list = the profile surfaces (weakest engagement AND the impression-losing ones, 2026-07 diagnosis). If the section is missing, say `ga4: n/a (gather errored)` — don't silently drop the block.
- Each 🟡/🔴 finding gets its own block — 3 lines max:
  - Line 1: signal
  - Line 2: root cause (from Step 2 investigation)
  - Line 3: recommended action
- 🟢 / footer items: collapse into a single trailing line.
- Per-property block convention per `[[feedback_vb_per_property_detail]]`: when surfacing a "Top properties" detail, render as URLs / Popularity / Performance / Notable / Action — not a one-liner.
- Telegram replies: NO wide tables per `[[feedback_telegram_formatting]]` — bullets only.
- Cap ~3000 chars; split into 2 sends if needed.
- Prefix every send with `🤖 ` (load-bearing — the receiver classifier uses it).

### Step 4 — deliver

Always reply on @vyakunin_visa_bulletin_bot — not Kombi. The slash command came from this bot; the answer goes back to this bot.

```bash
TOKEN=$(cat ~/tokens/tg_bot_visa_bulletin)
curl -sS "https://api.telegram.org/bot${TOKEN}/sendMessage" \
  -d "chat_id=132118323" \
  --data-urlencode "text=<the composed digest>"
```

### Step 5 — Notion follow-ups (only for new 🟡/🔴 items)

Per `~/cursor_projects/personal_projects/.claude/skills/daily_checkup/SKILL.md` §"Followup tracker" — same data source (`d0ad4f4b-ed1c-4c69-9fa9-0202a2b0d4d2`), same de-dup rules. Tag `Project = visa_bulletin`. Only create when the item needs deferred action; if the user can act on it from the chat right now, skip Notion and let the conversation handle it.

### Step 6 — do NOT hand off to listen_chat

Whether scheduled (standalone `claude -p`) or interactive (inside a `/listen_chat`
loop), do NOT spawn a new listener. Scheduled: send + exit. Interactive: send +
return (the caller loops back to `/wait_for_message`). The receiver auto-spawns a
listener the moment the user replies to the bot.

## Anti-patterns

- ❌ Do not duplicate the cross-project digest. This skill covers ONLY visa_bulletin.
- ❌ Do not reply on Kombi — always on @vyakunin_visa_bulletin_bot.
- ❌ Do not paste raw MCP signals without investigation. The whole point of running on the project's bot is that the agent's cwd is the project repo — use it (SSH into homeserver, check nginx logs, query the prod DB).
- ❌ Do not surface "all clear" sections verbatim. Collapse to a footer line.
- ❌ Do not skip the traffic line even when nothing else is interesting — it's the daily KPI the user opens the chat to see.

## Why this skill is separate from the cross-project version

The user explicitly asked (2026-05-24) for `/daily_checkup` to work on the visa_bulletin bot too. Same underlying MCP, narrower scope, different delivery channel. Putting it in the project repo means it loads automatically whenever the visa_bulletin listener spawns — no central registry needed.
