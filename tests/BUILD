# Build file for tests

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_test(
    name = "test_parser",
    srcs = [
        "__init__.py",
        "test_parser.py",
    ],
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        "//lib:bulletint_parser",
        "//lib:table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

