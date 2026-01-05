# BUILD file for ingest models package

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "enums",
    srcs = ["enums.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
    ],
)

py_library(
    name = "data_source",
    srcs = ["data_source.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":enums",
        requirement("Django"),
    ],
)

py_library(
    name = "ingest_run",
    srcs = ["ingest_run.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_source",
        ":enums",
        requirement("Django"),
    ],
)

py_library(
    name = "ingest_version",
    srcs = ["ingest_version.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":ingest_run",
        requirement("Django"),
    ],
)

py_library(
    name = "ingest",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_source",
        ":ingest_run",
        ":ingest_version",
        ":enums",
    ],
)

filegroup(
    name = "migrations",
    srcs = glob(["migrations/*.py"]),
    visibility = ["//visibility:public"],
)










