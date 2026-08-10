load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "queue_snapshot",
    srcs = ["queue_snapshot.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "coupling",
    srcs = ["coupling.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:country",
    ],
)

py_library(
    name = "demand",
    srcs = ["demand.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":queue_snapshot",
        "//models/enums:country",
    ],
)

py_library(
    name = "estimators",
    srcs = ["estimators.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:country",
    ],
)

# Leaf: the deterministic queue simulation. expert_pool's physics experts need
# exactly this surface, and solver needs expert_pool for the ensemble — keeping
# the engine here is what stops that becoming an import cycle. Deps must stay
# free of solver and expert_pool.
py_library(
    name = "queue_engine",
    srcs = ["queue_engine.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":meta_params",
        ":queue_snapshot",
        "//models/enums:country",
    ],
)

py_library(
    name = "solver",
    srcs = ["solver.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":demand",
        ":estimators",
        ":queue_engine",
        ":fy_transition_model",
        ":queue_snapshot",
        ":regime",
        ":seasonal_predictor",
        "//models:bulletin",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:visa_category",
        ":meta_params",
        ":metric_config",
        ":aggregator",
        ":data_cache",
    ],
)

py_library(
    name = "direction_metrics",
    srcs = ["direction_metrics.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "interval_coverage",
    srcs = ["interval_coverage.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "accuracy_metrics",
    srcs = ["accuracy_metrics.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":metric_config",
        ":seasonal_predictor",
        ":solver",
        "//models:bulletin",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
        ":meta_params",
    ],
)

py_library(
    name = "accuracy_surfacing",
    srcs = ["accuracy_surfacing.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":accuracy_metrics",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:vqs",
    ],
)

py_library(
    name = "reporting",
    srcs = ["reporting.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":accuracy_metrics",
    ],
)

py_library(
    name = "meta_params",
    srcs = ["meta_params.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "metric_config",
    srcs = ["metric_config.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "regime",
    srcs = ["regime.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "data_cache",
    srcs = ["data_cache.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/bulletin:eb_series",
        "//models:bulletin",
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "october_reset",
    srcs = ["october_reset.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        # october_reset.py imports eb_series (EB_CLASSES / resolve_cutoff_label).
        "//lib/business/bulletin:eb_series",
        "//models:published_floor",
        "//models:visa_cutoff_date",
        "//models/enums:country",
    ],
)

py_library(
    name = "expert_pool",
    srcs = ["expert_pool.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":demand",
        ":estimators",
        ":gbm_expert",  # lazy import at expert_pool.py:445
        ":queue_engine",
        ":seasonal_predictor",
        ":data_cache",
        "//models:bulletin",
        "//models:raw_facts",
        "//models/enums:country",
        "//models:visa_cutoff_date",
        "//lib/business/vqs/supply:supply",
    ],
)

py_library(
    name = "aggregator",
    srcs = ["aggregator.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":expert_pool",
        ":metric_config",
        ":regime",
        ":seasonal_predictor",
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "seasonal_predictor",
    srcs = ["seasonal_predictor.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "prediction_loader",
    srcs = ["prediction_loader.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":solver",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models:vqs",
        requirement("python-dateutil"),
    ],
)

py_library(
    name = "fy_utilization",
    srcs = ["fy_utilization.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":estimators",
    ],
)

py_library(
    name = "fy_transition_model",
    srcs = ["fy_transition_model.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":fy_utilization",
        ":seasonal_predictor",
        "//models:raw_facts",
    ],
)

py_library(
    name = "ingest_utils",
    srcs = ["ingest_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/parsing/salary:db_importer",
        "//models/enums:country",
    ],
)

py_library(
    name = "predictors",
    srcs = ["predictors.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":solver",
        ":expert_pool",
        "//models/enums:country",
        "//models:visa_cutoff_date",
        requirement("python-dateutil"),
    ],
)

py_library(
    name = "contextual_aggregator",
    srcs = ["contextual_aggregator.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":predictors",
        ":regime",
        ":seasonal_predictor",
        "//models:visa_cutoff_date",
        requirement("python-dateutil"),
    ],
)

py_library(
    name = "gbm_expert",
    srcs = ["gbm_expert.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":estimators",
        ":regime",
        ":seasonal_predictor",
        "//models:raw_facts",
        "//models/enums:country",
        requirement("lightgbm"),
        requirement("numpy"),
        requirement("scikit_learn"),
    ],
)

py_library(
    name = "calibration",
    srcs = ["calibration.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        ":expert_pool",
        ":regime",
        ":seasonal_predictor",
        "//models:vqs",
        requirement("python-dateutil"),
    ],
)
