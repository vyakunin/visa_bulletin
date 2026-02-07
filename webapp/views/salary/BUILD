load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "search",
    srcs = ["search.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/salary:common_chart_builder",
        "//lib/business/salary:market_overview",
        "//lib/utils:filter_utils",
        "//lib/utils:location_utils",
        "//lib/utils:pagination",
        "//models:salary",
        "//webapp:forms",
        requirement("Django"),
    ],
)
