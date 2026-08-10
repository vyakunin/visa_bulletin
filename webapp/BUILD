load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_library(
    name = "apps",
    srcs = ["apps.py"],
    visibility = ["//visibility:public"],
    deps = [
        # ready() lazily imports these (apps.py:43-45) to warm the VQS solver.
        "//lib/business/vqs:solver",
        "//models:bulletin",
        "//models/enums:country",
        requirement("Django"),
        # apps.py:ready() eagerly imports numpy so gunicorn --preload loads it once
        # in the master (CoW-shared to workers), avoiding the per-request numpy
        # first-import thread race in the GBM VQS expert.
        requirement("numpy"),
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
        "//webapp/views/bulletin:prediction_month_forecast",
        "//webapp/views/bulletin:priority_date_calculator",
        "//webapp/views/bulletin:priority_date_landing",
        "//webapp/views/bulletin:priority_date_rollup",
        "//webapp/views/bulletin:vqs_api",
        "//webapp/views/employers:directory",
        "//webapp/views/employers:profile",
        "//webapp/views/employers:rankings",
        "//webapp/views/job_titles:directory",
        "//webapp/views/job_titles:profile",
        "//webapp/views/lottery:h1b_lottery",
        "//webapp/views/salary:by_state",
        "//webapp/views/salary:h1b_salary_pair",
        "//webapp/views/salary:h1b_sponsors",
        "//webapp/views/salary:occupation",
        "//webapp/views/salary:search",
        "//webapp/views/static:pages",
        "//webapp/views/static:spanish",
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
