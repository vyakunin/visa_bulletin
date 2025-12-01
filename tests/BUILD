# Build file for tests
# Following rule: One Bazel target per file
# Tests use pytest format but work with Bazel py_test

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_test(
    name = "test_parser",
    srcs = ["test_parser.py"],
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

py_test(
    name = "test_extractor",
    srcs = ["conftest.py", "test_extractor.py"],
    main = "test_extractor.py",
    deps = [
        "//lib:table",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//extractors:bulletin_extractor",
        "//django_config:settings",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("Django"),
        requirement("pytest"),
        requirement("pytest-django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_integration",
    srcs = ["conftest.py", "test_integration.py"],
    main = "test_integration.py",
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        "//lib:bulletint_parser",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//extractors:bulletin_handler",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("Django"),
        requirement("beautifulsoup4"),
        requirement("pytest"),
        requirement("pytest-django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


