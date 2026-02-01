load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "warm_cache",
    srcs = ["warm_cache.py"],
    main = "warm_cache.py",
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:salary",
        "//models:job_title",
        "//models/enums:visa_program",
        "//lib/business/salary:market_overview",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    visibility = ["//visibility:public"],
)
