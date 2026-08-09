load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
# Note: sh_binary is a built-in Bazel rule, no need to load it

# Read as a data file by //tests:test_shared_chrome_cookie_scope (static source guard).
# Not a py_binary target: it runs on the minipc via `uv run` with playwright, which is
# deliberately outside the Bazel/prod dependency graph.
exports_files([
    "fetch_bulletin_via_browser.py",
    # Read by //tests:test_bulletin_sync_alerting — the bridge is the only bulletin
    # ingest path, so its alerting + state-file contract is guarded statically.
    "sync_bulletin_to_prod.sh",
])

# Every top-level PEP-723 script, read as data by //tests:test_mcp_pin_guard. It is a
# glob rather than a list so a NEW script that imports the daily_checkup MCP server is
# swept into the guard automatically — the pin drift it checks for is exactly the kind
# that arrives with a file nobody remembered to register.
filegroup(
    name = "toplevel_python_sources",
    srcs = glob(["*.py"]),
    visibility = ["//visibility:public"],
)

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
        # models/apps.py must be in runfiles or ModelsConfig.ready() never
        # runs in the sandbox — any model missing from the wrapper's explicit
        # import list is then invisible to the autodetector (phantom-0050).
        "//models:apps",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models:salary",
        "//models:i129",
        "//models:uscis_employer",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//models:vqs",
        "//models:blog",
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
    name = "run_sql",
    srcs = ["run_sql.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models:bulletin",
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
    name = "test_url_discovery",
    srcs = ["test_url_discovery.py"],
    main = "test_url_discovery.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
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
    name = "clean_bad_datasources",
    srcs = ["clean_bad_datasources.py"],
    main = "clean_bad_datasources.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
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
        "//django_config:logging_config",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("redis"),  # Django Redis cache backend when REDIS_URL is set
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "import_visa_bulletin_data",
    srcs = ["import_visa_bulletin_data.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//models/enums:action_type",
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
    name = "benchmark_fenced_queries",
    srcs = ["benchmark_fenced_queries.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        "//models:salary",
        "//lib/utils:filter_utils",
        "//lib/utils:logging_utils",
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
    name = "smoke_check_production",
    srcs = ["smoke_check_production.py"],
    main = "smoke_check_production.py",
    visibility = ["//visibility:public"],
    deps = [],
    python_version = "PY3",
)

# investigate_salary_issues target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# investigate_validation_issues target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data

# investigate_null_salaries target removed - functionality merged into //scripts/salary:validate_data
# Use: bazel run //scripts/salary:validate_data -- --check-incomplete-records

py_binary(
    name = "vqs_backtest",
    srcs = ["vqs_backtest.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/business/vqs:accuracy_metrics",
        "//lib/business/vqs:meta_params",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:country",
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
    name = "ingest_i485_inventory",
    srcs = ["ingest_i485_inventory.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:raw_facts",
        "//models/enums:country",
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
    name = "ingest_dos_issuance",
    srcs = ["ingest_dos_issuance.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:raw_facts",
        "//models/enums:country",
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
    name = "ingest_perm_disclosure",
    srcs = ["ingest_perm_disclosure.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:raw_facts",
        "//models/enums:country",
        "//lib/parsing/salary:db_importer",
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
    name = "test_plugins",
    srcs = ["test_plugins.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:enums",
        requirement("Django"),
    ],
    data = ["//data/sources:sample_data"],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "ingest_vqs_supply",
    srcs = ["ingest_vqs_supply.py"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/ingest:registry",
        "//lib/ingest:orchestrator",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:enums",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)



py_binary(
    name = "publish_predictions",
    srcs = ["publish_predictions.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:aggregator",
        "//lib/business/vqs:calibration",
        "//lib/business/vqs:expert_pool",
        "//lib/business/vqs:gbm_expert",
        "//lib/business/vqs:meta_params",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:october_reset",
        "//models:vqs",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models/enums:country",
        "//models/enums:family_preference",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# Importable form of the binary above, for callers that need the module rather
# than the entrypoint (scripts/cron/refresh_bulletin.py:217 imports
# publish_predictions() directly). Same `_lib` pattern as :refresh_bulletin_lib.
py_library(
    name = "publish_predictions_lib",
    srcs = ["publish_predictions.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:aggregator",
        "//lib/business/vqs:calibration",
        "//lib/business/vqs:expert_pool",
        "//lib/business/vqs:gbm_expert",
        "//lib/business/vqs:meta_params",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:october_reset",
        "//models:vqs",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models/enums:country",
        "//models/enums:family_preference",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
)

py_binary(
    name = "debug_predictions_db",
    srcs = ["debug_predictions_db.py"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:vqs",
        "//models/enums:country",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
py_binary(
    name = "check_coverage",
    srcs = ["check_coverage.py"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:bulletin",
        "//models:vqs",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
