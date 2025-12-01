# BUILD file for Django configuration

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "settings",
    srcs = ["settings.py"],
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
        "//webapp:urls",
        requirement("Django"),
    ],
)

