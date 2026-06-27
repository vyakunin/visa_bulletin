# Documentation

This directory contains all project documentation organized by topic.

## Directory Structure

### Core Documentation (Root Level)

**Operations & Data:**
- **INGESTION_PLAYBOOK.md** - Step-by-step guide for running DOL data ingestion (development)
- Production data-refresh architecture and concrete hosting topology live in the private ops repo, not in this public repository.

**Development Setup:**
- **DEV_SETUP.md** - Local development environment setup (macOS)
- **POSTGRESQL_SETUP.md** - Local PostgreSQL setup for development

**Build System:**
- **BAZEL.md** - Bazel build system guide (dependencies, targets, runfiles)
- **BAZEL_DEPENDENCIES.md** - Managing Bazel dependencies
- **BAZEL_RUNFILES.md** - Working with Bazel runfiles
- **BAZEL_RUNFILES_IMPLEMENTATION.md** - Runfiles implementation details

**Reference:**
- **PAGESPEED_OPTIMIZATIONS.md** - Performance optimization decisions and rationale
- **FEATURE_IDEAS.md** - Feature ideas and proposals

### Organized by Topic

#### [employer_clustering/](employer_clustering/)
Documentation for the employer clustering system that groups similar employer names.

**Key Files:**
- SYSTEM_EXPLANATION.md - Complete system architecture
- BENCHMARK_WORKFLOW.md - Benchmarking and tuning workflow
- ITERATIVE_TUNING.md - Performance improvement process

**Related Code:** `lib/business/salary/`

---

#### [department_of_labor/](department_of_labor/)
Documentation for Department of Labor (DOL) salary data (H-1B LCA, PERM, worksite data).

**Key Files:**
- DATABASE_DESIGN.md - Database schema and field mappings
- VIEWS_PROPOSALS.md - Query optimization proposals
- WAGE_THRESHOLDS.md - Wage validation rules
- WORKSITE_FILES_DESIGN.md - Worksite data separation design (future)

**Related Code:** `models/salary.py`, `lib/ingest/plugins/dol_*.py`

---

#### [ingest/](ingest/)
Documentation for the unified ingest pipeline framework (download → parse → transform → load → validate).

**Key Files:**
- PIPELINE_DESIGN.md - Complete pipeline architecture and design
- VALIDATION_FRAMEWORK.md - Post-ingest validation framework
- VALIDATION_MANUAL_FLOW.md - Manual validation workflow

**Related Code:** `lib/ingest/`, `models/ingest/`

---

#### [deployment/](deployment/)
Documentation for deployment, infrastructure, and operations.

**Start Here:**
- **ROLLOUT_FLOW.md** - Complete rollout process for new deployments
- Concrete production-server setup (hosts, hardware, provisioning) lives in the private ops repo, not in this public repository.

**Related Code:** `deployment/`; release tooling lives in `visa_bulletin_platform/hosting/` (see `.claude/rules/branching.md`).

---

#### [seo/](seo/)
Documentation for SEO optimization and search engine visibility.

**Key Files:**
- SEO_OPTIMIZATION.md - SEO best practices and implementation

**Related Code:** `webapp/templates/`, `django_config/context_processors.py`

---

#### [future_features/](future_features/)
Design documents for features that are planned or partially implemented.

**Key Files:**
- COMPANY_REPORT_CARD_DESIGN.md - Company green card sponsorship grading system
- VQS_RUNBOOK.md - Operational runbook for VQS predictions system (add I-140 data, re-run accuracy)
- VQS_NEW_SUGGESTIONS.md - Active improvement ideas for the VQS prediction model
- VQS_META_PARAMS_AND_TUNING.md - Meta-parameter design and Optuna tuning details
- VQS_FAMILY_EXTENSION_DESIGN.md - Design for extending VQS to family-based categories
- VQS_META_PARAMS_CRITIQUE.md - Critical analysis of current meta-param approach

**Note:** These are design proposals and operational guides for planned or in-progress work.

---

## Finding Documentation

### By Task

**Setting up local development environment:**
- Start with: `DEV_SETUP.md` (developer tools)
- Database: `POSTGRESQL_SETUP.md` (local PostgreSQL)
- Build system: `BAZEL.md`

**Running data ingestion (development):**
- Step-by-step guide: `INGESTION_PLAYBOOK.md`
- Pipeline design: `ingest/PIPELINE_DESIGN.md`

**Working with DOL salary data:**
- Overview: `department_of_labor/README.md`
- Database design: `department_of_labor/DATABASE_DESIGN.md`
- Validation: `ingest/VALIDATION_MANUAL_FLOW.md`

**Improving employer clustering:**
- Overview: `employer_clustering/README.md`
- System architecture: `employer_clustering/SYSTEM_EXPLANATION.md`
- Tuning workflow: `employer_clustering/BENCHMARK_WORKFLOW.md`

**Adding new data sources:**
- Pipeline design: `ingest/PIPELINE_DESIGN.md`
- Create plugin: See `lib/ingest/plugins/` for examples

**Setting up new production instance:**
- Rollout process: `deployment/ROLLOUT_FLOW.md`
- Concrete server provisioning lives in the private ops repo (not in this public repository).

**Understanding production data refresh:**
- Manual ingestion: `INGESTION_PLAYBOOK.md` (for testing/dev only)
- The production refresh architecture lives in the private ops repo (not in this public repository).

### By Component

- **Models:** See `department_of_labor/DATABASE_DESIGN.md` for salary models, `ingest/PIPELINE_DESIGN.md` for ingest models
- **Ingest Pipeline:** See `ingest/` directory
- **Business Logic:** See component-specific directories (e.g., `employer_clustering/`)
- **Web Application:** See `seo/SEO_OPTIMIZATION.md` and root README.md
- **Build System:** See `BAZEL.md` and related files
- **VQS Predictions:** See `PREDICTIONS_ASSESSMENT.md` (research log), `future_features/VQS_RUNBOOK.md` (operations), `lib/business/vqs/README.md` (code-level)

## Contributing to Documentation

When adding new documentation:

1. **Choose the right location:**
   - Feature-specific docs → Appropriate topic directory
   - General development docs → Root level
   - Future proposals → `future_features/`

2. **Update README files:**
   - Add entry to this README.md
   - Add entry to topic-specific README.md
   - Update any related documentation

3. **Follow naming conventions:**
   - Use UPPER_CASE_WITH_UNDERSCORES.md
   - Be descriptive (e.g., "BENCHMARK_WORKFLOW.md" not "BENCHMARK.md")
   - Avoid redundant prefixes (e.g., "WORKFLOW.md" in `employer_clustering/`, not "CLUSTERING_WORKFLOW.md")

4. **Keep current state only:**
   - Document what IS, not what WAS
   - Delete progress reports after work completes
   - Move completed design docs to implementation directories or delete if fully integrated
   - Keep only future proposals in `future_features/`

## Documentation Standards

- **Audience:** Developers familiar with Django and Python
- **Style:** Clear, concise, practical examples
- **Format:** Markdown with code blocks and diagrams where helpful
- **Maintenance:** Update docs when code changes, delete outdated docs

