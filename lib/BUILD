# Build file for lib package
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# One target per file for better granularity and incremental builds

py_library(
    name = "table",
    srcs = ["table.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "publication_data",
    srcs = ["publication_data.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "bulletint_parser",
    srcs = ["bulletint_parser.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

