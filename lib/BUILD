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
    name = "projection",
    srcs = ["projection.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "chart_builder",
    srcs = ["chart_builder.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:country",
        requirement("plotly"),
    ],
)

py_library(
    name = "visa_class_utils",
    srcs = ["visa_class_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "publication_data",
    srcs = ["publication_data.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "bulletin_parser",
    srcs = ["bulletin_parser.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

py_library(
    name = "dashboard_service",
    srcs = ["dashboard_service.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":projection",
        ":visa_class_utils",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:employment_preference",
        "//models/enums:family_preference",
        "//models/enums:visa_category",
    ],
)

