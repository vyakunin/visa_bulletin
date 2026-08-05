load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "ingest_uscis_i140",
    srcs = ["ingest_uscis_i140.py"],
    main = "ingest_uscis_i140.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "compute_perm_lag",
    srcs = ["compute_perm_lag.py"],
    main = "compute_perm_lag.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//models:salary",
        "//models/enums:case_status",
        "//models/enums:country",
        "//models/enums:visa_program",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "run_simulation",
    srcs = ["run_simulation.py"],
    main = "run_simulation.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/utils:logging_utils",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "run_backtest",
    srcs = ["run_backtest.py"],
    main = "run_backtest.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "download_uscis_i140",
    srcs = ["download_uscis_i140.py"],
    main = "download_uscis_i140.py",
    visibility = ["//visibility:public"],
    deps = [
        ":ingest_uscis_i140",
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("requests"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_publish_dispatch",
    srcs = ["backtest_publish_dispatch.py"],
    main = "backtest_publish_dispatch.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:gbm_expert",
        "//lib/utils:logging_utils",
        "//scripts:publish_predictions",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "compute_prediction_accuracy",
    srcs = ["compute_prediction_accuracy.py"],
    main = "compute_prediction_accuracy.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:accuracy_metrics",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/business/vqs:metric_config",
        "//lib/utils:logging_utils",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("plotly"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "evaluate_model",
    srcs = ["evaluate_model.py"],
    main = "evaluate_model.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:direction_metrics",
        "//lib/business/vqs:estimators",
        "//lib/business/vqs:gbm_expert",
        "//lib/business/vqs:metric_config",
        "//lib/business/vqs:prediction_loader",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/business/vqs:regime",
        "//lib/business/vqs:seasonal_predictor",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "analyze_fy_transitions",
    srcs = ["analyze_fy_transitions.py"],
    main = "analyze_fy_transitions.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:fy_utilization",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_fy_boundary",
    srcs = ["backtest_fy_boundary.py"],
    main = "backtest_fy_boundary.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/business/vqs:data_cache",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_october_reset",
    srcs = ["backtest_october_reset.py"],
    main = "backtest_october_reset.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:october_reset",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_interval_coverage",
    srcs = ["backtest_interval_coverage.py"],
    main = "backtest_interval_coverage.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:interval_coverage",
        "//models:visa_cutoff_date",
        "//models:vqs",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_trajectory",
    srcs = ["backtest_trajectory.py"],
    main = "backtest_trajectory.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:metric_config",
        "//lib/business/vqs:seasonal_predictor",
        "//lib/business/vqs:solver",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_selector",
    srcs = ["backtest_selector.py"],
    main = "backtest_selector.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:expert_pool",
        "//lib/business/vqs:metric_config",
        "//lib/business/vqs:prediction_loader",
        "//lib/business/vqs:regime",
        "//lib/business/vqs:seasonal_predictor",
        "//lib/business/vqs:solver",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backtest_experts",
    srcs = ["backtest_experts.py"],
    main = "backtest_experts.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//lib/business/vqs:data_cache",
        "//lib/business/vqs:expert_pool",
        "//lib/business/vqs:regime",
        "//lib/business/vqs:seasonal_predictor",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "generate_metric_report",
    srcs = ["generate_metric_report.py"],
    main = "generate_metric_report.py",
    visibility = ["//visibility:public"],
    deps = [
        ":evaluate_model",
        "//django_config:logging_config",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
        requirement("python-dateutil"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "download_uscis_i485",
    srcs = ["download_uscis_i485.py"],
    main = "download_uscis_i485.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("openpyxl"),
        requirement("requests"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "ingest_perm_supply",
    srcs = ["ingest_perm_supply.py"],
    main = "ingest_perm_supply.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:ingest_utils",
        "//lib/parsing/salary:db_importer",
        "//lib/utils:logging_utils",
        "//models:raw_facts",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "tune_params",
    srcs = ["tune_params.py"],
    main = "tune_params.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:accuracy_metrics",
        "//lib/business/vqs:contextual_aggregator",
        "//lib/business/vqs:aggregator",
        "//lib/business/vqs:gbm_expert",
        "//lib/business/vqs:meta_params",
        "//lib/business/vqs:metric_config",
        "//lib/business/vqs:data_cache",
        "//webapp:apps",
        requirement("Django"),
        requirement("lightgbm"),
        requirement("optuna"),
        requirement("scikit_learn"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
