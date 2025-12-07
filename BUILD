# Root BUILD file

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "requirements.txt",
])

py_binary(
    name = "refresh_data",
    srcs = ["scripts/bulletin/refresh_data.py"],
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:publication_data",
        "//lib/parsing/bulletin:bulletin_table",
        "//lib/parsing/bulletin:db_importer",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
        requirement("requests"),
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
        requirement("idna"),
        requirement("urllib3"),
        requirement("certifi"),
        requirement("charset-normalizer"),
        requirement("typing-extensions"),
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "refresh_data_incremental",
    srcs = ["scripts/bulletin/refresh_incremental.py"],
    main = "scripts/bulletin/refresh_incremental.py",
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:publication_data",
        "//lib/parsing/bulletin:bulletin_table",
        "//lib/parsing/bulletin:db_importer",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
        requirement("requests"),
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
        requirement("idna"),
        requirement("urllib3"),
        requirement("certifi"),
        requirement("charset-normalizer"),
        requirement("typing-extensions"),
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "runserver",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["runserver", "8000", "--noreload"],
    data = [
        "//webapp:templates",
        # Note: visa_bulletin.db is created at runtime, not a build dependency
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:urls",
        "//django_config:context_processors",
        "//webapp:apps",
        "//webapp:views",
        "//webapp:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:salary",
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

py_binary(
    name = "makemigrations",
    srcs = ["scripts/makemigrations_wrapper.py"],
    main = "scripts/makemigrations_wrapper.py",
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
        "//models/ingest:ingest",  # Include ingest models
        "//models/enums:visa_program",
        "//lib/utils:logging_utils",  # Required by wrapper script
        "//django_config:logging_config",  # Required by wrapper script
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "migrate",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["migrate"],
    # Note: visa_bulletin.db is created by migrate, not a dependency
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
        "//models/ingest:ingest",  # Include ingest models (IngestVersion, etc.)
        "//models/enums:visa_program",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter (Bazel uses underscores)
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "download_salary_data",
    srcs = ["scripts/salary/download_data.py"],
    main = "scripts/salary/download_data.py",
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//django_config:settings",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
        requirement("idna"),
        requirement("urllib3"),
        requirement("certifi"),
        requirement("charset-normalizer"),
        requirement("typing-extensions"),
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "ingest",
    srcs = ["scripts/ingest/run_pipeline.py"],
    main = "scripts/ingest/run_pipeline.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:ingest",
        "//lib/ingest:orchestrator",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:ingest",
        "//lib/utils:logging_utils",
        "//django_config:settings",
        "//django_config:logging_config",
        "//django_config:urls",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "ingest_rollback",
    srcs = ["scripts/ingest/rollback.py"],
    main = "scripts/ingest/rollback.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:versioning",
        "//models/ingest:ingest",
        "//models:salary",
        "//models:visa_cutoff_date",
        "//lib/utils:logging_utils",
        "//django_config:settings",
        "//django_config:logging_config",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "check_duplicates",
    srcs = ["scripts/check_duplicates.py"],
    main = "scripts/check_duplicates.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest/plugins:dol_perm",
        "//models/ingest:ingest",
        "//lib/utils:http_utils",
        "//django_config:settings",
        "//django_config:urls",
        "//webapp:apps",
        "//webapp:urls",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# DEPRECATED: import_salary_data removed - use //:ingest instead

# Convenience target to restart the development server
sh_binary(
    name = "restart_server",
    srcs = ["scripts/restart_server.sh"],
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

py_binary(
    name = "explore_db",
    srcs = ["scripts/explore_db.py"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models:bulletin",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_salary_calculation",
    srcs = ["scripts/salary/fix_calculation.py"],
    main = "scripts/salary/fix_calculation.py",
    deps = [
        "//lib/utils:logging_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "drop_salary_data",
    srcs = ["scripts/salary/drop_data.py"],
    main = "scripts/salary/drop_data.py",
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "validate_salary_data",
    srcs = ["scripts/salary/validate_data.py"],
    main = "scripts/salary/validate_data.py",
    deps = [
        "//lib/utils:logging_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# DEPRECATED: update_salary_data removed - use //:ingest instead

py_binary(
    name = "benchmark_db_ingest",
    srcs = ["scripts/benchmark_db_ingest.py"],
    main = "scripts/benchmark_db_ingest.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//lib/parsing/salary:db_importer",
        "//lib/parsing/salary:wage_unit_correction",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# DEPRECATED: reimport_salary_data removed - use //:ingest_rollback and //:ingest instead
# py_binary(
#     name = "reimport_salary_data",
#     srcs = ["scripts/salary/reimport_data.py"],
#     deps = [...],
# )

py_binary(
    name = "clear_cache",
    srcs = ["scripts/clear_cache.py"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:salary",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

