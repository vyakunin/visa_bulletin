# Post-Migration Notebook

> **Created 2026-05-09** as the single source of truth for follow-up tasks after the Lightsail → homeserver migration on 2026-05-08.
>
> **2026-05-20:** All task-shaped items migrated to the central Notion DB (Daily Checkup Followups, filter `Project=visa_bulletin`). This file now holds only **notebook content**: design rationale, recurring playbooks, historical signal log, and the Done log. Open follow-ups live in Notion.
>
> Older planning docs (`HARDENING_PLAN.md`, `INSTANCE_ROTATION.md`, `DEPLOYMENT_ZERO_DOWNTIME.md`, etc.) describe the pre-migration Lightsail world and are **mostly obsolete**. They're kept for git history but should not be treated as active. (A Notion task tracks their cleanup.)

---

## Recurring playbook: daily Reddit-watch via F5Bot

- **Why this lives here, not in Notion:** F5Bot alerts (`admin@f5bot.com`) ping us whenever Reddit threads mention "visa bulletin prediction", "green card priority date", or "priority date movement" — exactly the discussions our app is for. These are not noise; they're community traffic we should engage with where it makes sense. This is a recurring procedure with a signal log, not a discrete task.
- **Cadence:** check daily during the morning checkup. For each new F5Bot email:
  1. **Log the signal** in the "F5Bot signal log" subsection below (date, keyword, subreddit, thread title + URL). Don't let the content disappear into archive without a written record — the user can scan the log weekly to spot patterns or revisit threads they skipped at first.
  2. Open the linked Reddit thread.
  3. Decide: does our site offer useful context? Worth a comment with link?
  4. If yes — comment (or note to do so manually). If no — log only.
  5. After processing (commented or skipped), archive the F5Bot email.
- **Do NOT filter F5Bot blanket-archive.** The daily_checkup skill has the rule.

### F5Bot signal log

Newest at top. Format: `YYYY-MM-DD — keyword — r/sub — "thread title" by user (link) — action taken`.

- 2026-05-14 — *priority date movement* — r/ShareAiPrompts — "June 2026 Visa Bulletin" by jamesidayi — https://www.reddit.com/r/ShareAiPrompts/comments/1tcm2wm/ — logged, not commented yet
- 2026-05-13 — *green card priority date* — r/nri — "Any 2019+ EB2/EB3 Families with H4 kids Planning Their Future in the US?" by FarPrune250 — https://www.reddit.com/r/nri/comments/1tca6sb/ — logged, not commented yet

---

## Done (post-migration session, 2026-05-08 / 09 and onward)

- ✅ DNS cutover: `visa-bulletin.us` + `www` → CF tunnel. Lightsail traffic = 0.
- ✅ Hourly bulletin refresh moved to homeserver cron.
- ✅ Lightsail crons disabled.
- ✅ Lightsail instances stopped (still billing, but freed compute).
- ✅ Dual-environment built: prod stack at `/opt/stack/visa_bulletin/`, staging stack at `/opt/stack/visa_bulletin_staging/`. Each has own DB, redis, web, nginx. Shared `cloudflared` + `vb_public` Docker network for ingress.
- ✅ Bot rate limits + per-bot/per-/16/per-IP tiers, `main_timed` log format with `$request_time`, basic security headers (HSTS, X-Frame, Referrer, Permissions, X-Content-Type) on prod nginx.
- ✅ Staging stack has `Disallow: /` robots.txt + `X-Robots-Tag: noindex, nofollow`.
- ✅ ALLOWED_HOSTS bug from cutover documented as global rule (`~/.cursor/shared_rules/django.mdc`).
- ✅ Rules updated to reflect homeserver topology: `homeserver.mdc`, `deployment.mdc`, `branching.mdc`, `AGENTS.md`, `~/.claude/CLAUDE.md`.
- ✅ Home-automation project scaffolded at `~/cursor_projects/home_automation/` with HANDOFF.md.
- ✅ **Critical bug found & fixed:** CF tunnel ingress was routing real `visa-bulletin.us` traffic to staging stack for ~30 min after dual-env build. Cause: ingress used Compose service-name `nginx` which on the shared `vb_public` external network resolved to the staging container (because Compose only adds the service-name alias on networks declared in the `networks:` block, not on networks attached via `docker network connect`). Fix: switched ingress to container-name aliases (`vb_nginx`, `vb_stg_nginx`). Lesson added to `~/.cursor/shared_rules/homeserver.mdc` "Common Mistakes" section.
- ✅ rclone + Google Drive backups: rclone authorized on Mac AND homeserver (both have `gdrive:` remote), daily cron at 1 AM UTC, one manual test upload verified in Drive. (Notion task tracks first-cron verification.)
- ✅ **Disaster recovery scripts** at `deployment/dr/`: `preflight.sh` (read-only checks, all green), `failover.sh` (start Lightsail + DNS flip, ~3 min), `restore_latest_backup_on_lightsail.sh` (refreshes Lightsail DB from latest GDrive backup, +5 min), `failback.sh` (DNS back + stop Lightsail). RUNBOOK.md documents 3 scenarios. **Tested end-to-end 2026-05-09:** Lightsail boot to "web responds 200" took ~30s (instance was warm); failover→failback round trip took 7 min total without disrupting prod (declined the actual DNS flip during the drill).
- ✅ **Lightsail decommission (2026-05-09):** Snapshot `vb-prod-snapshot-2026-05-09` created (60 GB, available). All 3 instances deleted (`VisaBulletin2GB`, `VisaBulletinStaging`, `visa-bulletin-prod`). All 3 static IPs released. DR scripts updated for snapshot-based recovery. Final monthly cost: ~$1 for the snapshot. AWS IAM user `visa-bulletin-deploy` kept for potential DR.
- ✅ **CF edge X-Robots-Tag mystery resolved:** was NOT a CF setting — symptom of the staging-routing bug (above). After routing fix, prod responses are clean; staging still has X-Robots-Tag (correct, by design).
- ✅ **Legacy-bulletin parser support for 2004 colspan-title format** added in commit `2400477` (2026-05-05). Remaining cron noise is now validation failures (not parse failures) for 10 ancient bulletins missing `Bulletin` DB rows — suppressed in daily checkup, real fix tracked in Notion.

---

## Architecture note: P2 ideas worth keeping for context

These are aspirational and have not yet been opened as Notion tasks (they would be too speculative). Captured here so the design thinking isn't lost. If any matures into a concrete action, open a Notion task and remove from this list.

- **Two-instance HA on homeserver:** currently a single Wyse 5070. If the homeserver dies, the DR path is "Lightsail snapshot → restore → DNS flip" (10-15 min). A second cheap node + LB would shrink RTO. Not justified today.
- **Cold-cache vs warm-cache user experience:** Django local memory cache + Redis + CF edge cache form a 3-tier stack. After deploys, the first 20-30 cold requests are slow. A post-deploy cache-warmer script is a P2 Notion task; pursue if cold-tail becomes a user complaint.
