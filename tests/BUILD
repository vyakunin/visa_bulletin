load("@rules_python//python:defs.bzl", "py_library", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
load(":django_test.bzl", "django_py_test")

py_library(
    name = "django_setup",
    srcs = ["django_setup.py", "ensure_test_db.py"],
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
)

py_test(
    name = "test_supply",
    srcs = ["test_supply.py"],
    deps = [
        "//lib/business/vqs/supply",
        "//models/enums:country",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    tags = ["manual"],
)

py_test(
    name = "test_url_utils",
    srcs = ["test_url_utils.py"],
    deps = [
        "//lib/utils:url_utils",
    ],
)

py_test(
    name = "test_refresh_checkpoint",
    srcs = ["test_refresh_checkpoint.py"],
    deps = [
        "//scripts/cron/refresh:checkpoint",
        requirement("pytest"),
    ],
)

py_test(
    name = "test_refresh_config",
    srcs = ["test_refresh_config.py"],
    deps = [
        "//scripts/cron/refresh:config",
        requirement("pytest"),
    ],
)

py_test(
    name = "test_refresh_pipeline",
    srcs = ["test_refresh_pipeline.py"],
    deps = [
        "//scripts/cron/refresh:pipeline",
        "//scripts/cron/refresh:runner",
        "//scripts/cron/refresh:checkpoint",
        "//scripts/cron/refresh:config",
        requirement("pytest"),
    ],
)

py_test(
    name = "test_refresh_steps",
    srcs = ["test_refresh_steps.py"],
    deps = [
        "//scripts/cron/refresh:steps",
        "//scripts/cron/refresh:runner",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:services",
        requirement("pytest"),
    ],
)

py_test(
    name = "test_refresh_orchestrate",
    srcs = ["test_refresh_orchestrate.py"],
    deps = [
        "//scripts/cron/refresh:orchestrate",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:instance",
        requirement("pytest"),
    ],
)

django_py_test(
    name = "test_job_title_normalization",
    srcs = ["test_job_title_normalization.py"],
    deps = [
        "//models:job_title",
    ],
)

py_test(
    name = "test_refresh_instance",
    srcs = ["test_refresh_instance.py"],
    deps = [
        "//scripts/cron/refresh:instance",
        requirement("pytest"),
    ],
)
