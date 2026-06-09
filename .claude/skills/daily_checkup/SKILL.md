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
- **Scheduled** (`$DAILY_CHECKUP_SCHEDULED=1`, driver-spawned): gather → compose →
  send to @vyakunin_visa_bulletin_bot → exit.
- **Interactive**: user types `/daily_checkup` on @vyakunin_visa_bulletin_bot.

visa_bulletin always sends (never silent) — the traffic KPI line is the daily
signal the user opens the chat for.

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
- **Traffic deltas**: positive MoM is the goal — celebrate briefly. Negative MoM ≥ 30% → 🟡, ≥ 60% → 🔴; investigate the surface-by-surface breakdown and check GSC for ranking/visibility drops (mcp__gsc__gsc_query_search_analytics).

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

### Step 3 — compose the digest

Telegram-mobile format. One screen = one user-readable summary. Style:

- First line: `🤖 visa_bulletin checkup — <YYYY-MM-DD> <HH:MM> Berlin`
- One-sentence headline: `<emoji> <status verdict>` (🟢 all clear / 🟡 needs attention / 🔴 act now). State the most important finding right after.
- Then the unified ticket block from Step 2.5 (only the non-empty buckets).
- Traffic block (the user's #1 KPI), cycle-aware per `[[feedback_traffic_analysis_visa_bulletin]]`:
  - Headline line: `Traffic: 7d <N> views (<+/-N%> MoM cycle, <+/-N%> WoW)`.
  - Then a per-surface breakdown — **one surface (property) per line, each row showing absolute 7d views, MoM%, and WoW%** (user request 2026-06-04). Data is in the MCP's `_build_surface_deltas` rows: `this_week` (absolute), `delta_pct` (MoM vs `cycle_ago`), `wow_pct` (vs `prev_week`). Use a column header so rows stay terse + phone-readable (≤50 chars/line, no wide tables). Example:
    ```
    7d views / MoM / WoW:
    employer  1.2k / +306% / +12%
    job-title  980 / +428% / +8%
    salaries  1.5k / +268% / −3%
    dashboard 2.1k / −31% / −5%
    ```
  - Show `n/a` for WoW when `wow_pct` is null (top-100 fallback path with no prev_7d). Round views (1.2k) + percentages to whole numbers.
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
- ❌ Do not paste raw MCP signals without investigation. The whole point of running on the project's bot is that the agent's cwd is the project repo — use it (SSH into homeserver, check nginx logs, query GSC).
- ❌ Do not surface "all clear" sections verbatim. Collapse to a footer line.
- ❌ Do not skip the traffic line even when nothing else is interesting — it's the daily KPI the user opens the chat to see.

## Why this skill is separate from the cross-project version

The user explicitly asked (2026-05-24) for `/daily_checkup` to work on the visa_bulletin bot too. Same underlying MCP, narrower scope, different delivery channel. Putting it in the project repo means it loads automatically whenever the visa_bulletin listener spawns — no central registry needed.
