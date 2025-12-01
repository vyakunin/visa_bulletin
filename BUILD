# Root BUILD file

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "requirements.txt",
])

py_binary(
    name = "refresh_data",
    srcs = ["refresh_data.py"],
    deps = [
        "//lib:bulletint_parser",
        "//lib:publication_data",
        requirement("requests"),
    ],
    python_version = "PY3",
)

