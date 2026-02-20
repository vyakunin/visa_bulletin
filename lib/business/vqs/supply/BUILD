load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "supply",
    srcs = [
        "__init__.py",
        "allocator.py",
        "cascade.py",
        "country_cap.py",
        "fb_spillover.py",
    ],
    visibility = ["//visibility:public"],
    deps = [
        "//lib/business/vqs:estimators",
        "//lib/business/vqs:data_cache",
        "//models/enums:country",
    ],
)
