load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "directory",
    srcs = ["directory.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/utils:location_utils",
        "//lib/utils:pagination",
        "//models/enums:visa_program",
        "//models:salary",
        "//webapp/views/seo:jsonld",
        requirement("Django"),
    ],
)

py_library(
    name = "profile",
    srcs = ["profile.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/i129:approval_stats",
        "//lib/business/i129:pay_comparison",
        "//lib/business/salary:common_stats",
        "//lib/business/salary:common_chart_builder",
        "//lib/business/salary:slug_redirects",
        "//models/enums:visa_program",
        "//models:job_title",
        "//models:salary",
        requirement("Django"),
    ],
)

py_library(
    name = "rankings",
    srcs = ["rankings.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//models/enums:visa_program",
        "//models:salary",
        requirement("Django"),
    ],
)
