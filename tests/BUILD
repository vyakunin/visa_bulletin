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

django_py_test(
    name = "test_copy_schema",
    size = "small",
    srcs = ["test_copy_schema.py"],
    deps = [
        "//lib/ingest:schema",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_seo_page_heading",
    size = "small",
    srcs = ["test_seo_page_heading.py"],
    deps = [
        "//lib/business/bulletin:cutoff_data_aggregator",
        "//models/enums:country",
        "//models/enums:visa_category",
    ],
)

django_py_test(
    name = "test_worksite_record_copy_bug",
    size = "small",
    srcs = ["test_worksite_record_copy_bug.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
    ],
)

django_py_test(
    name = "test_wage_unit_parsing",
    size = "small",
    srcs = ["test_wage_unit_parsing.py"],
    deps = [
        "//models/enums:visa_program",
        "//lib/parsing/salary:wage_unit_correction",
    ],
)

django_py_test(
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
)

# Same dep graph as refresh_bulletin (parser via visa_bulletin plugin). Parser must list
# //models/enums:family_preference so runfiles include it (prod ModuleNotFoundError otherwise).
django_py_test(
    name = "test_bulletin_parser_deps",
    size = "small",
    srcs = ["test_bulletin_parser_deps.py"],
    deps = [
        "//lib/ingest/plugins:visa_bulletin",
        "//models/ingest:ingest",
    ],
)

django_py_test(
    name = "test_extractor",
    size = "small",
    srcs = ["test_extractor.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        ":conftest_lib",
        "//lib/parsing/bulletin:bulletin_table",
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//lib/parsing/bulletin:table_to_cutoff_data",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_integration",
    size = "small",
    srcs = ["test_integration.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        ":conftest_lib",
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:publication_data",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//lib/parsing/bulletin:db_importer",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        requirement("beautifulsoup4"),
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_country_header_parsing",
    size = "small",
    srcs = ["test_country_header_parsing.py"],
    data = [
        "//data/bulletin/saved_pages:test_data",
    ],
    deps = [
        "//lib/parsing/bulletin:parser",
        "//lib/parsing/bulletin:table_to_cutoff_data",
        "//lib/parsing/bulletin:publication_data",
        "//models/enums:country",
        requirement("beautifulsoup4"),
        requirement("soupsieve"),
    ],
)

django_py_test(
    name = "test_projection",
    size = "small",
    srcs = ["test_projection.py"],
    deps = [
        "//lib/business/bulletin:cutoff_projection",
    ],
)

django_py_test(
    name = "test_chart_builder",
    size = "small",
    srcs = ["test_chart_builder.py"],
    deps = [
        "//lib/business/bulletin:chart_builder",
        "//models/enums:country",
        requirement("plotly"),
    ],
)

django_py_test(
    name = "test_bulletin_narrator",
    srcs = ["test_bulletin_narrator.py"],
    deps = [
        "//lib/business/blog:blog",
        "//models/enums:country",
    ],
)

py_test(
    name = "test_calibration_cache",
    srcs = ["test_calibration_cache.py"],
    deps = [
        "//lib/business/vqs:calibration",
    ],
)

django_py_test(
    name = "test_prediction_category_landing",
    srcs = ["test_prediction_category_landing.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:bulletin",
        "//webapp:urls",
        "//webapp/views:views",
    ],
)

django_py_test(
    name = "test_next_bulletin",
    srcs = ["test_next_bulletin.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//lib/business/bulletin:release_schedule",
        "//models:bulletin",
        "//webapp:urls",
        "//webapp/views:views",
    ],
)

django_py_test(
    name = "test_cluster_merge",
    size = "small",
    srcs = ["test_cluster_merge.py"],
    deps = [
        "//lib/utils:db_utils",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_clustering_job_integration",
    srcs = ["test_clustering_job_integration.py"],
    deps = [
        "//models:salary",
        "//scripts/salary:cluster_existing_employers_lib",
    ],
)

django_py_test(
    name = "test_webapp_ui",
    size = "small",
    srcs = ["test_webapp_ui.py"],
    deps = [
        "//webapp/views:views",
        "//models:blog",
        "//models:visa_cutoff_date",
    ],
)

django_py_test(
    name = "test_employment_preference",
    size = "small",
    srcs = ["test_employment_preference.py"],
    deps = [
        "//models/enums:employment_preference",
    ],
)

django_py_test(
    name = "test_visa_class_utils",
    size = "small",
    srcs = ["test_visa_class_utils.py"],
    deps = [
        "//lib/business/bulletin:visa_class_utils",
        "//models:visa_cutoff_date",
        "//models:bulletin",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:family_preference",
        "//models/enums:employment_preference",
    ],
)

django_py_test(
    name = "test_dashboard_integration",
    size = "small",
    srcs = ["test_dashboard_integration.py"],
    deps = [
        "//webapp/views:views",
        "//models:visa_cutoff_date",
        "//models:bulletin",
        "//models/enums:visa_category",
        "//models/enums:action_type",
        "//models/enums:country",
        "//django_config:urls",
        "//webapp:urls",
    ],
)

django_py_test(
    name = "test_salary",
    size = "small",
    srcs = ["test_salary.py"],
    deps = [
        "//lib/utils:location_utils",
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
        "//lib/parsing/salary:wage_unit_correction",
    ],
)

django_py_test(
    name = "test_salary_search_view",
    size = "small",
    srcs = ["test_salary_search_view.py"],
    deps = [
        "//django_config:urls",
        "//django_config:context_processors",
        "//models:salary",
        "//models:job_title",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
    ],
)

django_py_test(
    name = "test_fenced_page_ids",
    srcs = ["test_fenced_page_ids.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/utils:filter_utils",
    ],
)

django_py_test(
    name = "test_cluster_stats_freshness",
    srcs = ["test_cluster_stats_freshness.py"],
    deps = [
        "//models:salary",
        "//models:job_title",
        "//models/enums:visa_program",
        "//scripts/salary:cluster_existing_employers_lib",
        "//scripts/salary:update_job_title_cluster_stats_lib",
    ],
)

django_py_test(
    name = "test_fenced_aggregate",
    srcs = ["test_fenced_aggregate.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//lib/utils:filter_utils",
    ],
)

django_py_test(
    name = "test_salary_import",
    # Un-quarantined 2026-06-20: all 11 failures were one BUILD dep-gap, not a
    # logic regression. db_importer._get_or_create_employer does a runtime
    # `from lib.business.salary.employer_clustering import assign_to_cluster`
    # (local import to avoid a lib-level cycle); without the dep in runfiles every
    # row errored before validation ran, so even the rejection tests failed. The 3
    # salary_search view tests also needed webapp views+urls (like
    # test_salary_real_data). Added all three deps.
    size = "small",
    srcs = ["test_salary_import.py"],
    data = [
        ":test_salary_data.csv",
    ],
    deps = [
        ":conftest_lib",
        "//lib/business/salary:employer_clustering",
        "//lib/parsing/salary:db_importer",
        "//lib/parsing/salary:wage_unit_correction",
        "//lib/utils:data_source_utils",
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_ingest_integration",
    size = "medium",
    srcs = ["test_ingest_integration.py"],
    deps = [
        ":conftest_lib",
        "//lib/ingest:ingest",
        "//lib/ingest:orchestrator",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:plugins",
        "//models/ingest:ingest",
        "//models:salary",
        requirement("pytest-django"),
        requirement("openpyxl"),
    ],
)

django_py_test(
    name = "test_salary_real_data",
    size = "small",
    srcs = ["test_salary_real_data.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp/views:views",
        "//webapp:urls",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_ingest_models",
    size = "small",
    srcs = ["test_ingest_models.py"],
    deps = [
        ":conftest_lib",
        "//models/ingest:ingest",
        "//models/ingest:enums",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_ingest_plugins",
    # Un-quarantined 2026-06-20: test_download was fixed in commit 04ea649 (the
    # last remaining failure); the target now runs fully green.
    size = "small",
    srcs = ["test_ingest_plugins.py"],
    deps = [
        ":conftest_lib",
        "//lib/ingest:base",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
        "//lib/utils:http_utils",
        "//models/ingest:ingest",
        "//models/ingest:enums",
        "//models:salary",
        requirement("pytest-django"),
        requirement("openpyxl"),
    ],
)

django_py_test(
    name = "test_worksite_record",
    size = "small",
    srcs = ["test_worksite_record.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
    ],
)

django_py_test(
    name = "test_lca_plugin",
    # Un-quarantined 2026-06-20: 5 failures were a missing @pytest.mark.django_db
    # on the DB-touching classes (TestLCATransformRouting/Parse/Validation); the
    # 6th was a stale fixture (a year-less filename -> _fiscal_year=None) fixed by
    # using an FY2024 filename. See umbrella "test suite false-green" ticket.
    size = "small",
    srcs = ["test_lca_plugin.py"],
    deps = [
        "//lib/ingest:base",
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/parsing/salary:file_detection",
        "//models/ingest:ingest",
        "//models/ingest:enums",
        "//models:salary",
        requirement("pytest-django"),
        requirement("openpyxl"),
    ],
)

django_py_test(
    name = "test_ingest_versioning",
    size = "small",
    srcs = ["test_ingest_versioning.py"],
    tags = ["exclusive"],
    deps = [
        ":conftest_lib",
        "//lib/ingest:versioning",
        "//models/ingest:ingest",
        "//models:salary",
        "//models:visa_cutoff_date",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_validation",
    # Un-quarantined 2026-06-20: the 5 failing wage-unit assertions were stale
    # (asserted old arbitrary $500/hr,$50K/mo thresholds + a higher min). The
    # should_correct_wage_unit redesign to a single data-driven [MIN_ANNUAL,
    # MAX_ANNUAL] range was intentional (ticket 38462b8d); tests rewritten to the
    # new contract.
    size = "small",
    srcs = ["test_validation.py"],
    deps = [
        "//lib/utils:location_utils",
        "//lib/parsing/salary:wage_unit_correction",
        "//scripts/salary:fix_state_codes_lib",
        "//scripts/salary:cleanup_orphaned_employers_lib",
        "//models:salary",
        "//models/enums:visa_program",
    ],
)

django_py_test(
    name = "test_employer_clustering",
    # Un-quarantined 2026-06-20: 3 failures were fixture unique-collisions
    # (normalize_name collapses "Google Inc."/"Google" -> "google", etc.); 2 were
    # stale matching assertions against a pre-rewrite 0.85 threshold (the impl has
    # used a 0.95 similarity threshold since commit 2ffb1ec, favoring precision).
    # Rewritten to the real contract + a precision-boundary non-match test. See
    # umbrella "test suite false-green" ticket.
    size = "small",
    srcs = ["test_employer_clustering.py"],
    deps = [
        "//lib/business/salary:employer_clustering",
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
    ],
)

# test_clustering_evaluator + test_clustering_metrics + test_llm_validation_integration
# removed 2026-06-20 with the Ollama LLM clustering-evaluator subsystem (Ollama retired).

django_py_test(
    name = "test_clustering_regression",
    size = "small",
    srcs = ["test_clustering_regression.py"],
    deps = [
        "//lib/business/salary:employer_clustering",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_clustering_precision",
    size = "small",
    srcs = ["test_clustering_precision.py"],
    deps = [
        "//lib/business/salary:employer_clustering",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_clustering_recall",
    size = "small",
    srcs = ["test_clustering_recall.py"],
    deps = [
        "//lib/business/salary:employer_clustering",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_perm_job_title_parsing",
    size = "small",
    srcs = ["test_perm_job_title_parsing.py"],
    deps = [
        "//lib/parsing/salary:db_importer",
    ],
)

django_py_test(
    name = "test_data_source_utils",
    size = "small",
    srcs = ["test_data_source_utils.py"],
    deps = [
        ":conftest_lib",
        "//lib/utils:data_source_utils",
        "//models/ingest:ingest",
    ],
)

django_py_test(
    name = "test_orchestrator_upsert",
    size = "small",
    srcs = ["test_orchestrator_upsert.py"],
    deps = [
        ":conftest_lib",
        "//lib/ingest:orchestrator",
        "//models:salary",
        "//models/enums:visa_program",
        "//models/ingest:ingest",
    ],
)

django_py_test(
    name = "test_exception_utils",
    size = "small",
    srcs = ["test_exception_utils.py"],
    deps = [
        "//lib/utils:exception_utils",
    ],
)

django_py_test(
    name = "test_dol_transform_golden",
    # Golden rebaselined 2026-06-23 from verified transform output (440 annotated
    # non-error cases) after categorizing every drift: 3204 None->value enrichment
    # (dates/employer_id/prevailing_wage_unit), worksite_state full-name->2-letter
    # (normalize_state_code), the resolved PERM/H1B employer-title preference, and
    # the wage-unit annualization fix — ZERO field losses. Regenerate with
    # //scripts/oneoff:regen_dol_golden (it ABORTS if any annotated case now
    # transforms to None — a real regression vs benign drift).
    size = "medium",
    srcs = ["test_dol_transform_golden.py"],
    data = [
        "//tests/data:dol_golden_test_data",
    ],
    deps = [
        ":conftest_lib",
        "//lib/ingest/plugins:dol_perm",
        "//lib/ingest/plugins:dol_lca",
        "//lib/utils:bazel_runfiles",
        "//lib/utils:data_source_utils",
        "//models:salary",
        requirement("pytest-django"),
        requirement("PyYAML"),
    ],
)

django_py_test(
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
        requirement("openpyxl"),
    ],
    tags = ["smoke", "parsing"],
)

django_py_test(
    name = "test_dol_parsing_comprehensive",
    size = "small",
    srcs = ["test_dol_parsing_comprehensive.py"],
    deps = [
        "//lib/ingest:registry",
        "//lib/ingest/plugins:dol_lca",
        "//lib/ingest/plugins:dol_perm",
        "//models/ingest:ingest",
        "//models:salary",
    ],
    tags = ["smoke", "parsing", "precommit"],
)

django_py_test(
    name = "test_file_discovery",
    size = "small",
    srcs = ["test_file_discovery.py"],
    deps = [
        "//lib/utils:http_utils",
        "//lib/utils:excel_utils",
        "//scripts/salary:collect_dol_golden_test_data",
        requirement("openpyxl"),
    ],
)

django_py_test(
    name = "test_cluster_utils",
    size = "small",
    srcs = ["test_cluster_utils.py"],
    deps = [
        "//lib/business/salary:cluster_utils",
    ],
)

django_py_test(
    name = "test_batched_updates_case_insensitive",
    size = "small",
    srcs = ["test_batched_updates_case_insensitive.py"],
    deps = [
        "//lib/utils:db_utils",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_clustering_cache_fix",
    size = "small",
    srcs = ["test_clustering_cache_fix.py"],
    deps = [
        "//lib/utils:db_utils",
        "//models:salary",
    ],
)

django_py_test(
    name = "test_job_title_normalization",
    srcs = ["test_job_title_normalization.py"],
    deps = [
        "//models:job_title",
    ],
)

django_py_test(
    name = "test_employer_profile_view",
    size = "small",
    srcs = ["test_employer_profile_view.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:job_title",
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
    ],
)

django_py_test(
    name = "test_employer_rankings_view",
    size = "small",
    srcs = ["test_employer_rankings_view.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
        "//webapp/views/employers:rankings",
    ],
)

django_py_test(
    name = "test_visa_program",
    size = "small",
    srcs = ["test_visa_program.py"],
    deps = [
        "//models/enums:visa_program",
    ],
)

django_py_test(
    name = "test_employer_directory_view",
    size = "small",
    srcs = ["test_employer_directory_view.py"],
    deps = [
        "//django_config:urls",
        "//django_config:context_processors",
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
    ],
)

django_py_test(
    name = "test_no_init_in_code_dirs",
    size = "small",
    srcs = ["test_no_init_in_code_dirs.py"],
    data = ["//lib/business/salary:no_init_check"],
)

django_py_test(
    name = "test_debug_safety",
    size = "small",
    srcs = ["test_debug_safety.py"],
    deps = [
        "//django_config:debug_safety",
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
django_py_test(
    name = "test_refresh_checkpoint",
    size = "small",
    srcs = ["test_refresh_checkpoint.py"],
    deps = [
        "//scripts/cron/refresh:checkpoint",
    ],
)

django_py_test(
    name = "test_refresh_config",
    size = "small",
    srcs = ["test_refresh_config.py"],
    deps = [
        "//scripts/cron/refresh:config",
    ],
)

django_py_test(
    name = "test_refresh_pipeline",
    size = "small",
    srcs = ["test_refresh_pipeline.py"],
    deps = [
        "//scripts/cron/refresh:checkpoint",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:pipeline",
        "//scripts/cron/refresh:runner",
        # steps.py lazily does `from . import services`; needed in runfiles.
        "//scripts/cron/refresh:services",
    ],
)

django_py_test(
    name = "test_refresh_steps",
    size = "small",
    srcs = ["test_refresh_steps.py"],
    deps = [
        "//scripts/cron/refresh:steps",
        "//scripts/cron/refresh:runner",
        "//scripts/cron/refresh:config",
        "//scripts/cron/refresh:services",
    ],
)

# test_refresh_instance + test_traffic_switch + test_refresh_orchestrate removed
# 2026-06-20 with the AWS/Lightsail orchestrator (instance / traffic_switch /
# orchestrate) they covered (Lightsail retired -> homeserver + Cloudflare).

# New tests from wip/pre-cleanup
django_py_test(
    name = "test_supply",
    srcs = ["test_supply.py"],
    deps = [
        "//lib/business/vqs/supply",
        "//models/enums:country",
    ],
)

django_py_test(
    name = "test_url_utils",
    srcs = ["test_url_utils.py"],
    deps = [
        "//lib/utils:url_utils",
    ],
)

django_py_test(
    name = "test_vqs_regime",
    size = "small",
    srcs = ["test_vqs_regime.py"],
    deps = [
        "//lib/business/vqs:regime",
    ],
)

django_py_test(
    name = "test_vqs_metrics",
    size = "small",
    srcs = ["test_vqs_metrics.py"],
    deps = [
        "//lib/business/vqs:metric_config",
    ],
)

django_py_test(
    name = "test_data_cache",
    size = "small",
    srcs = ["test_data_cache.py"],
    deps = [
        "//lib/business/vqs:data_cache",
        # data_cache lazily imports models.bulletin / models.visa_cutoff_date inside
        # its functions, so the bulletin enum chain isn't picked up statically.
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:employment_preference",
        "//models/enums:family_preference",
        "//models/enums:visa_category",
    ],
)

django_py_test(
    name = "test_solver_regime_display",
    size = "small",
    srcs = ["test_solver_regime_display.py"],
    deps = [
        "//lib/business/vqs:solver",
        "//lib/business/vqs:regime",
        "//lib/business/vqs:expert_pool",
    ],
)

django_py_test(
    name = "test_sitemap_lastmod",
    size = "small",
    srcs = ["test_sitemap_lastmod.py"],
    deps = [
        "//django_config:urls",
        "//models:bulletin",
        "//models:job_title",
        "//models:salary",
        "//webapp/views/seo:sitemaps",
    ],
)

django_py_test(
    name = "test_priority_date_landing",
    size = "small",
    srcs = ["test_priority_date_landing.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_h1b_sponsors_landing",
    size = "small",
    srcs = ["test_h1b_sponsors_landing.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:job_title",
        "//models:salary",
        "//models/enums:visa_program",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_priority_date_rollup",
    size = "small",
    srcs = ["test_priority_date_rollup.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//webapp:urls",
        "//webapp/views:views",
        requirement("pytest-django"),
    ],
)

django_py_test(
    name = "test_prediction_month_forecast",
    size = "small",
    srcs = ["test_prediction_month_forecast.py"],
    deps = [
        "//django_config:context_processors",
        "//django_config:urls",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:vqs",
        "//models/enums:action_type",
        "//models/enums:country",
        "//webapp:urls",
        "//webapp/views:views",
        "//webapp/views:prediction_views",
        requirement("pytest-django"),
    ],
)
