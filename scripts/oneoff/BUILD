load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "attach_staging_ip_to_old_prod",
    srcs = ["attach_staging_ip_to_old_prod.py"],
    main = "attach_staging_ip_to_old_prod.py",
    deps = ["//scripts/cron/refresh:traffic_switch"],
)

py_binary(
    name = "purge_bad_6m_predictions",
    srcs = ["purge_bad_6m_predictions.py"],
    main = "purge_bad_6m_predictions.py",
    deps = [
        "//django_config:settings",
        "//models:vqs",
        "//webapp:apps",
        requirement("Django"),
        requirement("asgiref"),
        requirement("sqlparse"),
        requirement("psycopg2_binary"),
    ],
    python_version = "PY3",
    env = {"DJANGO_SETTINGS_MODULE": "django_config.settings"},
)

py_binary(
    name = "generate_initial_blog_post",
    srcs = ["generate_initial_blog_post.py"],
    main = "generate_initial_blog_post.py",
    deps = [
        "//django_config:settings",
        "//models:bulletin",
        "//models:vqs",
        "//models:blog",
        "//lib/business/blog:blog",
        "//webapp:apps",
        requirement("Django"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "generate_initial_blog_posts",
    srcs = ["generate_initial_blog_posts.py"],
    deps = [
        "//django_config:settings",
        "//django_config:logging_config",
        "//models:bulletin",
        "//models:blog",
        "//models:vqs",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//lib/business/blog:blog",
        "//lib/utils:logging_utils",
        "//webapp:apps",
        requirement("Django"),
        requirement("python-dateutil"),
        requirement("psycopg2_binary"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "debug_predictions_eb3_row",
    srcs = ["debug_predictions_eb3_row.py"],
    deps = [
        "//django_config:settings",
        "//models:visa_cutoff_date",
        "//models:vqs",
        "//models:bulletin",
        "//models/enums:visa_category",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)







py_binary(
    name = "evaluate_horizon_metrics",
    srcs = ["evaluate_horizon_metrics.py"],
    deps = [
        "//django_config:settings",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:vqs",
        "//models/enums:visa_category",
        "//models/enums:country",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
        requirement("numpy"),
        requirement("pandas"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "visualize_backtest",
    srcs = ["visualize_backtest.py"],
    deps = [
        "//django_config:settings",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//webapp:apps",
        "//lib/business/vqs:solver",
        "//models:raw_facts",
        requirement("Django"),
        requirement("psycopg2_binary"),
        requirement("plotly"),
        requirement("python-dateutil"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "debug_dashboard_slope",
    srcs = ["debug_dashboard_slope.py"],
    deps = [
        "//django_config:settings",
        "//models:visa_cutoff_date",
        "//models:bulletin",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//webapp:apps",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "debug_vqs_behavior",
    srcs = ["debug_vqs_behavior.py"],
    deps = [
        "//django_config:settings",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models:bulletin",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//lib/business/vqs:solver",
        "//webapp:apps",
        requirement("Django"),
        requirement("python-dateutil"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)

py_binary(
    name = "analyze_october_predictions",
    srcs = ["analyze_october_predictions.py"],
    deps = [
        "//django_config:settings",
        "//models:visa_cutoff_date",
        "//models:raw_facts",
        "//models:bulletin",
        "//models/enums:country",
        "//models/enums:visa_category",
        "//lib/business/vqs:solver",
        "//lib/business/vqs:aggregator",
        "//lib/business/vqs:expert_pool",
        "//lib/business/vqs:seasonal_predictor",
        "//lib/business/vqs:meta_params",
        "//lib/business/vqs:metric_config",
        "//lib/business/vqs:data_cache",
        "//lib/utils:logging_utils",
        "//webapp:apps",
        requirement("Django"),
        requirement("psycopg2_binary"),
    ],
    env = {
        "DJANGO_SETTINGS_MODULE": "django_config.settings",
    },
)
