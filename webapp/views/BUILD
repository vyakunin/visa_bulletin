load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "prediction_views",
    srcs = ["prediction_views.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//webapp/views/bulletin:dashboard",
        "//webapp/views/bulletin:vqs_api",
        "//webapp/views/employers:directory",
        "//webapp/views/employers:profile",
        "//webapp/views/job_titles:directory",
        "//webapp/views/job_titles:profile",
        "//webapp/views/salary:search",
        "//webapp/views/seo:sitemaps",
        "//webapp/views/static:pages",
        "//models:vqs",
        "//models/enums:country",
        "//models/enums:action_type",
        "//models/enums:visa_category",

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
