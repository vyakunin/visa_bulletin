# BUILD file for extractors
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "bulletin_extractor",
    srcs = ["bulletin_extractor.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
    ],
)

py_library(
    name = "bulletin_handler",
    srcs = ["bulletin_handler.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":bulletin_extractor",
        "//lib:bulletint_parser",
        "//lib:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        requirement("Django"),
    ],
)


