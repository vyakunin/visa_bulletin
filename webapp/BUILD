load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "apps",
    srcs = ["apps.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
    ],
)

py_library(
    name = "urls",
    srcs = ["urls.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":views",
        requirement("Django"),
    ],
)

py_library(
    name = "views",
    srcs = ["views.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//lib:chart_builder",
        "//lib:dashboard_service",
        requirement("Django"),
    ],
)

filegroup(
    name = "templates",
    srcs = glob(["templates/**/*.html"]),
    visibility = ["//visibility:public"],
)

