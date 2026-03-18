# Root BUILD file
# This file should only contain top-level targets (runserver, migrate) and aliases.
# BUILD rules for code in subdirectories should be co-located with that code.
# See .cursor/rules/bazel.mdc for BUILD file organization rules.

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
# Note: alias is a built-in Bazel rule, no need to load it
# Note: Ollama repository is set up via module extension in MODULE.bazel

# See .cursor/rules/bazel.mdc for template on creating one-off Django scripts

exports_files([
    "requirements.txt",
])

# Note: Bulletin refresh scripts have been replaced by the unified ingest pipeline
# Use: bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --domain visa_bulletin
# Or: bazel run //scripts/ingest:run_pipeline -- discover-and-ingest --all-domains

py_binary(
    name = "runserver",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["runserver", "8000", "--noreload"],
    data = [
        "//webapp:templates",
        # Database is PostgreSQL (no SQLite files needed)
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:urls",
        "//django_config:context_processors",
        "//webapp:apps",
        "//webapp/views:prediction_views",
        "//webapp/views:blog_views",
        "//webapp:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:salary",
        "//models:blog",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:visa_program",
        requirement("Django"),
        requirement("plotly"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("tenacity"),
        requirement("narwhals"),

    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# Alias for backward compatibility - rule moved to scripts/BUILD
# Actual target: scripts/BUILD:makemigrations_wrapper (line 4)
alias(
    name = "makemigrations",
    actual = "//scripts:makemigrations_wrapper",
    visibility = ["//visibility:public"],
)

py_binary(
    name = "migrate",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["migrate"],
    # Database is PostgreSQL (no SQLite files needed)
    data = [
        "//models:migrations",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:urls",
        "//webapp:apps",
        "//webapp:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:salary",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//models:vqs",
        "//models:raw_facts",
        "//models:blog",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# Aliases for backward compatibility - rules moved to subdirectories

# Actual target: scripts/ingest/BUILD:run_pipeline (line 4)
alias(
    name = "ingest",
    actual = "//scripts/ingest:run_pipeline",
    visibility = ["//visibility:public"],
)

# Actual target: scripts/ingest/BUILD:rollback (line 30)
alias(
    name = "ingest_rollback",
    actual = "//scripts/ingest:rollback",
    visibility = ["//visibility:public"],
)

# Target to update requirements.lock from requirements.txt
# Run this whenever requirements.txt changes to ensure Bazel can resolve dependencies
# Update requirements.lock from requirements.txt
# Requires: pip-tools installed (pip install pip-tools)
# This is a build-time tool dependency, similar to Bazel itself
alias(
    name = "update_requirements_lock",
    actual = "//tools:update_requirements_lock",
)


# check_migrations: No alias needed - not referenced anywhere, use //scripts/oneoff:check_migrations directly

# Actual target: scripts/BUILD:run_sql
alias(
    name = "run_sql",
    actual = "//scripts:run_sql",
)

# fix_calculation deleted - use fix_high_wage_records instead
# alias(
#     name = "fix_salary_calculation",
#     actual = "//scripts/salary:fix_high_wage_records",
# )

# Actual target: scripts/salary/BUILD:drop_data (line 40)
alias(
    name = "drop_salary_data",
    actual = "//scripts/salary:drop_data",
)

# Actual target: scripts/salary/BUILD:validate_data (line 60)
alias(
    name = "validate_salary_data",
    actual = "//scripts/salary:validate_data",
)

# Aliases for backward compatibility - rules moved to subdirectories
# validate_data_comprehensive removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# Actual target: scripts/BUILD:benchmark_db_ingest (line 77)
alias(
    name = "benchmark_db_ingest",
    actual = "//scripts:benchmark_db_ingest",
    visibility = ["//visibility:public"],
)

# Actual target: scripts/BUILD:clear_cache (line 100)
alias(
    name = "clear_cache",
    actual = "//scripts:clear_cache",
)

# Actual target: scripts/salary/BUILD:fix_high_wage_records (line 100)
alias(
    name = "fix_high_wage_records",
    actual = "//scripts/salary:fix_high_wage_records",
)

# Actual target: scripts/salary/BUILD:update_wage_thresholds (line 140)
alias(
    name = "update_wage_thresholds",
    actual = "//scripts/salary:update_wage_thresholds",
)

# investigate_salary_issues removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# investigate_validation_issues removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# Actual target: scripts/salary/BUILD:fix_state_codes (line 182)
alias(
    name = "fix_state_codes",
    actual = "//scripts/salary:fix_state_codes",
)

# Actual target: scripts/salary/BUILD:cleanup_orphaned_employers (line 202)
alias(
    name = "cleanup_orphaned_employers",
    actual = "//scripts/salary:cleanup_orphaned_employers",
)

# Actual target: scripts/salary/BUILD:review_clustering (line 222)
alias(
    name = "review_clustering",
    actual = "//scripts/salary:review_clustering",
    visibility = ["//visibility:public"],
)

# Actual target: scripts/salary/BUILD:cluster_existing_employers (line 243)
alias(
    name = "cluster_existing_employers",
    actual = "//scripts/salary:cluster_existing_employers",
    visibility = ["//visibility:public"],
)
