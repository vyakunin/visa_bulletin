load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "check_migrations",
    srcs = ["check_migrations.py"],
    main = "check_migrations.py",
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:settings",
        "//models:salary",
        "//models:bulletin",
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









