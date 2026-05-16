load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")



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

py_library(
    name = "by_state",
    srcs = ["by_state.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/salary:common_stats",
        "//lib/utils:location_utils",
        "//models:salary",
        requirement("Django"),
    ],
)
