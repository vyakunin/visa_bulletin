# Root BUILD file

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "requirements.txt",
])

py_binary(
    name = "refresh_data",
    srcs = ["refresh_data.py"],
    deps = [
        "//lib:bulletint_parser",
        "//lib:publication_data",
        "//lib:table",
        "//extractors:bulletin_handler",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
        requirement("requests"),
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
        requirement("idna"),
        requirement("urllib3"),
        requirement("certifi"),
        requirement("charset-normalizer"),
        requirement("typing-extensions"),
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
    name = "refresh_data_incremental",
    srcs = ["refresh_data_incremental.py"],
    deps = [
        "//lib:bulletint_parser",
        "//lib:publication_data",
        "//lib:table",
        "//extractors:bulletin_handler",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
        requirement("requests"),
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
        requirement("idna"),
        requirement("urllib3"),
        requirement("certifi"),
        requirement("charset-normalizer"),
        requirement("typing-extensions"),
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
    name = "runserver",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["runserver", "8000", "--noreload"],
    data = [
        "//webapp:templates",
        "visa_bulletin.db",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:urls",
        "//webapp:apps",
        "//webapp:views",
        "//webapp:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("Django"),
        requirement("plotly"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("tenacity"),
        requirement("narwhals"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "migrate",
    srcs = ["manage.py"],
    main = "manage.py",
    args = ["migrate"],
    data = [
        "visa_bulletin.db",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//django_config:urls",
        "//webapp:apps",
        "//webapp:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

