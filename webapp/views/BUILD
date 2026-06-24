load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "views",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//webapp/views/bulletin:dashboard",
        "//webapp/views/employers:directory",
        "//webapp/views/employers:profile",
        "//webapp/views/employers:rankings",
        "//webapp/views/job_titles:directory",
        "//webapp/views/job_titles:profile",
        "//webapp/views/salary:by_state",
        "//webapp/views/salary:h1b_sponsors",
        "//webapp/views/salary:search",
        "//webapp/views/seo:sitemaps",
        "//webapp/views/static:pages",
    ],
)

py_library(
    name = "prediction_views",
    srcs = ["prediction_views.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/vqs:prediction_loader",
        "//models:bulletin",
        "//models:visa_cutoff_date",
        "//models/enums:country",
        "//models/enums:family_preference",
        "//models/enums:visa_category",
        "//webapp/views/bulletin:prediction_month_forecast",
    ],
)

py_library(
    name = "blog_views",
    srcs = ["blog_views.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//models:blog",
    ],
)
