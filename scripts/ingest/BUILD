load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
load("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")

# Note: sh_binary is a built-in Bazel rule, no need to load it

py_binary(
    name = "run_pipeline",
    srcs = ["run_pipeline.py"],
    main = "run_pipeline.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/ingest:ingest",
        "//lib/ingest:orchestrator",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:ingest",
        "//lib/utils:logging_utils",
        "//lib/utils:url_utils",
        "//django_config:settings",
        "//django_config:logging_config",
        "//django_config:urls",
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
    name = "rollback",
    srcs = ["rollback.py"],
    main = "rollback.py",
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

sh_binary(
    name = "ingest_and_cluster",
    srcs = ["ingest_and_cluster.sh"],
    visibility = ["//visibility:public"],
)

py_binary(
    name = "inspect_raw_file_headers",
    srcs = ["inspect_raw_file_headers.py"],
    main = "inspect_raw_file_headers.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//django_config:settings",
        "//django_config:logging_config",
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
    name = "inspect_source_columns",
    srcs = ["inspect_source_columns.py"],
    main = "inspect_source_columns.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:data_source_utils",
        "//lib/utils:excel_utils",
        "//lib/utils:http_utils",
        "//lib/utils:logging_utils",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:ingest",
        "//models:salary",
        "//webapp:apps",
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
    name = "inspect_unknown_source_rows",
    srcs = ["inspect_unknown_source_rows.py"],
    main = "inspect_unknown_source_rows.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/parsing/salary:db_importer",
        "//lib/utils:excel_utils",
        "//lib/utils:http_utils",
        "//lib/utils:logging_utils",
        "//models:salary",
        "//webapp:apps",
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
    name = "check_run_status",
    srcs = ["check_run_status.py"],
    main = "check_run_status.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
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
    name = "register_local_files",
    srcs = ["register_local_files.py"],
    main = "register_local_files.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
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
    name = "extract_smoke_test_samples",
    srcs = ["extract_smoke_test_samples.py"],
    main = "extract_smoke_test_samples.py",
    deps = [
        "//django_config:settings",
        "//lib/utils:excel_utils",
        "//lib/utils:http_utils",
        "//models:salary",
        "//models/ingest:ingest",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("openpyxl"),
        requirement("PyYAML"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "reset_incomplete_runs",
    srcs = ["reset_incomplete_runs.py"],
    main = "reset_incomplete_runs.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
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
    name = "reset_missing_files",
    srcs = ["reset_missing_files.py"],
    main = "reset_missing_files.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
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
