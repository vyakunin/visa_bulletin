# Critical Development Rules

Django/PostgreSQL/Bazel application parsing visa bulletin data. Python 3.11+. **Production runs on a self-hosted server behind Cloudflare Tunnel** (migrated from AWS Lightsail on 2026-05-08; see `.claude/rules/deployment.md`). Concrete hosting topology — hosts, hardware, IPs, keys — lives in the **private ops repo** (`visa_bulletin_platform/hosting/`), not in this public repository.

General rules (coding style, git, testing, logging, etc.) are in `~/.claude/rules/`. See `rules_management.md` for the shared rules structure and new-project setup.

---

## Rule: Always Investigate Production Warnings

**NEVER ignore warnings in production deployments or operations.**

- Stop and investigate immediately: check logs, status, and configuration
- Document the issue and resolution; fix or document why it's safe to ignore

**Examples:** SSL/Certificate issues, service failures or restarts, database locks, memory/disk warnings.

---

## Rule: Auto-Commit + Push on Meaningful Changes

**Default to committing AND pushing at the end of each completed, meaningful change — no need to be asked** (aligned with the global standing policy in `~/.claude/rules/git.md`, 2026-06-03; this reverses the prior "only commit when explicitly asked" rule, 2026-06-17 per user).

**What counts as "meaningful + complete":** a feature/fix/refactor/doc-or-rule update finished to a coherent, building, test-passing state — the point you'd report it as done. One logical change = one focused, atomic commit. NOT mid-edit WIP, half-applied refactors, or broken intermediate states. Don't commit after every file save; commit at the natural "this is done" boundary.

**Mandatory safeguards (auto-commit is NOT blind `git add -A`):**
1. **Build/tests green first** — `bazel build //...` + `bazel test //tests:all` clean for code changes (per `clean_baseline.md`). The pre-commit hook is a backstop, not the only check.
2. **Never auto-stage secrets / large blobs / scratch** — scan for `.env`, `*token*`, credentials, keys, >10 MB data dumps, `.playwright-mcp/`, `__pycache__`, `.DS_Store`. Prefer targeted `git add <paths>`; only `git add -A` after verifying nothing sensitive/large/scratch is swept in.
3. **visa_bulletin is a solo repo on `main`** → auto-commit to `main` is fine. Force-push to `main` always re-confirms (Tier 3).
4. **Never `--no-verify`** (see rule below).

**Still PAUSE (don't auto-commit) when:** the tree has unrelated changes you don't understand; a pre-commit hook fails (surface + fix, never bypass); secrets are unavoidably part of the change; or the user said "don't commit yet" / "hold off" / "local only" (honor until released).

**Deploy ≠ commit, but both happen:** deploying still goes through the documented deploy flow (`deployment.md`); the commit captures the source-of-truth in the same task.

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

`docker pull` and `docker logs` are always safe. `docker-compose up -d` is **not**. See `.claude/rules/deployment.md` for the full pre-flight checklist.

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

Use the SSH alias `homeserver` for the production server — its host, user, and key are configured in your private `~/.ssh/config` (concrete values live in the private ops repo, not this public repository). See `deployment.md` for the deploy flow.

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

**To opt in:** implement a stdio MCP server exposing a `daily_checkup` tool per the contract at `~/.claude/rules/daily_checkup.md`, then add the project to `~/cursor_projects/personal_projects/daily_checkup/registry.yaml`. **Not yet implemented.**

**Likely signals to surface from this project:**

- Public site availability + last-hour 5xx rate from cloudflared / nginx (`vb_nginx` access log)
- Hourly bulletin-refresh cron status: did it run, did it parse, any errors? (`/opt/stack/visa_bulletin/logs/cron/bulletin_refresh.log`)
- Production server headroom — `df -h /`, `free -h` (small SSD — watch disk pressure)
- Postgres DB size growth + any vacuum / replication warnings
- Cloudflare tunnel connector state (`vb_cloudflared` — QUIC connections healthy?)
