load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# Export prompt template as a Bazel resource
exports_files([
    "llm_prompt_template.txt",
])

py_binary(
    name = "check_suspicious_salaries",
    srcs = ["check_suspicious_salaries.py"],
    main = "check_suspicious_salaries.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# Note: download_data.py removed - use unified ingest pipeline instead:
# bazel run //scripts/ingest:run_pipeline -- download --domain dol
# bazel run //scripts/ingest:run_pipeline -- download --list-available

# fix_calculation.py deleted - functionality consolidated into fix_invalid_wages.py

py_binary(
    name = "fix_fiscal_year_from_url",
    srcs = ["fix_fiscal_year_from_url.py"],
    main = "fix_fiscal_year_from_url.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//lib/utils:data_source_utils",
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backfill_source_file_date",
    srcs = ["backfill_source_file_date.py"],
    main = "backfill_source_file_date.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
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
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "drop_data",
    srcs = ["drop_data.py"],
    main = "drop_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "manage_salary_indexes",
    srcs = ["manage_salary_indexes.py"],
    main = "manage_salary_indexes.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:logging_utils",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
        requirement("PyYAML"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "reset_clustering",
    srcs = ["reset_clustering.py"],
    main = "reset_clustering.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "validate_data",
    srcs = ["validate_data.py"],
    main = "validate_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:data_source_utils",
        "//lib/utils:import_completeness",
        "//lib/parsing/salary:wage_unit_correction",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:visa_bulletin",
        "//lib/business/bulletin:cutoff_data_aggregator",
        "//models:salary",
        "//models:job_title",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
        requirement("openpyxl"),  # For file row counting
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "fix_missing_employers",
    srcs = ["fix_missing_employers.py"],
    main = "fix_missing_employers.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_invalid_wages",
    srcs = ["fix_invalid_wages.py"],
    main = "fix_invalid_wages.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

# Backward compatibility alias
alias(
    name = "fix_high_wage_records",
    actual = ":fix_invalid_wages",
    visibility = ["//visibility:public"],
)

py_binary(
    name = "update_wage_thresholds",
    srcs = ["update_wage_thresholds.py"],
    main = "update_wage_thresholds.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("PyYAML"),
        requirement("numpy"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_library(
    name = "fix_state_codes_lib",
    srcs = ["fix_state_codes.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:location_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
)

py_binary(
    name = "fix_state_codes",
    srcs = ["fix_state_codes.py"],
    main = "fix_state_codes.py",
    visibility = ["//visibility:public"],
    deps = [
        ":fix_state_codes_lib",
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_library(
    name = "cleanup_orphaned_employers_lib",
    srcs = ["cleanup_orphaned_employers.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
)

py_binary(
    name = "cleanup_orphaned_employers",
    srcs = ["cleanup_orphaned_employers.py"],
    main = "cleanup_orphaned_employers.py",
    visibility = ["//visibility:public"],
    deps = [
        ":cleanup_orphaned_employers_lib",
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "reimport_i200_files",
    srcs = ["reimport_i200_files.py"],
    main = "reimport_i200_files.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models/ingest:ingest",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "review_clustering",
    srcs = ["review_clustering.py"],
    main = "review_clustering.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:salary",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "cluster_existing_employers",
    srcs = ["cluster_existing_employers.py"],
    main = "cluster_existing_employers.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:rate_limited_logger",
        "//lib/utils:db_utils",
        "//lib/business/salary:salary",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
        requirement("datasketch"),  # Locality-Sensitive Hashing for fast similarity search
        requirement("tqdm"),  # Progress bar for long-running operations
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "cluster_job_titles",
    srcs = ["cluster_job_titles.py"],
    main = "cluster_job_titles.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//lib/business:clustering_engine",
        "//lib/business/salary:job_title_config",
        "//models:salary",
        "//models:job_title",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "analyze_job_title_normalization",
    srcs = ["analyze_job_title_normalization.py"],
    main = "analyze_job_title_normalization.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_job_title_normalization",
    srcs = ["fix_job_title_normalization.py"],
    main = "fix_job_title_normalization.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:db_utils",
        "//models:job_title",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_missing_salary_data",
    srcs = ["fix_missing_salary_data.py"],
    main = "fix_missing_salary_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//lib/utils:validation_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "investigate_missing_salary",
    srcs = ["investigate_missing_salary.py"],
    main = "investigate_missing_salary.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "inspect_perm_columns",
    srcs = ["inspect_perm_columns.py"],
    main = "inspect_perm_columns.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//django_config:settings",
        "//django_config:logging_config",
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "reimport_perm_salary_data",
    srcs = ["reimport_perm_salary_data.py"],
    main = "reimport_perm_salary_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//lib/ingest:orchestrator",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",  # Added: Support LCA files
        "//lib/parsing/salary:db_importer",  # Added: For source file checking
        "//lib/business/salary:salary",  # Needed by PERM plugin transform() (includes employer_clustering)
        "//models:salary",
        "//models/ingest:ingest",
        "//models/enums:visa_program",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_all_data_quality_issues",
    srcs = ["fix_all_data_quality_issues.py"],
    main = "fix_all_data_quality_issues.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",  # Django models
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "iterative_clustering_tuning",
    srcs = ["iterative_clustering_tuning.py"],
    main = "iterative_clustering_tuning.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "evaluate_clustering_threshold",
    srcs = ["evaluate_clustering_threshold.py"],
    main = "evaluate_clustering_threshold.py",
    data = [
        "llm_prompt_template.txt",  # Template file for LLM prompts
        "//tools/ollama:ollama",  # Ollama binary dependency - Bazel will install if missing
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:llm_verifier",  # For async parallel validation
        "//lib/business/salary:clustering_evaluator",  # For ClusteringEvaluator
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
        requirement("ollama"),  # Ollama Python library for HTTP API
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "binary_search_threshold",
    srcs = ["binary_search_threshold.py"],
    main = "binary_search_threshold.py",
    data = [
        "//tools/ollama:ollama",  # Ollama binary dependency - Bazel will install if missing
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "test_llm_prompts",
    srcs = ["test_llm_prompts.py"],
    main = "test_llm_prompts.py",
    data = [
        "llm_prompt_template.txt",  # Template file for LLM prompts
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/salary:llm_verifier",  # For LLM validation functions
        "//lib/business/salary:clustering_evaluator",  # For EmployerPair
        "//lib/utils:bazel_runfiles",  # For get_template_file
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("ollama"),  # Ollama Python library for HTTP API
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "collect_clustering_examples",
    srcs = ["collect_clustering_examples.py"],
    main = "collect_clustering_examples.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "collect_dol_golden_test_data",
    srcs = ["collect_dol_golden_test_data.py"],
    main = "collect_dol_golden_test_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//lib/utils:data_source_utils",
        requirement("PyYAML"),
        requirement("openpyxl"),
    ],
    python_version = "PY3",
)

py_binary(
    name = "annotate_golden_test_data",
    srcs = ["annotate_golden_test_data.py"],
    main = "annotate_golden_test_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("PyYAML"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "auto_annotate_golden_test_data",
    srcs = ["auto_annotate_golden_test_data.py"],
    main = "auto_annotate_golden_test_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:logging_utils",
        "//lib/utils:data_source_utils",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("PyYAML"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "examine_unknown_files",
    srcs = ["examine_unknown_files.py"],
    main = "examine_unknown_files.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        requirement("openpyxl"),
    ],
    python_version = "PY3",
)

py_binary(
    name = "test_detection_logic",
    srcs = ["test_detection_logic.py"],
    main = "test_detection_logic.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//scripts/salary:collect_dol_golden_test_data",
        requirement("openpyxl"),
    ],
    python_version = "PY3",
)

py_binary(
    name = "test_worksite_detection",
    srcs = ["test_worksite_detection.py"],
    main = "test_worksite_detection.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//scripts/salary:collect_dol_golden_test_data",
        requirement("openpyxl"),
    ],
    python_version = "PY3",
)

py_binary(
    name = "verify_filtered_cases",
    srcs = ["verify_filtered_cases.py"],
    main = "verify_filtered_cases.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:data_source_utils",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("PyYAML"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_yaml_enums",
    srcs = ["fix_yaml_enums.py"],
    main = "fix_yaml_enums.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
    ],
    python_version = "PY3",
)

py_binary(
    name = "view_clustering_examples",
    srcs = ["view_clustering_examples.py"],
    main = "view_clustering_examples.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//django_config:settings",
        "//django_config:logging_config",
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "review_golden_set",
    srcs = ["review_golden_set.py"],
    main = "review_golden_set.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:employer_clustering",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "harvest_bucket_mismatch_examples",
    srcs = ["harvest_bucket_mismatch_examples.py"],
    main = "harvest_bucket_mismatch_examples.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:employer_clustering",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "finalize_bucket_mismatch_reviews",
    srcs = ["finalize_bucket_mismatch_reviews.py"],
    main = "finalize_bucket_mismatch_reviews.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "check_bucket_mismatch_status",
    srcs = ["check_bucket_mismatch_status.py"],
    main = "check_bucket_mismatch_status.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "delete_incomplete_records",
    srcs = ["delete_incomplete_records.py"],
    main = "delete_incomplete_records.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "fix_pending_bucket_mismatches",
    srcs = ["fix_pending_bucket_mismatches.py"],
    main = "fix_pending_bucket_mismatches.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "add_bucket_mismatch_to_golden_set",
    srcs = ["add_bucket_mismatch_to_golden_set.py"],
    main = "add_bucket_mismatch_to_golden_set.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "review_pending_bucket_mismatches",
    srcs = ["review_pending_bucket_mismatches.py"],
    main = "review_pending_bucket_mismatches.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "apply_manual_bucket_mismatch_reviews",
    srcs = ["apply_manual_bucket_mismatch_reviews.py"],
    main = "apply_manual_bucket_mismatch_reviews.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "apply_review_decisions",
    srcs = ["apply_review_decisions.py"],
    main = "apply_review_decisions.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:employer_clustering",
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "benchmark_clustering",
    srcs = ["benchmark_clustering.py"],
    main = "benchmark_clustering.py",
    data = [
        "llm_prompt_template.txt",  # Template file for LLM prompts
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/business/salary:llm_verifier",  # For LLM verifier interface
        "//lib/business/salary:clustering_evaluator",  # For EmployerPair
        "//lib/business/salary:employer_clustering",  # For production algorithm benchmarking
        "//scripts/salary:cluster_existing_employers",  # For LSH functions (_build_lsh_index, _get_normalized_name_similarity)
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
        requirement("ollama"),  # Ollama Python library for HTTP API
        requirement("datasketch"),  # For LSH (MinHash, MinHashLSH)
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "verify_file_discovery",
    srcs = ["verify_file_discovery.py"],
    main = "verify_file_discovery.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//scripts/salary:collect_dol_golden_test_data",
        requirement("openpyxl"),
    ],
    python_version = "PY3",
)

py_binary(
    name = "merge_duplicate_clusters",
    srcs = ["merge_duplicate_clusters.py"],
    main = "merge_duplicate_clusters.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",  # For bulk_update_batched
        "//models:salary",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),  # PostgreSQL adapter
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)


py_binary(
    name = "check_job_title_status",
    srcs = ["check_job_title_status.py"],
    main = "check_job_title_status.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "backfill_job_title_links",
    srcs = ["backfill_job_title_links.py"],
    main = "backfill_job_title_links.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:db_utils",
        "//models:salary",
        "//models:job_title",
        "//django_config:settings",
        "//django_config:logging_config",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "populate_job_title_slugs",
    srcs = ["populate_job_title_slugs.py"],
    main = "populate_job_title_slugs.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "find_valid_job_title_slug",
    srcs = ["find_valid_job_title_slug.py"],
    main = "find_valid_job_title_slug.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "check_sitemap_eligibility",
    srcs = ["check_sitemap_eligibility.py"],
    main = "check_sitemap_eligibility.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "debug_job_title_data",
    srcs = ["debug_job_title_data.py"],
    main = "debug_job_title_data.py",
    visibility = ["//visibility:public"],
    deps = [
        "//models:salary",
        "//models:job_title",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "update_employer_stats",
    srcs = ["update_employer_stats.py"],
    main = "update_employer_stats.py",
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
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
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_library(
    name = "update_job_title_cluster_stats_lib",
    srcs = ["update_job_title_cluster_stats.py"],
    visibility = ["//tests:__pkg__"],
    deps = [
        "//lib/utils:logging_utils",
        "//lib/utils:db_utils",
        "//models:job_title",
        "//models:salary",
        "//django_config:settings",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
)

py_binary(
    name = "update_job_title_cluster_stats",
    srcs = ["update_job_title_cluster_stats.py"],
    main = "update_job_title_cluster_stats.py",
    visibility = ["//visibility:public"],
    deps = [
        ":update_job_title_cluster_stats_lib",
    ],
    python_version = "PY3",
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
