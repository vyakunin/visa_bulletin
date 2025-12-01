# Build file for tests
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_test(
    name = "test_parser",
    srcs = ["test_parser.py"],
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        # Only depend on what we actually need (one target per file)
        "//lib:bulletint_parser",
        "//lib:table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_enums",
    srcs = ["test_enums.py"],
    deps = [
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:family_preference",
        "//models/enums:employment_preference",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

