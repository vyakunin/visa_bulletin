# Build file for tests
# Following rule: One Bazel target per file
# Tests use pytest format but work with Bazel py_test

load("@rules_python//python:defs.bzl", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "test_salary_data.csv",
])

py_test(
    name = "test_parser",
    size = "small",
    srcs = ["test_parser.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:bulletin_table",
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
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        "//lib/parsing/bulletin:bulletin_table",
        "//lib/parsing/bulletin:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//lib/parsing/bulletin:table_to_cutoff_data",
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
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//lib/parsing/bulletin:db_importer",
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
        "//lib/business/bulletin:cutoff_projection",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_chart_builder",
    size = "small",
    srcs = ["test_chart_builder.py"],
    deps = [
        "//lib/business/bulletin:chart_builder",
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
        "//lib/business/bulletin:visa_class_utils",
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

py_test(
    name = "test_salary",
    size = "small",
    srcs = ["test_salary.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",  # Required for IngestVersion ForeignKey resolution
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
    name = "test_salary_import",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_salary_import.py"],
    main = "test_salary_import.py",
    data = [
        ":test_salary_data.csv",
    ],
    deps = [
        "//lib/parsing/salary:db_importer",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
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
    name = "test_ingest_integration",
    size = "medium",
    srcs = ["django_setup.py", "conftest.py", "test_ingest_integration.py"],
    main = "test_ingest_integration.py",
    deps = [
        "//lib/ingest:ingest",
        "//lib/ingest:orchestrator",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:ingest",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("pytest"),
        requirement("pytest-django"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_salary_real_data",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_salary_real_data.py"],
    main = "test_salary_real_data.py",
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp:views",
        "//webapp:urls",
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
    name = "test_ingest_models",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_ingest_models.py"],
    main = "test_ingest_models.py",
    deps = [
        "//models/ingest:ingest",
        "//models/ingest:enums",
        "//django_config:settings",
        "//webapp:apps",
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
    name = "test_ingest_plugins",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_ingest_plugins.py"],
    main = "test_ingest_plugins.py",
    deps = [
        "//lib/ingest:base",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//models/ingest:ingest",
        "//models/ingest:enums",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("pytest"),
        requirement("pytest-django"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_ingest_versioning",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_ingest_versioning.py"],
    main = "test_ingest_versioning.py",
    deps = [
        "//lib/ingest:versioning",
        "//models/ingest:ingest",
        "//models:salary",
        "//models:visa_cutoff_date",
        "//django_config:settings",
        "//webapp:apps",
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

