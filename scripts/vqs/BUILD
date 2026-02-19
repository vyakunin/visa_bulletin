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
    name = "compute_prediction_accuracy",
    srcs = ["compute_prediction_accuracy.py"],
    main = "compute_prediction_accuracy.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/vqs:accuracy_metrics",
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
