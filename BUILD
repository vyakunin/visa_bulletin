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

