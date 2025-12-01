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

