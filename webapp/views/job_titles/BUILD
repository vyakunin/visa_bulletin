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
        "//lib/utils:pagination",
        "//models:job_title",
        requirement("Django"),
    ],
)

py_library(
    name = "profile",
    srcs = ["profile.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/salary:h1b_sponsors",
        "//lib/business/salary:job_title_chart_builder",
        "//lib/business/salary:job_title_stats",
        "//models:job_title",
        requirement("Django"),
    ],
)
