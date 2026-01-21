load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "dashboard",
    srcs = ["dashboard.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/bulletin:chart_builder",
        "//lib/business/bulletin:cutoff_data_aggregator",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:visa_category",
        requirement("Django"),
    ],
)
