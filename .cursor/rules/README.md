# Visa Bulletin Project Rules

This directory contains project-specific Cursor rules for the visa bulletin parser.

## Structure

- **overview.mdc**: Project overview and scope
- **bazel.mdc**: Bazel build system rules (always use Bazel)
- **django.mdc**: Django patterns (TextChoices, settings)
- **scripts.mdc**: Project scripts and workflows
- **deployment.mdc**: Deployment and rollout rules (always ask about versions)

## Rule Priority

1. **Global rules** (`~/.cursorrules/`): Apply to all projects
2. **Project rules** (this directory): Project-specific, can override global rules

## Backup

Original single-file rules backed up to: `.cursorrules.backup`

