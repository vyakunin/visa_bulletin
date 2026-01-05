# Build file for tests
# Following rule: One Bazel target per file
# Tests use pytest format but work with Bazel py_test

load("@rules_python//python:defs.bzl", "py_library", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "test_salary_data.csv",
])

# Shared Django setup library - used by multiple test targets
py_library(
    name = "django_setup",
    srcs = ["django_setup.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
        "//django_config:settings",
    ],
)

py_test(
    name = "test_wage_unit_parsing",
    size = "small",
    srcs = ["test_wage_unit_parsing.py"],
    deps = [
        "//models/enums:visa_program",
        "//lib/parsing/salary:wage_unit_correction",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

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
    name = "test_country_header_parsing",
    size = "small",
    srcs = ["django_setup.py", "test_country_header_parsing.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:table_to_cutoff_data",
        "//lib/parsing/bulletin:publication_data",
        "//models/enums:country",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
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
        "//lib/utils:location_utils",
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",  # Required for IngestVersion ForeignKey resolution
        "//lib/parsing/salary:wage_unit_correction",
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
        "//lib/ingest/plugins:dol_perm",
        "//models/ingest:ingest",
        "//models/ingest:enums",
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
)

py_test(
    name = "test_worksite_record",
    size = "small",
    srcs = ["django_setup.py", "test_worksite_record.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
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
    name = "test_lca_plugin",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_lca_plugin.py"],
    main = "test_lca_plugin.py",
    deps = [
        "//lib/ingest:base",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/parsing/salary:file_detection",
        "//models/ingest:ingest",
        "//models/ingest:enums",
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

py_test(
    name = "test_validation",
    size = "small",
    srcs = ["django_setup.py", "test_validation.py"],
    deps = [
        "//lib/utils:location_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//scripts/salary:fix_state_codes_lib",
        "//scripts/salary:cleanup_orphaned_employers_lib",
        "//models:salary",
        "//models/enums:visa_program",
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
    name = "test_employer_clustering",
    size = "small",
    srcs = ["django_setup.py", "test_employer_clustering.py"],
    deps = [
        "//lib/business/salary:salary",
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
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
    name = "test_clustering_evaluator",
    size = "small",
    srcs = ["django_setup.py", "test_clustering_evaluator.py"],
    deps = [
        "//lib/business/salary:clustering_evaluator",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_clustering_metrics",
    size = "small",
    srcs = ["test_clustering_metrics.py"],
    deps = [
        ":django_setup",  # Shared Django setup
        "//lib/business/salary:clustering_evaluator",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_clustering_regression",
    size = "small",
    srcs = ["test_clustering_regression.py"],
    deps = [
        ":django_setup",  # Shared Django setup library
        "//lib/business/salary:salary",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_clustering_precision",
    size = "small",
    srcs = ["test_clustering_precision.py"],
    deps = [
        ":django_setup",  # Shared Django setup library
        "//lib/business/salary:salary",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_clustering_recall",
    size = "small",
    srcs = ["test_clustering_recall.py"],
    deps = [
        ":django_setup",  # Shared Django setup library
        "//lib/business/salary:salary",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_llm_validation_integration",
    size = "medium",  # Integration test - may take longer due to LLM calls
    srcs = ["test_llm_validation_integration.py"],
    data = [
        "//tools/ollama:ollama",  # Hermetic Ollama binary (downloaded and cached by Bazel)
    ],
    deps = [
        ":django_setup",  # Shared Django setup library
        "//lib/business/salary:llm_verifier",
        "//lib/business/salary:clustering_evaluator",
        "//models:salary",  # Required for Django app discovery
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("pytest"),
        requirement("pytest-django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    tags = ["integration", "requires-ollama"],  # Mark as integration test requiring Ollama
)

py_test(
    name = "test_perm_job_title_parsing",
    size = "small",
    srcs = ["test_perm_job_title_parsing.py"],
    deps = [
        "//lib/parsing/salary:db_importer",
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
    name = "test_data_source_utils",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_data_source_utils.py"],
    main = "test_data_source_utils.py",
    deps = [
        "//lib/utils:data_source_utils",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_orchestrator_upsert",
    size = "small",
    srcs = ["django_setup.py", "conftest.py", "test_orchestrator_upsert.py"],
    main = "test_orchestrator_upsert.py",
    deps = [
        "//lib/ingest:orchestrator",
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_exception_utils",
    size = "small",
    srcs = ["test_exception_utils.py"],
    deps = [
        "//lib/utils:exception_utils",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_dol_transform_golden",
    size = "medium",  # May take longer due to multiple test cases
    srcs = ["django_setup.py", "conftest.py", "test_dol_transform_golden.py"],
    main = "test_dol_transform_golden.py",
    data = [
        "//tests/data:dol_golden_test_data",
    ],
    deps = [
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",
        "//lib/utils:bazel_runfiles",
        "//lib/utils:data_source_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("pytest"),
        requirement("pytest-django"),
        requirement("PyYAML"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_file_discovery",
    size = "small",
    srcs = ["test_file_discovery.py"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//scripts/salary:collect_dol_golden_test_data",
        requirement("openpyxl"),
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_cluster_utils",
    size = "small",
    srcs = ["test_cluster_utils.py"],
    deps = [
        "//lib/business/salary:cluster_utils",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_batched_updates_case_insensitive",
    size = "small",
    srcs = ["test_batched_updates_case_insensitive.py"],
    deps = [
        ":django_setup",  # Shared Django setup library
        "//lib/utils:db_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
