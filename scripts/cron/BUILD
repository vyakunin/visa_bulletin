# Cron jobs and automated maintenance scripts

sh_binary(
    name = "refresh_data",
    srcs = ["refresh_data.sh"],
    data = [
        "//scripts/ingest:run_pipeline",
        "//scripts/salary:manage_salary_indexes",
        "//scripts/salary:backfill_job_title_links",
        "//scripts/salary:backfill_source_file_date",
        "//scripts/salary:cluster_job_titles",
        "//scripts/salary:update_employer_stats",
        "//scripts/salary:cluster_existing_employers",
        "//scripts/salary:update_job_title_cluster_stats",
        "//scripts/salary:populate_job_title_slugs",
        "//scripts/cache:warm_cache",
    ],
    visibility = ["//visibility:public"],
)
