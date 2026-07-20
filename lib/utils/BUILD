# Build file for utils package
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Standard Bazel runfiles library for accessing data dependencies
# This is provided by rules_python and handles cross-platform runfiles access

py_library(
    name = "http_utils",
    srcs = ["http_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("requests"),
    ],
)

py_library(
    name = "logging_utils",
    srcs = ["logging_utils.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "cache_utils",
    srcs = ["cache_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
    ],
)

py_library(
    name = "location_utils",
    srcs = ["location_utils.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "url_utils",
    srcs = ["url_utils.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "pagination",
    srcs = ["pagination.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "filter_utils",
    srcs = ["filter_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:visa_program",
        requirement("Django"),
    ],
)

py_library(
    name = "db_utils",
    srcs = ["db_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/salary:cluster_utils",
        "//models:salary",
        requirement("Django"),
    ],
)

py_library(
    name = "validation_utils",
    srcs = ["validation_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//lib/utils:location_utils",
        requirement("Django"),
    ],
)

py_library(
    name = "bazel_runfiles",
    srcs = ["bazel_runfiles.py"],
    visibility = ["//visibility:public"],
    deps = [
        "@rules_python//python/runfiles:runfiles",  # Standard Bazel runfiles library
    ],
)

py_library(
    name = "rate_limited_logger",
    srcs = ["rate_limited_logger.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "data_source_utils",
    srcs = ["data_source_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":excel_utils",
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
    ],
)

py_library(
    name = "exception_utils",
    srcs = ["exception_utils.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "excel_utils",
    srcs = ["excel_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("openpyxl"),
    ],
)

py_library(
    name = "import_completeness",
    srcs = ["import_completeness.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/parsing/salary:file_detection",
        "//lib/utils:data_source_utils",
        "//models:salary",
        requirement("Django"),
    ],
)
