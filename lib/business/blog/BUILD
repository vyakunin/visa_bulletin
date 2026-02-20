load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "blog",
    srcs = glob(["*.py"]),
    visibility = ["//visibility:public"],
    deps = [
        "//models:bulletin",
        "//models:vqs",
        "//models:blog",
        "//models:visa_cutoff_date",
        "//models/enums:visa_category",
        "//models/enums:country",
    ],
)
