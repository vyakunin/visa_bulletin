# BUILD file for models package
# Following rule: One Bazel target per file

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
    name = "bulletin",
    srcs = ["bulletin.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
    ],
)

py_library(
    name = "visa_cutoff_date",
    srcs = ["visa_cutoff_date.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":bulletin",
        requirement("Django"),
    ],
)

