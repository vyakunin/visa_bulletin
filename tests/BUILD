# Build file for tests
# Following rule: One Bazel target per file
# Tests use pytest format but work with Bazel py_test

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_test(
    name = "test_parser",
    size = "small",
    srcs = ["test_parser.py"],
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        "//lib:bulletin_parser",
        "//lib:table",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_extractor",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_extractor.py"],
    main = "test_extractor.py",
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        "//lib:table",
        "//lib:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//extractors:bulletin_extractor",
        "//django_config:settings",
        "//webapp:apps",
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
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_integration.py"],
    main = "test_integration.py",
    data = [
        "//saved_pages:test_data",
    ],
    deps = [
        "//lib:bulletin_parser",
        "//lib:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//extractors:bulletin_handler",
        "//django_config:settings",
        "//webapp:apps",
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

py_test(
    name = "test_projection",
    size = "small",
    srcs = ["test_projection.py"],
    deps = [
        "//lib:projection",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_chart_builder",
    size = "small",
    srcs = ["test_chart_builder.py"],
    deps = [
        "//lib:chart_builder",
        "//models/enums:country",
        requirement("Django"),
        requirement("plotly"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_webapp_ui",
    size = "small",
    srcs = ["django_setup.py", "test_webapp_ui.py"],
    deps = [
        "//webapp:views",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_employment_preference",
    size = "small",
    srcs = ["test_employment_preference.py"],
    deps = [
        "//models/enums:employment_preference",
        requirement("Django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_visa_class_utils",
    size = "small",
    srcs = ["django_setup.py", "test_visa_class_utils.py"],
    deps = [
        "//lib:visa_class_utils",
        "//models:visa_cutoff_date",
        "//models:bulletin",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:family_preference",
        "//models/enums:employment_preference",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_dashboard_integration",
    size = "small",
    srcs = ["django_setup.py", "test_dashboard_integration.py"],
    deps = [
        "//webapp:views",
        "//models:visa_cutoff_date",
        "//models:bulletin",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//django_config:settings",
        "//django_config:urls",
        "//webapp:apps",
        "//webapp:urls",
        requirement("Django"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


