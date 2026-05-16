# Critical Development Rules

Django/PostgreSQL/Bazel application parsing visa bulletin data. Python 3.11+. **Production runs on a self-hosted Dell Wyse 5070 ("homeserver") behind Cloudflare Tunnel** (migrated from AWS Lightsail on 2026-05-08; see `.cursor/rules/deployment.mdc` and `homeserver.mdc` for topology). Lightsail kept reachable on `44.209.204.255` for rollback during burn-in.

General rules (coding style, git, testing, logging, etc.) are symlinked from `~/.cursor/shared_rules/`. See `rules_management.mdc` for the shared rules structure and new-project setup.

---

## Rule: Always Investigate Production Warnings

**NEVER ignore warnings in production deployments or operations.**

- Stop and investigate immediately: check logs, status, and configuration
- Document the issue and resolution; fix or document why it's safe to ignore

**Examples:** SSL/Certificate issues, service failures or restarts, database locks, memory/disk warnings.

---

## Rule: Only Commit When Explicitly Asked

**🚫 NEVER auto-commit changes. ONLY commit when user EXPLICITLY requests it. 🚫**

**User must use words like:** "commit", "commit this", "push", "push to git", "save to git"

**❌ DO NOT COMMIT when user says:** "create a file", "add analytics", "looks good", "deploy", or when finishing any task/fix.

**✅ What to do instead:** Create/modify files → show user what changed → WAIT for explicit commit request.

---

## Rule: Never Use git commit --no-verify

**🚫 NEVER use `git commit --no-verify` or bypass the pre-commit hook. 🚫**

Pre-commit runs ruff (lint) and all tests. If the hook fails, fix the failures and commit again. Never skip.

```bash
# ✅ REQUIRED
git commit -m "message"

# ❌ FORBIDDEN
git commit --no-verify -m "message"
git commit -n -m "message"
```

**When commit times out:** Run `bazel test //tests:...` first, then commit (hook reuses cache). Do NOT use `--no-verify`.

---

## Rule: Ask Before Installing Tools or Using Workarounds

**When a tool is not installed, ALWAYS ask the user before installing or using a workaround.**

Present options clearly with tradeoffs; never automatically `brew install` or `apt install`.

---

## Rule: Never Run Long-Running Processes in Foreground

**ALWAYS run servers and long-running processes in background mode.**

```bash
# ✅ ALWAYS
nohup command > /tmp/output.log 2>&1 &

# ❌ NEVER
command  # blocking foreground
```

---

## Rule: NEVER Use `| head` or `| tail -N` in Command Pipes

**🚨 CRITICAL: THIS IS THE #1 MISTAKE AI ASSISTANTS MAKE 🚨**

**❌ FORBIDDEN (will block monitoring):**
```bash
bazel run //:script 2>&1 | head -50
bazel run //:script 2>&1 | grep "pattern" | head -20
command | tail -N   # ANY use of tail -N in pipes
```

**✅ ALWAYS DO THIS INSTEAD:**
```bash
bazel run //:script > /tmp/script.log 2>&1 &
PID=$!
echo "Started with PID: $PID"
tail -f /tmp/script.log                   # Real-time monitoring
tail -50 /tmp/script.log                  # View last 50 lines (on log FILE, not in pipe)
```

**Why:** `| head`/`| tail -N` hides progress, causes SIGPIPE errors, prevents detecting stuck scripts.

**3-step pattern:**
1. Run in background: `command > /tmp/log.log 2>&1 &`
2. Monitor: `tail -f /tmp/log.log`
3. View last N: `tail -N /tmp/log.log` (on the log file, NOT in a pipe)

---

## Rule: Audit Docker Topology Before Touching Containers on Prod

**NEVER run `docker-compose up/down/stop`, `docker stop`, or `docker rm` on production without first running:**

```bash
docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -tlnp | grep 8000
```

Understand which container is *actually serving traffic* before touching anything. Legacy containers may depend on Docker DNS (`redis` hostname). Stopping ANY container on the shared network can break DNS for the serving container.

`docker pull` and `docker logs` are always safe. `docker-compose up -d` is **not**. See `.cursor/rules/deployment.mdc` for the full pre-flight checklist.

---

## Rule: Use SSH Config Aliases for Remote Servers

**ALWAYS use SSH config aliases instead of raw IP addresses.**

```bash
# ✅ GOOD
ssh production
ssh production "systemctl status app"

# ❌ BAD
ssh -i ~/.ssh/key.pem user@192.168.1.100
```

Project aliases: `homeserver.local` (current production, Wyse 5070, key `~/.ssh/homeserver_ed25519`, user `vyakunin`); `prod_2Gb_vm`/`staging_2Gb_vm`/`backup_0_5Gb_vm` (old Lightsail, kept for rollback during burn-in only). See `deployment.mdc` for details.

---

## Django Best Practices

### Database Migrations

- Always review migrations before committing
- Never bypass migrations (`--fake` or `--skip-checks` in production)
- Test migrations on development database first
- Check for reversibility when possible

---

## Daily Checkup (opt-in)

This project can plug into the morning digest pipeline run from `~/cursor_projects/personal_projects/daily_checkup/` (Claude Code skill: `/daily_checkup`).

**To opt in:** implement a stdio MCP server exposing a `daily_checkup` tool per the contract at `~/.cursor/shared_rules/daily_checkup.mdc`, then add the project to `~/cursor_projects/personal_projects/daily_checkup/registry.yaml`. **Not yet implemented.**

**Likely signals to surface from this project:**

- Public site availability + last-hour 5xx rate from cloudflared / nginx (`vb_nginx` access log)
- Hourly bulletin-refresh cron status: did it run, did it parse, any errors? (`/opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log`)
- Homeserver headroom — `df -h /`, `free -h` (Wyse 5070 is 64 GB disk / 8 GB RAM)
- Postgres DB size growth + any vacuum / replication warnings
- Lightsail rollback path: is `44.209.204.255` still reachable during burn-in?
- Cloudflare tunnel connector state (`vb_cloudflared` — 4 QUIC connections healthy?)
