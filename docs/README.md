# Documentation

This directory contains all project documentation organized by topic.

## Directory Structure

### Core Documentation (Root Level)
- **BAZEL.md** - Bazel build system guide (dependencies, targets, runfiles)
- **BAZEL_DEPENDENCIES.md** - Managing Bazel dependencies
- **BAZEL_RUNFILES_IMPLEMENTATION.md** - Runfiles implementation details
- **BAZEL_RUNFILES.md** - Working with Bazel runfiles
- **DEV_SETUP.md** - Development environment setup
- **ANALYTICS_QUICKSTART.md** - Analytics integration quickstart
- **PAGESPEED_OPTIMIZATIONS.md** - Performance and PageSpeed optimizations
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

**Key Files:**
- DEPLOYMENT.md - Deployment overview
- DOCKER_DEPLOYMENT.md - Docker-based deployment guide
- DEPLOYMENT_ZERO_DOWNTIME.md - Blue-green deployment strategy
- ROLLOUT_FLOW.md - Complete rollout process
- SSH_COMMANDS.md - Common SSH operations

**Related Code:** `deployment/`, `scripts/deploy-zero-downtime.sh`

---

#### [seo/](seo/)
Documentation for SEO optimization and search engine visibility.

**Key Files:**
- SEO_OPTIMIZATION.md - SEO best practices and implementation

**Related Code:** `webapp/templates/`, `django_config/context_processors.py`

---

#### [future_features/](future_features/)
Design documents for features that are planned but not yet implemented.

**Key Files:**
- COMPANY_REPORT_CARD_DESIGN.md - Company green card sponsorship grading system

**Note:** These are design proposals, not current features.

---

## Finding Documentation

### By Task

**Setting up development environment:**
- Start with: `DEV_SETUP.md`
- Then: `BAZEL.md` for build system

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

**Deploying to production:**
- Overview: `deployment/DEPLOYMENT.md`
- Zero-downtime: `deployment/DEPLOYMENT_ZERO_DOWNTIME.md`
- Rollout flow: `deployment/ROLLOUT_FLOW.md`

### By Component

- **Models:** See `department_of_labor/DATABASE_DESIGN.md` for salary models, `ingest/PIPELINE_DESIGN.md` for ingest models
- **Ingest Pipeline:** See `ingest/` directory
- **Business Logic:** See component-specific directories (e.g., `employer_clustering/`)
- **Web Application:** See `seo/SEO_OPTIMIZATION.md` and root README.md
- **Build System:** See `BAZEL.md` and related files

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

