load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "backtest_projections",
    srcs = ["backtest_projections.py"],
    main = "backtest_projections.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//models/enums:action_type",
        "//models/enums:visa_category",
        "//models/enums:employment_preference",
        "//lib/business/bulletin:cutoff_projection",
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
