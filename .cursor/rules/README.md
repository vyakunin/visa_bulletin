# Visa Bulletin Project Rules

This directory contains project-specific Cursor rules for the visa bulletin parser.

## Structure

- **overview.mdc**: Project overview and scope
- **general_*.mdc**: General portable rules (code style, testing, git, security, etc.) - prefixed with `general_` to identify portable rules
- **bazel.mdc**: Bazel build system rules (always use Bazel)
- **django.mdc**: Django patterns (TextChoices, settings)
- **scripts.mdc**: Project scripts and workflows
- **deployment.mdc**: Deployment and rollout rules (always ask about versions)
- **job_title_coherence.mdc**: Job title data coherence (pipeline order, representative title, deployment smoke test)

**Naming convention:**
- Files prefixed with `general_` contain portable rules that apply across all projects
- Files without `general_` prefix are project-specific to this codebase
- This makes it easy to copy general rules to new projects

## Rule Priority

1. **Global rules** (`~/.cursorrules/`): Apply to all projects
2. **Project rules** (this directory): Project-specific, can override global rules

## Backup

Original single-file rules backed up to: `.cursorrules.backup`

