# BUILD file for Django configuration

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "logging_config",
    srcs = ["logging_config.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "settings",
    srcs = ["settings.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":logging_config",
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

py_library(
    name = "context_processors",
    srcs = ["context_processors.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":settings",
        requirement("Django"),
    ],
)

