# Build file for salary parsing package
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "wage_unit_correction",
    srcs = ["wage_unit_correction.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:bazel_runfiles",
        "//lib/utils:rate_limited_logger",
        "//models/enums:visa_program",
        requirement("pyyaml"),
    ],
    data = [
        ":wage_thresholds_config.yaml",
    ],
)

exports_files(["wage_thresholds_config.yaml"])

py_library(
    name = "db_importer",
    srcs = ["db_importer.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/parsing/salary:wage_unit_correction",
        "//lib/utils:data_source_utils",
        "//lib/utils:location_utils",
        requirement("Django"),
        requirement("pandas"),
        requirement("openpyxl"),
    ],
)

py_library(
    name = "file_detection",
    srcs = ["file_detection.py"],
    visibility = ["//visibility:public"],
)
