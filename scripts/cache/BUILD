load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "inspect_cache",
    srcs = ["inspect_cache.py"],
    main = "inspect_cache.py",
    deps = [
        "//django_config:settings",
        "//webapp:apps",
        "//models:bulletin",
        "//models:salary",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("redis"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    visibility = ["//visibility:public"],
)

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
        "//lib/business/salary:common_stats",
        "//lib/business/salary:h1b_salary_pair",
        "//lib/business/salary:h1b_sponsors",
        "//lib/business/salary:market_overview",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("redis"),  # Django Redis cache backend when REDIS_URL/CACHE is Redis
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    visibility = ["//visibility:public"],
)

py_binary(
    name = "warm_profiles",
    srcs = ["warm_profiles.py"],
    main = "warm_profiles.py",
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp/views/employers:profile",
        "//webapp/views/salary:by_state",
        "//lib/utils:location_utils",
        "//models:salary",
        "//models:job_title",
        "//lib/business/salary:employer_stats",
        "//lib/business/salary:h1b_salary_pair",
        "//lib/business/salary:h1b_sponsors",
        "//lib/business/salary:job_title_stats",
        "//lib/business/salary:precomputed_profiles",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("redis"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    visibility = ["//visibility:public"],
)

# Library form so //tests:test_precomputed_profiles can import the warmer.
py_library(
    name = "warm_profiles_lib",
    srcs = ["warm_profiles.py"],
    deps = [
        "//django_config:logging_config",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp/views/employers:profile",
        "//webapp/views/salary:by_state",
        "//lib/utils:location_utils",
        "//models:salary",
        "//models:job_title",
        "//lib/business/salary:employer_stats",
        "//lib/business/salary:h1b_salary_pair",
        "//lib/business/salary:h1b_sponsors",
        "//lib/business/salary:job_title_stats",
        "//lib/business/salary:precomputed_profiles",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("redis"),
    ],
    visibility = ["//visibility:public"],
)
