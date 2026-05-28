---
name: daily_checkup
description: visa_bulletin-only morning checkup — run the project's daily_checkup MCP, compose a focused digest, deliver on @vyakunin_visa_bulletin_bot. Project-scoped twin of the cross-project Kombi digest.
---

Project-scoped variant of `/daily_checkup`. Cross-project digest lives at
`~/cursor_projects/personal_projects/.claude/skills/daily_checkup/SKILL.md`
(delivered via Kombi @vyakunin_agent_bot). This skill is the visa_bulletin
slice only — invoked when the user types `/daily_checkup` on
@vyakunin_visa_bulletin_bot.

The gather side is unchanged: the same `daily_checkup_server.py` under
`~/cursor_projects/visa_bulletin/mcp/` produces the report. The cross-project
orchestrator runs every morning at ~09:20 Berlin and writes
`~/cursor_projects/agent_infra/daily_checkup/logs/reports_<stamp>.json` —
**if a fresh enough report (≤30 min old) exists, reuse it. Otherwise spawn
a fresh visa_bulletin-only run.**

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

### Step 3 — compose the digest

Telegram-mobile format. One screen = one user-readable summary. Style:

- First line: `🤖 visa_bulletin checkup — <YYYY-MM-DD> <HH:MM> Berlin`
- One-sentence headline: `<emoji> <status verdict>` (🟢 all clear / 🟡 needs attention / 🔴 act now). State the most important finding right after.
- One-line traffic mention (the user's #1 KPI): `Traffic: 7d <N> views (<+/-N%> MoM cycle)`. Cycle-aware per `[[feedback_traffic_analysis_visa_bulletin]]`.
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

### Step 6 — hand back to listen_chat

This skill is invoked from inside a running `/listen_chat` loop on the visa_bulletin bot. Do NOT spawn a new listener — just return. The caller (listen_chat Step 4 → "Slash-command dispatch") will loop back to `/wait_for_message`.

## Anti-patterns

- ❌ Do not duplicate the cross-project digest. This skill covers ONLY visa_bulletin.
- ❌ Do not reply on Kombi — always on @vyakunin_visa_bulletin_bot.
- ❌ Do not paste raw MCP signals without investigation. The whole point of running on the project's bot is that the agent's cwd is the project repo — use it (SSH into homeserver, check nginx logs, query GSC).
- ❌ Do not surface "all clear" sections verbatim. Collapse to a footer line.
- ❌ Do not skip the traffic line even when nothing else is interesting — it's the daily KPI the user opens the chat to see.

## Why this skill is separate from the cross-project version

The user explicitly asked (2026-05-24) for `/daily_checkup` to work on the visa_bulletin bot too. Same underlying MCP, narrower scope, different delivery channel. Putting it in the project repo means it loads automatically whenever the visa_bulletin listener spawns — no central registry needed.
