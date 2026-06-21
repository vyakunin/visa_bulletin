load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "pages",
    srcs = ["pages.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/bulletin:release_schedule",
        requirement("Django"),
    ],
)
