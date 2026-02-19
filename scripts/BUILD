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
        "//models:raw_facts",
        "//models:salary",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//models:vqs",
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
    name = "vqs_error_analysis",
    srcs = ["vqs_error_analysis.py"],
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
    name = "vqs_tune_systemic",
    srcs = ["vqs_tune_systemic.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//scripts:vqs_backtest",
        "//scripts:vqs_error_analysis",
        "//lib/business/vqs:meta_params",
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
    name = "vqs_debug_fixes",
    srcs = ["vqs_debug_fixes.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:meta_params",
        "//models:visa_cutoff_date",
        "//models:bulletin",
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
        "//lib/business/vqs:meta_params",
        "//lib/business/vqs:data_cache",
        "//models:vqs",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models/enums:country",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
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
