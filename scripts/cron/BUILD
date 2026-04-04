# Cron jobs and automated maintenance scripts

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "refresh_data_py",
    srcs = ["refresh_data.py"],
    main = "refresh_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//scripts/cron/refresh:refresh",
    ],
)

py_binary(
    name = "refresh_and_switch_py",
    srcs = ["refresh_and_switch.py"],
    main = "refresh_and_switch.py",
    visibility = ["//visibility:public"],
    deps = [
        "//scripts/cron/refresh:refresh",
    ],
)

py_binary(
    name = "refresh_bulletin",
    srcs = ["refresh_bulletin.py"],
    main = "refresh_bulletin.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/blog:blog",
        "//lib/ingest:orchestrator",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:visa_bulletin",
        "//lib/utils:logging_utils",
        "//lib/utils:url_utils",
        "//models:blog",
        "//models:bulletin",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("redis"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

sh_binary(
    name = "refresh_data",
    srcs = ["refresh_data.sh"],
    data = [
        ":refresh_data_py",
        "//scripts/ingest:run_pipeline",
        "//scripts/salary:manage_salary_indexes",
        "//scripts/salary:backfill_job_title_links",
        "//scripts/salary:backfill_source_file_date",
        "//scripts/salary:cluster_job_titles",
        "//scripts/salary:update_employer_stats",
        "//scripts/salary:cluster_existing_employers",
        "//scripts/salary:update_job_title_cluster_stats",
        "//scripts/salary:populate_job_title_slugs",
        "//scripts/cache:warm_cache",
    ],
    visibility = ["//visibility:public"],
)
