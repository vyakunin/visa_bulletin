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
        "//webapp/views/seo:jsonld",
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
        "//lib/business/salary:h1b_sponsors",
        "//lib/utils:location_utils",
        "//models:salary",
        requirement("Django"),
    ],
)

py_library(
    name = "h1b_sponsors",
    srcs = ["h1b_sponsors.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/salary:common_stats",
        "//lib/business/salary:h1b_sponsors",
        "//lib/utils:location_utils",
        "//models:job_title",
        requirement("Django"),
    ],
)
