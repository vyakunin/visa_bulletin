load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
# Note: sh_binary is a built-in Bazel rule, no need to load it

py_binary(
    name = "makemigrations_wrapper",
    srcs = ["makemigrations_wrapper.py"],
    main = "makemigrations_wrapper.py",
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
        "//lib/utils:logging_utils",
        "//django_config:logging_config",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "explore_db",
    srcs = ["explore_db.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models:bulletin",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "spot_check_new_dol_files",
    srcs = ["spot_check_new_dol_files.py"],
    main = "spot_check_new_dol_files.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:salary",
        "//models/ingest:data_source",
        "//lib/utils:http_utils",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("requests"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backfill_content_hashes",
    srcs = ["backfill_content_hashes.py"],
    main = "backfill_content_hashes.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models/ingest:data_source",
        "//lib/utils:http_utils",
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

py_binary(
    name = "benchmark_db_ingest",
    srcs = ["benchmark_db_ingest.py"],
    main = "benchmark_db_ingest.py",
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

py_binary(
    name = "clear_cache",
    srcs = ["clear_cache.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:salary",
        "//lib/utils:logging_utils",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# investigate_salary_issues target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# investigate_validation_issues target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# investigate_null_salaries target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data -- --check-incomplete-records
