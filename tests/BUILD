# Build file for tests
# Following rule: One Bazel target per file
# Tests use pytest format but work with Bazel py_test
# DB-using tests: use django_py_test() from django_test.bzl for common deps and CREATEDB flow.

load("@rules_python//python:defs.bzl", "py_library", "py_test")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")
load(":django_test.bzl", "django_py_test")

exports_files([
    "test_salary_data.csv",
])

# Shared Django setup library - used by multiple test targets.
# Calls ensure_test_db.grant_createdb() on first DB test when PG_SUPERUSER_* is set (no manual step).
py_library(
    name = "django_setup",
    srcs = ["django_setup.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":ensure_test_db_lib",
        requirement("Django"),
        "//django_config:settings",
    ],
)

# Grant CREATEDB logic: used by django_setup on first DB test when PG_SUPERUSER_* set (or .env).
py_library(
    name = "ensure_test_db_lib",
    srcs = ["ensure_test_db.py"],
    visibility = ["//visibility:public"],
    deps = [requirement("psycopg2_binary")],
)

# Pytest config and fixtures; tests that use pytest depend on this instead of listing conftest.py in srcs.
py_library(
    name = "conftest_lib",
    srcs = ["conftest.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":django_setup",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//webapp:apps",
        requirement("pytest"),
        requirement("pytest-django"),
    ],
)

py_test(
    name = "test_copy_schema",
    size = "small",
    srcs = ["test_copy_schema.py"],
    main = "test_copy_schema.py",
    deps = [
        ":django_setup",
        "//lib/ingest:schema",
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

py_test(
    name = "test_worksite_record_copy_bug",
    size = "small",
    srcs = ["test_worksite_record_copy_bug.py"],
    data = ["//models:migrations"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
        "RUNNING_TESTS": "1",
    },
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

# Same dep graph as refresh_bulletin (parser via visa_bulletin plugin). Parser must list
# //models/enums:family_preference so runfiles include it (prod ModuleNotFoundError otherwise).
py_test(
    name = "test_bulletin_parser_deps",
    size = "small",
    srcs = ["test_bulletin_parser_deps.py"],
    main = "test_bulletin_parser_deps.py",
    deps = [
        ":django_setup",
        "//lib/ingest/plugins:visa_bulletin",
        "//django_config:settings",
        "//webapp:apps",
        "//models/ingest:ingest",
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
    name = "test_extractor",
    size = "small",
    srcs = ["test_extractor.py"],
    main = "test_extractor.py",
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        ":conftest_lib",
        ":django_setup",
        "//lib/parsing/bulletin:bulletin_table",
        "//lib/parsing/bulletin:parser",
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
    srcs = ["test_integration.py"],
    main = "test_integration.py",
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_country_header_parsing.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        ":django_setup",
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

django_py_test(
    name = "test_bulletin_narrator",
    srcs = ["test_bulletin_narrator.py"],
    deps = [
        "//lib/business/blog:blog",
    ],
)

django_py_test(
    name = "test_prediction_category_landing",
    srcs = ["test_prediction_category_landing.py"],
    deps = [
        "//models:bulletin",
        "//webapp:urls",
    ],
)

py_test(
    name = "test_webapp_ui",
    size = "small",
    srcs = ["test_webapp_ui.py"],
    data = ["//models:migrations"],
    deps = [
        ":django_setup",
        "//webapp/views:views",
        "//models:blog",
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
    srcs = ["test_visa_class_utils.py"],
    deps = [
        ":django_setup",
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
    srcs = ["test_dashboard_integration.py"],
    deps = [
        ":django_setup",
        "//webapp/views:views",
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
        "//models/ingest:ingest",
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
    name = "test_salary_search_view",
    size = "small",
    srcs = ["test_salary_search_view.py"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models:job_title",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("Django"),
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
    name = "test_fenced_page_ids",
    size = "small",
    srcs = ["test_fenced_page_ids.py"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//lib/utils:filter_utils",
        requirement("Django"),
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
    name = "test_salary_import",
    size = "small",
    srcs = ["test_salary_import.py"],
    main = "test_salary_import.py",
    data = [
        ":test_salary_data.csv",
    ],
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_ingest_integration.py"],
    main = "test_ingest_integration.py",
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_salary_real_data.py"],
    main = "test_salary_real_data.py",
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp/views:views",
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
    srcs = ["test_ingest_models.py"],
    main = "test_ingest_models.py",
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_ingest_plugins.py"],
    main = "test_ingest_plugins.py",
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_worksite_record.py"],
    deps = [
        ":django_setup",
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
    srcs = ["test_lca_plugin.py"],
    main = "test_lca_plugin.py",
    deps = [
        ":django_setup",
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
    srcs = ["test_ingest_versioning.py"],
    main = "test_ingest_versioning.py",
    tags = ["exclusive"],
    deps = [
        ":conftest_lib",
        ":django_setup",
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
        "RUNNING_TESTS": "1",
    },
)

py_test(
    name = "test_validation",
    size = "small",
    srcs = ["test_validation.py"],
    deps = [
        ":django_setup",
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
    srcs = ["test_employer_clustering.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:employer_clustering",
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
        "RUNNING_TESTS": "1",
    },
)

py_test(
    name = "test_clustering_evaluator",
    size = "small",
    srcs = ["test_clustering_evaluator.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:clustering_evaluator",
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

py_test(
    name = "test_clustering_metrics",
    size = "small",
    srcs = ["test_clustering_metrics.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:clustering_evaluator",
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

py_test(
    name = "test_clustering_regression",
    size = "small",
    srcs = ["test_clustering_regression.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:employer_clustering",
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
        "RUNNING_TESTS": "1",
    },
)

py_test(
    name = "test_clustering_precision",
    size = "small",
    srcs = ["test_clustering_precision.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:employer_clustering",
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

py_test(
    name = "test_clustering_recall",
    size = "small",
    srcs = ["test_clustering_recall.py"],
    deps = [
        ":django_setup",
        "//lib/business/salary:employer_clustering",
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
    srcs = ["test_data_source_utils.py"],
    main = "test_data_source_utils.py",
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    srcs = ["test_orchestrator_upsert.py"],
    main = "test_orchestrator_upsert.py",
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    size = "medium",
    srcs = ["test_dol_transform_golden.py"],
    main = "test_dol_transform_golden.py",
    data = [
        "//tests/data:dol_golden_test_data",
    ],
    deps = [
        ":conftest_lib",
        ":django_setup",
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
    name = "test_dol_parsing_smoke",
    size = "medium",
    srcs = ["test_dol_parsing_smoke.py"],
    deps = [
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
        "//lib/utils:http_utils",
        "//models/ingest:ingest",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    tags = ["smoke", "parsing"],
)

py_test(
    name = "test_dol_parsing_comprehensive",
    size = "small",
    srcs = ["test_dol_parsing_comprehensive.py"],
    data = ["//models:migrations"],
    deps = [
        ":django_setup",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
        "//models/ingest:ingest",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    tags = ["smoke", "parsing", "precommit"],
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
    data = ["//models:migrations"],
    deps = [
        ":django_setup",
        "//lib/utils:db_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
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
    name = "test_clustering_cache_fix",
    size = "small",
    srcs = ["test_clustering_cache_fix.py"],
    data = ["//models:migrations"],
    deps = [
        ":django_setup",
        "//lib/utils:db_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
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

django_py_test(
    name = "test_job_title_normalization",
    srcs = ["test_job_title_normalization.py"],
    deps = [
        "//models:job_title",
    ],
)

py_test(
    name = "test_employer_profile_view",
    size = "small",
    srcs = ["test_employer_profile_view.py"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
        "RUNNING_TESTS": "1",
    },
)

py_test(
    name = "test_employer_rankings_view",
    size = "small",
    srcs = ["test_employer_rankings_view.py"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp:urls",
        "//webapp/views/employers:rankings",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
        "RUNNING_TESTS": "1",
    },
)

py_test(
    name = "test_visa_program",
    size = "small",
    srcs = ["test_visa_program.py"],
    deps = [
        ":django_setup",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_employer_directory_view",
    size = "small",
    srcs = ["test_employer_directory_view.py"],
    deps = [
        ":django_setup",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        "//webapp:urls",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_test(
    name = "test_no_init_in_code_dirs",
    size = "small",
    srcs = ["test_no_init_in_code_dirs.py"],
    data = ["//lib/business/salary:no_init_check"],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_debug_safety",
    size = "small",
    srcs = ["test_debug_safety.py"],
    python_version = "PY3",
    srcs_version = "PY3",
    deps = [
        "//django_config:debug_safety",
        requirement("Django"),
    ],
)

django_py_test(
    name = "test_job_title_profile_view",
    size = "small",
    srcs = ["test_job_title_profile_view.py"],
    deps = [
        "//models/ingest:ingest",
        "//models:salary",
        "//models:job_title",
        "//models/enums:visa_program",
        "//models/ingest:ingest_version",
        "//lib/business/salary:job_title_stats",
        "//lib/business/salary:job_title_chart_builder",
        "//scripts/salary:update_job_title_cluster_stats_lib",
        "//django_config:urls",
        "//django_config:context_processors",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("plotly"),
    ],
)

# Refresh pipeline tests (no Django)
py_test(
    name = "test_refresh_checkpoint",
    size = "small",
    srcs = ["test_refresh_checkpoint.py"],
    main = "test_refresh_checkpoint.py",
    deps = [
        "//scripts/cron/refresh:checkpoint",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_refresh_config",
    size = "small",
    srcs = ["test_refresh_config.py"],
    main = "test_refresh_config.py",
    deps = [
        "//scripts/cron/refresh:config",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_refresh_pipeline",
    size = "small",
    srcs = ["test_refresh_pipeline.py"],
    main = "test_refresh_pipeline.py",
    deps = [
        "//scripts/cron/refresh:checkpoint",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:pipeline",
        "//scripts/cron/refresh:runner",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_refresh_steps",
    size = "small",
    srcs = ["test_refresh_steps.py"],
    deps = [
        "//scripts/cron/refresh:steps",
        "//scripts/cron/refresh:runner",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:services",
        requirement("pytest"),
    ],
)

py_test(
    name = "test_refresh_instance",
    size = "small",
    srcs = ["test_refresh_instance.py"],
    main = "test_refresh_instance.py",
    deps = [
        "//scripts/cron/refresh:instance",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_traffic_switch",
    size = "small",
    srcs = ["test_traffic_switch.py"],
    main = "test_traffic_switch.py",
    deps = [
        "//scripts/cron/refresh:traffic_switch",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_refresh_orchestrate",
    size = "small",
    srcs = ["test_refresh_orchestrate.py"],
    main = "test_refresh_orchestrate.py",
    deps = [
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:instance",
        "//scripts/cron/refresh:orchestrate",
        "//scripts/cron/refresh:runner",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

# New tests from wip/pre-cleanup
py_test(
    name = "test_supply",
    srcs = ["test_supply.py"],
    deps = [
        "//lib/business/vqs/supply",
        "//models/enums:country",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
    tags = ["manual"],
)

py_test(
    name = "test_url_utils",
    srcs = ["test_url_utils.py"],
    deps = [
        "//lib/utils:url_utils",
    ],
)

py_test(
    name = "test_vqs_regime",
    size = "small",
    srcs = ["test_vqs_regime.py"],
    deps = [
        "//lib/business/vqs:regime",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_vqs_metrics",
    size = "small",
    srcs = ["test_vqs_metrics.py"],
    deps = [
        "//lib/business/vqs:metric_config",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_data_cache",
    size = "small",
    srcs = ["test_data_cache.py"],
    deps = [
        "//lib/business/vqs:data_cache",
        requirement("pytest"),
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)

py_test(
    name = "test_solver_regime_display",
    size = "small",
    srcs = ["test_solver_regime_display.py"],
    deps = [
        "//lib/business/vqs:solver",
        "//lib/business/vqs:regime",
        "//lib/business/vqs:expert_pool",
    ],
    python_version = "PY3",
    srcs_version = "PY3",
)
