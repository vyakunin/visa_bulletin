# Build file for lib package
# Main BUILD file - subdirectories have their own BUILD files

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Top-level bulletin_parser (imports from lib.parsing.bulletin)

py_library(
    name = "bulletin_parser",
    srcs = ["bulletin_parser.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/parsing/bulletin:bulletin_table",
        "//models/enums:family_preference",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)
