# Build file for bulletin parsing package
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "bulletin_table",
    srcs = ["bulletin_table.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "publication_data",
    srcs = ["publication_data.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "parser",
    srcs = ["parser.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":bulletin_table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

py_library(
    name = "table_to_cutoff_data",
    srcs = ["table_to_cutoff_data.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":publication_data",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
    ],
)

py_library(
    name = "db_importer",
    srcs = ["db_importer.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":table_to_cutoff_data",
        ":parser",
        ":publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        requirement("Django"),
    ],
)











