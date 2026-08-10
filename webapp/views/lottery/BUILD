load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "h1b_lottery",
    srcs = ["h1b_lottery.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//django_config:cache_utils",
        "//lib/business/i129:lottery_season",
        requirement("Django"),
    ],
)
