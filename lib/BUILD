# Build file for lib package
# Main BUILD file - subdirectories have their own BUILD files

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Legacy salary_import.py (kept for backwards compatibility)
# New code should use lib/parsing/salary/db_importer.py
py_library(
    name = "salary_import",
    srcs = ["salary_import.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/parsing/salary:wage_unit_correction",
        requirement("Django"),
        requirement("pandas"),
        requirement("openpyxl"),
    ],
)
