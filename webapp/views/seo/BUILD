load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "jsonld",
    srcs = ["jsonld.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "sitemaps",
    srcs = ["sitemaps.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/salary:h1b_salary_pair",
        "//lib/business/salary:h1b_sponsors",
        "//lib/business/salary:job_title_stats",
        "//lib/business/salary:occupation_stats",
        "//lib/utils:location_utils",
        "//models:blog",
        "//models:bulletin",
        "//models/enums:country",
        "//models:job_title",
        "//models:salary",
        "//webapp/views/bulletin:prediction_month_forecast",
        requirement("Django"),
    ],
)
