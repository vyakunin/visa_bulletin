# Cursor Rules

Rules are split into two tiers. See `rules_management.mdc` for the full structure and new-project setup commands.

## Shared rules (symlinks → `~/.cursor/shared_rules/`)

General rules that apply across all projects. Edit the canonical file in `~/.cursor/shared_rules/` — changes propagate to every project automatically.

| Symlink in this directory        | Canonical file                                    |
|----------------------------------|---------------------------------------------------|
| `bazel.mdc`                      | `~/.cursor/shared_rules/bazel.mdc`                |
| `django.mdc`                     | `~/.cursor/shared_rules/django.mdc`               |
| `general_code_health.mdc`        | `~/.cursor/shared_rules/code_health.mdc`          |
| `general_code_style.mdc`         | `~/.cursor/shared_rules/code_style.mdc`           |
| `general_communication.mdc`      | `~/.cursor/shared_rules/communication.mdc`        |
| `general_documentation.mdc`      | `~/.cursor/shared_rules/documentation.mdc`        |
| `general_env_and_security.mdc`   | `~/.cursor/shared_rules/env_and_security.mdc`     |
| `general_git.mdc`                | `~/.cursor/shared_rules/git.mdc`                  |
| `general_logging.mdc`            | `~/.cursor/shared_rules/logging.mdc`              |
| `general_performance.mdc`        | `~/.cursor/shared_rules/performance.mdc`          |
| `general_script_development.mdc` | `~/.cursor/shared_rules/script_development.mdc`   |
| `general_testing.mdc`            | `~/.cursor/shared_rules/testing.mdc`              |
| `rules_management.mdc`           | `~/.cursor/shared_rules/rules_management.mdc`     |

## Project-specific rules (regular files)

Rules specific to this project's infra, conventions, or domain.

- `branching.mdc` — git branching and deployment strategy
- `deployment.mdc` — production/staging deployment procedures
- `employer_clustering.mdc` — employer name clustering rules
- `ingest_framework.mdc` — unified ingest pipeline rules
- `job_title_coherence.mdc` — job title data pipeline rules
- `scripts.mdc` — project scripts and SQL conventions
- `vqs.mdc` — VQS prediction model rules
- `vqs_research_log.mdc` — VQS research log conventions

## All rules have `alwaysApply: true`

Every `.mdc` file sets `alwaysApply: true` so Cursor always loads them. See `rules_management.mdc` → "All Rules Are alwaysApply: true".
