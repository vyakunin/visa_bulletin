load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "views",
    srcs = ["__init__.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//webapp/views/bulletin:dashboard",
        "//webapp/views/employers:directory",
        "//webapp/views/employers:profile",
        "//webapp/views/job_titles:directory",
        "//webapp/views/job_titles:profile",
        "//webapp/views/salary:search",
        "//webapp/views/seo:sitemaps",
        "//webapp/views/static:pages",
    ],
)
