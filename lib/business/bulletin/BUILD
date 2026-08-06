# Build file for bulletin business logic package
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Consumed as data by //tests:test_chart_space_reservation_guard, which reads the
# rendered chart height as source text rather than importing plotly.
exports_files(["chart_builder.py"])

py_library(
    name = "cutoff_projection",
    srcs = ["cutoff_projection.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "release_schedule",
    srcs = ["release_schedule.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:bulletin",
        requirement("python-dateutil"),
    ],
)

py_library(
    name = "chart_builder",
    srcs = ["chart_builder.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:country",
        "//models/enums:cutoff_state",
        requirement("plotly"),
    ],
)

py_library(
    name = "visa_class_utils",
    srcs = ["visa_class_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:visa_cutoff_date",
        "//models/enums:employment_preference",
    ],
)

py_library(
    name = "cutoff_data_aggregator",
    srcs = ["cutoff_data_aggregator.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":cutoff_projection",
        ":visa_class_utils",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:cutoff_state",
        "//models/enums:employment_preference",
        "//models/enums:family_preference",
        "//models/enums:visa_category",
        requirement("Django"),
    ],
)












py_library(
    name = "wayback",
    srcs = ["wayback.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("requests"),
    ],
)
