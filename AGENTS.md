# Rule Organization

**Keep non-project-specific general rules portable between projects:**

- **Critical rules** (must never be violated) should be kept in `AGENTS.md`
- **General portable rules** (code style, testing, git, security, etc.) should go in `.cursor/rules/general_*.mdc` files (must be prefixed with `general_`)
- **Project-specific rules** (e.g., Bazel build system, Django patterns, domain logic) should go in `.cursor/rules/*.mdc` files (without `general_` prefix)
- This separation makes it easy to copy general rules to new projects by copying all `general_*.mdc` files

**Current file structure:**
```
AGENTS.md                           - Core critical rules (must never be violated)
.cursor/rules/general_*.mdc         - General portable rules (code style, testing, git, security, etc.)
.cursor/rules/*.mdc                 - Project-specific rules (Bazel, Django, scripts, deployment, etc.)
```

**Naming convention:**
- **`general_*.mdc`** - All general (non-project-specific) rules must be prefixed with `general_`
- **`*.mdc`** (without `general_` prefix) - Project-specific rules for this codebase only
- This makes it easy to identify which rules are portable vs project-specific

**Benefits of this structure:**
- ✅ Uses Cursor's recommended `.cursor/rules/` directory (current standard)
- ✅ Better organization with modular `.mdc` files
- ✅ Supports glob pattern scoping for granular control
- ✅ Easy to copy `AGENTS.md` to new projects
- ✅ Project-specific rules stay organized and maintainable

---

# Critical Development Rules

These are the most important rules that should never be violated.

## Rule: Always Investigate Production Warnings
**NEVER ignore warnings in production deployments or operations.**

**When you see warnings (⚠️) in production:**
- ✅ Stop and investigate immediately
- ✅ Check logs, status, and configuration
- ✅ Verify if the warning indicates a real problem
- ✅ Document the issue and resolution
- ✅ Fix or document why it's safe to ignore

**Examples of production warnings to investigate:**
- SSL/Certificate issues (Certbot failures)
- Service failures or restarts
- Database locks or errors
- Memory/disk warnings
- Configuration validation failures

**Rationale:**
- Production warnings often indicate real issues
- Ignoring warnings can lead to outages
- SSL issues can break the site for users
- Early detection prevents bigger problems

## Rule: Only Commit When Explicitly Asked
**🚫 NEVER auto-commit changes. ONLY commit when user EXPLICITLY requests it. 🚫**

**This is CRITICAL. When in doubt, DO NOT COMMIT.**

**User must use words like:**
- "commit" / "commit this" / "commit these changes"
- "push" / "push to git" / "push to github"
- "save to git" / "add to git"
- Or explicitly say "commit and push"

**❌ DO NOT COMMIT when user says:**
- "create a file" / "add a file" / "make a document"
- "add analytics" / "update design"
- "looks good" / "thanks" / "great"
- "deploy" / "update the site" (deployment is separate from git commit)
- Finishing ANY task
- Fixing ANY bugs
- Making ANY changes

**✅ What to do instead:**
1. Create/modify the files
2. Show the user what changed
3. WAIT for explicit commit request
4. Let user review changes first

**Example of what counts as explicit:**
- User: "commit this" → ✅ Commit
- User: "looks good, commit it" → ✅ Commit
- User: "push the changes" → ✅ Commit and push
- User: "add a README" → ❌ Create file but DON'T commit
- User: "deploy to AWS" → ❌ Deploy but DON'T commit (unless they also say "commit")

**Rationale:**
- User controls git history
- Prevents premature commits
- Allows review before committing
- User may want to make more changes
- Commits are permanent and public

## Rule: Ask Before Installing Tools or Using Workarounds

**When a tool is not installed, ALWAYS ask the user before:**
1. Installing the tool
2. Using a workaround/alternative approach

**DO NOT automatically:**
- Install tools without permission (e.g., `brew install`, `apt install`)
- Use workarounds without explaining the tradeoffs

**Good approach:**
```
❌ Tool 'gh' not found.

Options:
1. Install GitHub CLI: brew install gh (recommended for this feature)
2. Use workaround: curl to GitHub API (less convenient, no auth caching)
3. Check status via web: https://github.com/user/repo/actions

Which would you prefer?
```

**Bad approach:**
```
Installing gh...  # ❌ Don't do this without asking
```

**Rationale:**
- User may prefer manual installation
- User may not want certain tools
- Workarounds may have limitations user should know about
- Respects user's environment preferences

## Rule: Never Run Long-Running Processes in Foreground

**CRITICAL: When using terminal commands, NEVER run servers or long-running processes in foreground mode.**

**Why?**
- Foreground processes block the terminal and cannot be interrupted
- AI assistants cannot send Ctrl+C or interact with running processes
- The terminal session will hang indefinitely

**✅ ALWAYS:**
- Run servers in background: `nohup command > /tmp/output.log 2>&1 &`
- Use timeout for checks: `timeout 5 curl http://localhost:8000`
- Use timed waits: `sleep 3 && check_status`
- Use project scripts that handle background execution

**❌ NEVER:**
- Run development servers directly without background mode
- Start long-running processes that block terminal
- Execute commands that wait for user input without timeouts

**Rationale:**
- Terminal cannot be interrupted once blocked
- Prevents hanging sessions
- Enables automation and scripting
- Better control over process lifecycle

## Rule: Use SSH Config Aliases for Remote Servers

**ALWAYS use SSH config aliases instead of raw IP addresses or long connection strings.**

**✅ GOOD:**
```bash
ssh production                          # Clean, memorable alias
ssh production "systemctl status app"   # Easy to use in commands
scp file.txt production:/path/to/dest   # Works with scp too
```

**❌ BAD:**
```bash
ssh -i ~/.ssh/key.pem user@192.168.1.100                    # Hard to remember
ssh -i ~/.ssh/key.pem -o StrictHostKeyChecking=no user@IP  # Verbose, error-prone
```

**Setup in `~/.ssh/config`:**
```
Host production
    HostName 192.168.1.100
    User ubuntu
    IdentityFile ~/.ssh/production_key
    StrictHostKeyChecking no
```

**Benefits:**
- Memorable aliases instead of IPs
- Consistent connection settings
- Easier to update (change config, not all scripts)
- Works with ssh, scp, rsync, and other SSH tools
- Self-documenting infrastructure
---

**Note:** General development rules have been moved to `.cursor/rules/general_*.mdc` files:
- `general_code_style.mdc` - Code style, comments, orchestration patterns
- `general_testing.mdc` - Testing guidelines
- `general_communication.mdc` - Communication style
- `general_shell_setup.mdc` - Shell environment setup
- `general_logging.mdc` - Logging rules
- `general_code_health.mdc` - Code health and complexity
- `general_git.mdc` - Git workflow
- `general_security.mdc` - Security guidelines
- `general_documentation.mdc` - Documentation rules
- `general_script_development.mdc` - Script development rules

---

# Django Best Practices

## Database Migrations

- **Always review migrations before committing**
- **Never bypass migrations** (no `--fake` or `--skip-checks` in production)
- Test migrations on development database first
- Check for reversibility when possible
- Document complex migrations with comments
- Use `makemigrations --check` in CI/CD to catch missing migrations

**Rationale:**
- Migrations are part of your codebase
- Bad migrations can corrupt production data
- Migrations should be reviewed like code changes
- Reversible migrations enable safe rollbacks
