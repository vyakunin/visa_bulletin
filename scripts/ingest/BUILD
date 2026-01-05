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
