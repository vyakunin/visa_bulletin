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
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

py_library(
    name = "bulletin",
    srcs = ["bulletin.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

py_library(
    name = "visa_cutoff_date",
    srcs = ["visa_cutoff_date.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":bulletin",
        "//models/ingest:ingest_version",
        requirement("Django"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

py_library(
    name = "salary",
    srcs = ["salary.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":job_title",
        "//lib/business/salary:generic_words",
        "//models/enums:visa_program",
        "//models/ingest:ingest_version",
        requirement("Django"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

py_library(
    name = "job_title",
    srcs = ["job_title.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

filegroup(
    name = "migrations",
    srcs = glob(["migrations/*.py"]) + ["//models/ingest:migrations"],
    visibility = ["//visibility:public"],
)

# Ingest models (targets are in models/ingest/BUILD)

