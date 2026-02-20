load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "queue_snapshot",
    srcs = ["queue_snapshot.py"],
    visibility = ["//visibility:public"],
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

py_library(
    name = "solver",
    srcs = ["solver.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":demand",
        ":estimators",
        ":queue_snapshot",
        ":seasonal_predictor",
        "//models:bulletin",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
        "//models/enums:action_type",
        "//models/enums:country",
        "//models/enums:visa_category",
        ":meta_params",
        ":aggregator",
        ":data_cache",
    ],
)

py_library(
    name = "accuracy_metrics",
    srcs = ["accuracy_metrics.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":solver",
        "//models:bulletin",
        "//models:raw_facts",
        "//models:visa_cutoff_date",
        ":meta_params",
    ],
)

py_library(
    name = "meta_params",
    srcs = ["meta_params.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "data_cache",
    srcs = ["data_cache.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:bulletin",
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "expert_pool",
    srcs = ["expert_pool.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":seasonal_predictor",
        ":data_cache",
        "//models:bulletin",
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
    ],
)

py_library(
    name = "seasonal_predictor",
    srcs = ["seasonal_predictor.py"],
    visibility = ["//visibility:public"],
    deps = [
        ":data_cache",
        "//models:visa_cutoff_date",
    ],
)

py_library(
    name = "ingest_utils",
    srcs = ["ingest_utils.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models/enums:country",
    ],
)
