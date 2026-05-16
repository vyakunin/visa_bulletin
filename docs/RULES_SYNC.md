# Rules Synchronization: Cursor ↔ Claude Code

This project maintains rules in two locations with a bidirectional sync system. **Claude Code naturally learns and modifies rules in its memory files during conversations**, and the sync system captures those changes back to Cursor.

## The Two Worlds

### Cursor World (Source of Truth)
- **Global shared rules:** `~/.cursor/shared_rules/*.mdc` (20 files)
- **Project-specific rules:** `.cursor/rules/*.mdc` (symlinks + 9 project-only files) + `AGENTS.md`

Structure:
```
~/.cursor/shared_rules/bazel.mdc, django.mdc, ...  ← authoritatively managed
  .cursor/rules/bazel.mdc → symlinks to shared
  .cursor/rules/branching.mdc, deployment.mdc, ...  ← project-specific
AGENTS.md                                           ← critical rules
```

### Claude Code World (Memory-First)
Claude Code reads and learns rules from **memory files** in its project-specific memory directory. This allows CC to naturally augment/improve rules during conversations, and those changes sync back to Cursor.

- **Shared rules:** `~/.claude/projects/<project>/memory/rules_shared_*.md` (19 files)
- **Project rules:** `~/.claude/projects/<project>/memory/rules_project_*.md` (9 files)
- **Memory index:** `~/.claude/projects/<project>/memory/MEMORY.md` (auto-managed)
- **Bootstrap:** `CLAUDE.md` (minimal, just AGENTS.md for initial context)

Structure:
```
~/.claude/projects/<project>/memory/
  MEMORY.md                          ← auto-managed index
  rules_shared_bazel.md, ...         ← shared rules (from Cursor)
  rules_project_AGENTS.md, ...       ← project rules (from Cursor + CC edits)
```

**Why memory files?** When Claude Code learns a rule during a conversation and saves it to memory, that rule persists across sessions. The sync system captures those changes back to Cursor, so learned rules become canonical.

## Syncing Rules

### When Working in Cursor

Edit rules directly in `.mdc` files:
```bash
# Edit shared rules (for all projects)
$EDITOR ~/.cursor/shared_rules/bazel.mdc

# Edit project-specific rules (visa_bulletin only)
$EDITOR .cursor/rules/branching.mdc
$EDITOR AGENTS.md
```

After editing, sync to Claude Code memory:
```bash
bazel run //tools:sync_rules -- cursor2claude
```

This writes rules to:
- `~/.claude/projects/<project>/memory/rules_shared_*.md` (shared rules)
- `~/.claude/projects/<project>/memory/rules_project_*.md` (project rules)
- Updates `MEMORY.md` index
- `CLAUDE.md` (bootstrap only, contains AGENTS.md)

When you open Claude Code, it reads the rules from memory files.

### When Working in Claude Code

Claude Code naturally works with rules in memory. You can:
1. **Read rules** — CC loads them from `rules_shared_*.md` and `rules_project_*.md`
2. **Modify rules** — CC can edit these files directly during conversations
3. **Learn new rules** — CC can save new rules to memory (as new memory files)

When you want to capture those changes in Cursor:
```bash
bazel run //tools:sync_rules -- claude2cursor
```

This:
1. Reads all `rules_*.md` files from CC memory
2. Parses them back to `.mdc` format
3. Writes to `~/.cursor/shared_rules/` and `.cursor/rules/`
4. Preserves YAML frontmatter

Then review the updated `.mdc` files in Cursor and commit.

## Sync Commands

```bash
# Copy Cursor rules → Claude Code memory (primary direction)
bazel run //tools:sync_rules -- cursor2claude

# Parse Claude Code memory → Cursor .mdc files (round-trip)
bazel run //tools:sync_rules -- claude2cursor

# Check sync status and detect conflicts
bazel run //tools:sync_rules -- status

# Dry-run (shows what would happen without making changes)
bazel run //tools:sync_rules -- cursor2claude --dry-run
bazel run //tools:sync_rules -- claude2cursor --dry-run
```

## Conflict Resolution

The `status` command detects conflicts based on file timestamps:

```
⚠️  Cursor rules are newer than memory files.
   Run: sync_rules cursor2claude
```

**Last-writer-wins rule:** Run the appropriate sync command to resolve:
- If you edited in Cursor: run `cursor2claude` (overwrites memory files)
- If you edited in Claude Code: run `claude2cursor` (overwrites `.mdc` files)

**Good practice:** Always run `status` before switching between the two editors.

## Implementation Details

### File Format Preservation

**`.mdc` files (Cursor):**
```yaml
---
alwaysApply: true
---

# Content here...
```

**Memory files (Claude Code):**
```yaml
---
alwaysApply: true
---

# Content here...
```

Memory files use the same YAML frontmatter format as `.mdc` files. The sync script preserves frontmatter during round-trips.

### Naming Convention

Memory files follow a naming scheme for reliable parsing:
- `rules_shared_<name>.md` — from `~/.cursor/shared_rules/<name>.mdc`
- `rules_project_<name>.md` — from `.cursor/rules/<name>.mdc` or `AGENTS.md`

This allows the sync script to correctly map back to original filenames.

### Multi-Project Shared Rules

When syncing shared rules:
- `cursor2claude` writes shared rules to **all projects** with CC memory (propagates updates)
- `claude2cursor` reads shared rules from **current project** only (per-project view)

To sync shared rule updates across all projects:
```bash
# In visa_bulletin
bazel run //tools:sync_rules -- cursor2claude

# In personal_blog (or other projects)
bazel run //tools:sync_rules -- cursor2claude
```

Each project gets the latest shared rules in its memory directory.

### Memory Index (MEMORY.md)

The sync script updates `MEMORY.md` with rule entries:
```markdown
- [bazel](rules_shared_bazel.md) — Bazel Build System Rules
- [AGENTS](rules_project_AGENTS.md) — Critical Development Rules
- [branching](rules_project_branching.md) — Branching and Deployment Strategy
```

This index is auto-managed and human-readable.

## Shared Tool

The sync script is shared across projects at `~/.cursor/tools/sync_rules.py`. Each project:
- Has a Bazel target `//tools:sync_rules` that invokes the shared script
- Can run `bazel run //tools:sync_rules -- <command>` from its own directory
- The script auto-detects the project root (looks for `MODULE.bazel` or `WORKSPACE`)

To set up sync in a new project, add to `tools/BUILD`:
```python
genrule(
    name = "sync_rules_wrapper",
    outs = ["sync_rules.sh"],
    cmd = """cat > $@ <<'EOF'
#!/bin/bash
set -e
SHARED_SYNC="$$HOME/.cursor/tools/sync_rules.py"
if [ ! -f "$$SHARED_SYNC" ]; then
  echo "Error: Shared sync script not found at $$SHARED_SYNC" >&2
  exit 1
fi
WORKSPACE="$${BUILD_WORKSPACE_DIRECTORY:-.}"
cd "$$WORKSPACE"
exec python3 "$$SHARED_SYNC" "$$@"
EOF
chmod +x $@""",
    executable = True,
)

sh_binary(
    name = "sync_rules",
    srcs = [":sync_rules_wrapper"],
    visibility = ["//visibility:public"],
)
```

Then run: `bazel run //tools:sync_rules -- cursor2claude`

## Workflow Examples

### Scenario 1: Editing in Cursor, deploying to Claude Code

```bash
# Edit in Cursor (in IDE or via $EDITOR)
$EDITOR ~/.cursor/shared_rules/bazel.mdc
$EDITOR .cursor/rules/deployment.mdc

# Sync to Claude Code memory
bazel run //tools:sync_rules -- cursor2claude

# Now Claude Code sees the updates in memory files
# When you open Claude Code, it reads rules_shared_bazel.md, etc.
```

### Scenario 2: Claude Code learns a rule, sync back to Cursor

```bash
# Work in Claude Code (it learns/modifies a rule)
# CC saves changes to ~/.claude/projects/<project>/memory/rules_project_*.md

# Back in Cursor: sync changes back
bazel run //tools:sync_rules -- claude2cursor

# Review the updated .mdc files
git diff .cursor/rules/

# Commit the learned rules
git add .cursor/rules/
git commit -m "Capture learned rule improvements from Claude Code"
```

### Scenario 3: Parallel edits in both worlds (conflict)

```bash
# Work in Cursor
$EDITOR ~/.cursor/shared_rules/git.mdc

# Also work in Claude Code (it modifies git.mdc in memory)

# Back in Cursor: check status
bazel run //tools:sync_rules -- status

# Output:
#   ⚠️  Cursor rules are newer than memory files.
#   ⚠️  CC memory is newer than Cursor rules.
#   ...

# Resolve: decide which side is authoritative
# Option A: Keep Cursor version
bazel run //tools:sync_rules -- cursor2claude

# Option B: Keep Claude Code version
bazel run //tools:sync_rules -- claude2cursor

# Option C: Manual merge
# Edit .cursor/rules/git.mdc manually, then cursor2claude
```

## Troubleshooting

### Memory files not found in Claude Code

Make sure `cursor2claude` has been run:
```bash
bazel run //tools:sync_rules -- cursor2claude
```

Claude Code reads from `~/.claude/projects/<project>/memory/rules_*.md`.

### Changes not syncing back from Claude Code

Run `status` to check timestamps:
```bash
bazel run //tools:sync_rules -- status
```

If CC memory is newer but you want to capture changes:
```bash
bazel run //tools:sync_rules -- claude2cursor
```

### `rules_project_AGENTS.md` not found

This is the project critical rules memory file. It's auto-generated from `AGENTS.md`:
```bash
bazel run //tools:sync_rules -- cursor2claude
```

### Sync script not found

```
Error: Shared sync script not found at ~/.cursor/tools/sync_rules.py
```

Ensure the shared script exists. It's located at `~/.cursor/tools/sync_rules.py`.

## See Also

- `.cursor/rules/rules_management.mdc` — Full Cursor rules setup documentation
- `~/.cursor/tools/sync_rules.py` — Shared sync script source code
- `tools/run_claude.py` — Bazel launcher for Claude CLI
