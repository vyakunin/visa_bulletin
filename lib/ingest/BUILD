# BUILD file for ingest pipeline framework

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "base",
    srcs = ["base.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
        "//models/ingest:enums",
        requirement("Django"),
    ],
)

py_library(
    name = "registry",
    srcs = ["registry.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":base",
        "//models/ingest:enums",
    ],
)

py_library(
    name = "rejection_tracker",
    srcs = ["rejection_tracker.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/ingest:ingest_run",
        "//models/ingest:rejection_stats",
    ],
)

py_library(
    name = "schema",
    srcs = ["schema.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "orchestrator",
    srcs = ["orchestrator.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":base",
        ":registry",
        ":rejection_tracker",
        ":schema",
        ":versioning",  # For create_version, activate_version
        "//lib/utils:rate_limited_logger",
        "//lib/utils:data_source_utils",
        "//lib/utils:exception_utils",  # For UNRECOVERABLE_ERRORS
        "//models/ingest:data_source",
        "//models/ingest:ingest_run",
        "//models/ingest:ingest_version",
        "//models/ingest:enums",
        "//models:salary",
        "//models:visa_cutoff_date",
        requirement("Django"),
    ],
)

py_library(
    name = "versioning",
    srcs = ["versioning.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/ingest:ingest_version",
        "//models:salary",
        "//models:visa_cutoff_date",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("Django"),
    ],
)

py_library(
    name = "ingest",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":base",
        ":registry",
        ":orchestrator",
        ":versioning",
        ":schema",
    ],
)

