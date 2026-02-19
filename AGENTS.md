# Rule Organization

> [!IMPORTANT]
> **BOOTSTRAPPING FOR AI AGENTS**: 
> 1. Read this file for critical rules.
> 2. Index all rules in [.cursor/rules/](file:///Users/vyakunin/cursor_projects/visa_bulletin/.cursor/rules/) (all are `alwaysApply: true`).

**File structure:**
- `AGENTS.md` — Critical rules (must never be violated)
- `.cursor/rules/general_*.mdc` — General portable rules (prefixed `general_` for easy cross-project copy)
- `.cursor/rules/*.mdc` (no prefix) — Project-specific rules (Bazel, Django, deployment, etc.)

All rules are `alwaysApply: true`. Context cost is managed via aggressive compression, not selective loading.

---

# Critical Rules

## Only Commit When Explicitly Asked

**NEVER auto-commit.** Only commit when user says "commit", "push", or "save to git". Creating files, fixing bugs, deploying — none of these imply commit. Create/modify files, show changes, WAIT for explicit commit request.

## Never Use git commit --no-verify

**NEVER bypass the pre-commit hook.** It runs ruff + all tests. If it fails, fix the failures. If it times out, run `bazel test //tests/...` first so the hook reuses cache, then commit. `--no-verify` is forbidden in all cases.

## Never Pipe Through `| head` or `| tail -N`

**The #1 AI assistant mistake.** Never use `| head`, `| tail -N`, or `| grep | head` in command pipes — it blocks monitoring and hides progress.

```bash
# ❌ FORBIDDEN
command 2>&1 | head -50
command 2>&1 | tail -15

# ✅ CORRECT — background + log file
command > /tmp/script.log 2>&1 &
tail -f /tmp/script.log           # monitor
tail -50 /tmp/script.log          # view last N (on file, not pipe)
```

## Never Run Long-Running Processes in Foreground

Background everything: `nohup command > /tmp/out.log 2>&1 &`. AI assistants cannot Ctrl+C. Use `timeout` for checks. Use project scripts that handle background execution.

## Always Investigate Production Warnings

Stop, check logs/status/config, verify if real problem, fix or document why safe to ignore. Never dismiss SSL failures, service restarts, DB errors, memory warnings.

## Ask Before Installing Tools

Never `brew install` or `apt install` without asking. Present options (install vs workaround) and let user choose.

## Use SSH Config Aliases

Always `ssh prod_2Gb_vm`, never raw `ssh -i key user@IP`. Aliases defined in `~/.ssh/config`.

## Branch Strategy: Never Deploy from `main`

Three branches: `main` (dev), `staging` (release candidate), `prod` (frozen production). Deploy from `staging` or `prod`, never from `main`. Never scp files to servers. See `.cursor/rules/branching.mdc` and `docs/BRANCHING_AND_DEPLOYMENT.md`.
