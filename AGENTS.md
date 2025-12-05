# Rule Organization

**Keep non-project-specific general rules portable between projects:**

- General development rules (commit practices, code style, security, testing) should be kept in `AGENTS.md` OR separated into `non_project_specific.mdc` if `AGENTS.md` gets too large
- Project-specific rules (e.g., Bazel build system, Django patterns, domain logic) should go in `.cursor/rules/*.mdc` files
- This separation makes it easy to copy general rules to new projects without filtering

**Current file structure:**
```
AGENTS.md                - General portable rules (commit, code style, security, git workflow)
.cursor/rules/*.mdc      - Project-specific rules (Bazel, Django, scripts, etc.)
```

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
# Code Style and Testing Guidelines

## Python Code Style

- Follow PEP 8
- **Python 3.11+**: Use modern type hints (no `typing` imports for basic types)
  - ✅ `list[str]`, `dict[str, int]`, `tuple[int, str]`
  - ✅ `str | None` (not `Optional[str]`)
  - ✅ `int | str` (not `Union[int, str]`)
  - ❌ `from typing import List, Dict, Tuple, Optional, Union`
- Add docstrings to public functions and classes
- Keep functions focused and single-purpose

## Testing

### Test Quality Rules

**Do NOT write trivial tests** that only check if code exists:
- ❌ BAD: Testing if an enum has a specific value (e.g., `assertEqual(MyEnum.VALUE, "value")`)
- ❌ BAD: Testing if a class exists or can be imported
- ❌ BAD: Testing simple getters/setters with no logic
- ❌ BAD: Testing that a constant equals itself

**DO write meaningful behavioral tests**:
- ✅ GOOD: Testing business logic and transformations
- ✅ GOOD: Testing edge cases and error handling
- ✅ GOOD: Testing integration between components
- ✅ GOOD: Testing data validation and constraints
- ✅ GOOD: Testing complex parsing or extraction logic

**Example:**
```python
# ❌ Trivial - just checks if value exists
def test_has_value(self):
    self.assertEqual(MyEnum.FOO.value, "foo")

# ✅ Meaningful - tests behavior
def test_parse_table_header_to_country_enum(self):
    self.assertEqual(parse_country("CHINA-mainland born"), Country.CHINA)
    self.assertEqual(parse_country("All Chargeability Areas"), Country.ALL)
```

### Test Requirements

- All new features must include meaningful behavioral tests
- Run tests before committing (pre-commit hook handles this)
- Aim for meaningful test coverage, not just high percentages
- Each test should verify actual behavior, not just existence

## Documentation

- Update README.md for user-facing changes
- Update CONTRIBUTING.md for developer workflow changes
- Keep inline code comments focused on "why" not "what"

## Dependencies

- Add new dependencies to requirements.txt (or equivalent package file)
- Use pinned versions for reproducibility
- Document why each dependency is needed
- Review dependency licenses before adding
- Keep dependencies up to date for security patches
# Security Guidelines

## General Token Security Rules

- **NEVER** commit tokens to git
- **NEVER** hardcode tokens in source code or configuration files
- Always reference tokens via environment variables
- Never mention tokens in code comments or documentation

## GitHub Token Security Rules

### Token Storage
- GitHub personal access token is exported as `GITHUB_TOKEN` environment variable in `~/.shrc`
- `~/.shrc` is sourced by both `~/.zshrc` and `~/.bashrc` for cross-shell compatibility
- **NEVER** commit this token to any repository
- **NEVER** mention the token in any project files, code, or documentation

### Git Configuration
- Git is configured to automatically use the token via environment variable `GITHUB_TOKEN`
- The token is exported in `~/.shrc` and available as `$GITHUB_TOKEN` in shell sessions (both bash and zsh)

### Security Best Practices
1. The token in `~/.shrc` should never be:
   - Committed to git repositories
   - Shared in chat logs or documentation
   - Exposed in environment variables in project files
   - Mentioned in any code comments

2. The environment variable `GITHUB_TOKEN` should:
   - Only be set in `~/.shrc` (which is sourced by `~/.zshrc` and `~/.bashrc`)
   - Never be hardcoded in project files or scripts
   - Never be committed to version control

3. If the token needs to be referenced:
   - Use the `GITHUB_TOKEN` environment variable in local shell sessions only
   - Never hardcode in any source code or project configuration files
   - The token is available as `$GITHUB_TOKEN` after shell initialization (works in both bash and zsh)

4. Token rotation:
   - If token is compromised, revoke it immediately on GitHub
   - Update the `GITHUB_TOKEN` export in `~/.shrc` with new token
   - Restart shell or run `source ~/.shrc` (or `source ~/.zshrc` / `source ~/.bashrc`) to reload
# Git Workflow Guidelines

## Commit Rules

- **ONLY commit when user explicitly requests it** (see critical.mdc for details)
- Write clear, descriptive commit messages
- Tests run automatically via pre-commit hook
- Don't bypass hooks unless absolutely necessary
- Keep commits focused and atomic

## Commit Message Format

**Good commit messages:**
```
Add Docker deployment infrastructure

- Update Dockerfile to use gunicorn for production
- Add GitHub Actions workflows for build and deploy
- Update docker-compose.yml to pull from GHCR
- Add comprehensive documentation

This solves memory constraints on Lightsail by building images
in GitHub Actions instead of on production servers.
```

**Bad commit messages:**
```
fix stuff
update files
changes
WIP
```

## Branch Strategy

- Work on feature branches when appropriate
- Keep main/master stable
- Merge only after tests pass
- Use pull requests for team projects

### Rule: Add Files Individually to Commits

**ALWAYS use explicit file paths, NEVER use directories or wildcards.**

**✅ GOOD:**
```bash
git add file1.py
git add file2.py
git add src/module.py
```

**❌ BAD:**
```bash
git add .                    # Adds everything
git add src/                 # Adds entire directory
git add *.py                 # Wildcard
git add -A                   # Adds all changes
```

**Rationale:**
- Prevents accidentally committing unwanted files
- Makes commits more intentional and reviewable
- Easier to see exactly what's being committed
- Avoids committing build artifacts, temp files, etc.

**Exception:**
Only use `git add .` or `git add -A` when explicitly asked by user.

## Git Best Practices

- Review changes before committing (`git diff`)
- Use `.gitignore` appropriately
- Don't commit sensitive data (tokens, passwords, private keys)
- Keep repository clean (no build artifacts, temp files)

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

# Communication Style

## Rule: Direct, Expert Communication

**Be direct, precise, and expert. Skip excessive praise and cheerleading.**

### What to AVOID

**❌ Excessive praise:**
- "Great idea!"
- "Excellent question!"
- "Perfect!"
- "You're absolutely right!"
- Multiple exclamation marks and emojis

**❌ Hedging unnecessarily:**
- "I think maybe we could..."
- "It might be possible to..."
- "Perhaps we should consider..."
(Use these only when genuinely uncertain)

**❌ Over-explaining obvious things:**
- Don't explain what basic commands do unless asked
- Don't repeat information already stated

### What to DO

**✅ Be direct and confident:**
```
The build failed due to missing dependency X. Adding it to requirements.txt.
```

**✅ Challenge assumptions (red teaming):**
```
This approach has a flaw: it won't handle concurrent writes. 
Consider using transactions or a queue.
```

**✅ Provide expert analysis:**
```
Memory usage increased 40% - this is significant. The issue is likely 
the N+1 query pattern in the ORM. Recommend adding select_related().
```

**✅ Be concise:**
```
# Good
Fixed. Testing now.

# Bad  
Great catch! I've gone ahead and fixed that issue for you. 
Now I'll test it to make sure everything works perfectly!
```

### When Praise is Appropriate

**✅ Use sparingly for:**
- Genuinely clever solutions you didn't think of
- User catching critical bugs
- Important corrections to your approach

**Format:**
```
Good catch - that would have caused production issues.
```

### Red Teaming Approach

**Actively look for problems:**
- Security vulnerabilities
- Performance issues
- Edge cases not handled
- Breaking changes impact
- Scalability concerns

**Challenge risky decisions:**
```
User: "Let's deploy on Friday afternoon"
Response: "Deploying Friday afternoon is risky - low coverage if issues arise. 
Recommend Monday morning instead, or ensure rollback plan is ready."
```

### Expert Mode

**Demonstrate expertise through:**
- Precise technical terminology
- Anticipating issues before they occur
- Providing complete solutions, not just suggestions
- Explaining tradeoffs clearly
- Recommending best practices

**Example:**
```
# Expert tone
The Dockerfile needs a non-root user for Bazel's rules_python. 
Adding builder user with home directory.

# Not this
I think maybe the Dockerfile might need a user? Bazel seems to 
want that, if that makes sense? Let me know what you think!
```

### Exceptions

**Be verbose when:**
- Explaining complex architecture decisions
- User is learning a new concept
- Multiple valid options exist (present tradeoffs)
- User explicitly asks for detailed explanation

### Balance

Aim for:
- **70% direct/expert** - Most communications
- **20% detailed explanation** - When complexity warrants
- **10% praise** - When genuinely warranted

# Shell Environment Setup

## Shared Shell Configuration

**User has a shared shell configuration at `~/.shrc`** that is sourced by both `.zshrc` and `.bashrc`.

### What's in ~/.shrc

- Homebrew initialization (works for both Apple Silicon and Intel Macs)
- GitHub token configuration
- Other environment variables and settings

### Using Shell Commands

**When running shell commands, ALWAYS source `~/.shrc` first:**

```bash
# ✅ GOOD: Source shared config
source ~/.shrc && your_command_here

# ❌ BAD: Manually initialize Homebrew
eval "$(/opt/homebrew/bin/brew shellenv)" && your_command_here
```

**Why:**
- Loads all environment variables (brew, tokens, etc.)
- Works across all shells (zsh, bash)
- Single source of truth
- User's preferred configuration method

### Example

```bash
# Check GitHub Actions status
cd /path/to/project && source ~/.shrc && gh run list

# Deploy to production
cd /path/to/project && source ~/.shrc && ./scripts/deploy.sh
```

### Structure

```
~/
  .shrc                  ← Shared config (Homebrew, tokens)
  .zshrc                 ← Sources .shrc
  .bashrc                ← Sources .shrc
```

### Rationale

- **DRY principle**: Define environment once in `~/.shrc`
- **Cross-shell**: Works in both zsh and bash
- **Maintainable**: Update one file, affects all shells
- **User preference**: Respects user's configuration setup
