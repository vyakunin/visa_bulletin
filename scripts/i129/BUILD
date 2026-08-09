load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "backfill_employer_links",
    srcs = ["backfill_employer_links.py"],
    main = "backfill_employer_links.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/i129:employer_linker",
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
    name = "warm_demographic_pay",
    srcs = ["warm_demographic_pay.py"],
    main = "warm_demographic_pay.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/business/i129:demographic_pay_panel",
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
