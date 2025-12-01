# Build file for lib package

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "lib",
    srcs = [
        "__init__.py",
        "bulletint_parser.py",
        "publication_data.py",
        "table.py",
    ],
    visibility = ["//visibility:public"],
    deps = [
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

py_library(
    name = "bulletint_parser",
    srcs = ["bulletint_parser.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

py_library(
    name = "publication_data",
    srcs = ["publication_data.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "table",
    srcs = ["table.py"],
    visibility = ["//visibility:public"],
)

