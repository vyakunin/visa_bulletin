load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "__init__",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "retention",
    srcs = ["retention.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:action_type",
        "//models/enums:country",
    ],
)

py_library(
    name = "dashboard",
    srcs = ["dashboard.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":prediction_month_forecast",
        ":priority_date_landing",
        ":retention",
        "//django_config:cache_utils",
        "//lib/business/bulletin:chart_builder",
        "//lib/business/bulletin:cutoff_data_aggregator",
        "//lib/business/vqs:coupling",
        "//lib/business/vqs:solver",
        "//models:blog",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:visa_category",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
)

py_library(
    name = "vqs_api",
    srcs = ["vqs_api.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/vqs:solver",
        "//models/enums:country",
        requirement("Django"),
    ],
)

py_library(
    name = "priority_date_landing",
    srcs = ["priority_date_landing.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/bulletin:cutoff_data_aggregator",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:employment_preference",
        requirement("Django"),
    ],
)

py_library(
    name = "priority_date_rollup",
    srcs = ["priority_date_rollup.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":priority_date_landing",
        "//models:bulletin",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("Django"),
    ],
)

py_library(
    name = "priority_date_calculator",
    srcs = ["priority_date_calculator.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:employment_preference",
        "//models/enums:family_preference",
        "//models/enums:visa_category",
        requirement("Django"),
    ],
)

py_library(
    name = "prediction_month_forecast",
    srcs = ["prediction_month_forecast.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":retention",
        "//django_config:cache_utils",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:vqs",
        "//models/enums:country",
        "//models/enums:family_preference",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
)
