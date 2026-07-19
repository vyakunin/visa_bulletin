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
    name = "i129",
    srcs = ["i129.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":salary",  # EmployerCluster FK target (imported for FK registration)
        "//models/enums:visa_program",
        "//models/ingest:ingest_version",
        requirement("Django"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
)

py_library(
    name = "uscis_employer",
    srcs = ["uscis_employer.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":salary",  # EmployerCluster FK target (imported for FK registration)
        "//models/ingest:ingest_version",
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
        "//models/enums:action_type",
        # visa_cutoff_date.py imports this directly. It was missing here and only
        # ever resolved because every consumer so far also pulled in the full
        # webapp dep closure; a narrower binary (//scripts/seo:render_sitemap)
        # surfaced it as ModuleNotFoundError. Found 2026-07-19.
        "//models/enums:visa_category",
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

py_library(
    name = "raw_facts",
    srcs = ["raw_facts.py"],
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


py_library(
    name = "vqs",
    srcs = ["vqs.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
)

py_library(
    name = "blog",
    srcs = ["blog.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":bulletin",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
)

