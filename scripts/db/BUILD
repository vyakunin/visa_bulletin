# Build file for database maintenance scripts
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "audit_indexes",
    srcs = ["audit_indexes.py"],
    main = "audit_indexes.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//lib/utils:index_audit",
        "//lib/utils:logging_utils",
        "//models:salary",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("psycopg2_binary"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
