load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "apps",
    srcs = ["apps.py"],
    visibility = ["//visibility:public"],
    deps = [
        requirement("Django"),
    ],
)

py_library(
    name = "urls",
    srcs = ["urls.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//webapp/views:prediction_views",
        "//webapp/views:blog_views",
        "//webapp/views/bulletin:dashboard",
        "//webapp/views/bulletin:vqs_api",
        "//webapp/views/employers:directory",
        "//webapp/views/employers:profile",
        "//webapp/views/job_titles:directory",
        "//webapp/views/job_titles:profile",
        "//webapp/views/salary:search",
        "//webapp/views/static:pages",
        requirement("Django"),
    ],
)

py_library(
    name = "forms",
    srcs = ["forms.py"],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/utils:location_utils",
        requirement("Django"),
    ],
)

filegroup(
    name = "templates",
    srcs = glob(["templates/**/*.html"]),
    visibility = ["//visibility:public"],
)

# Force rebuild
# Force rebuild 2
# Force rebuild 3
# Force rebuild 4
# Force rebuild 5
# Force rebuild 6
# Force rebuild 7
# Force rebuild 8
# Force rebuild 9
# Force rebuild 10
# Force rebuild 11
