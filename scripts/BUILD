load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

py_binary(
    name = "post_to_reddit",
    srcs = ["post_to_reddit.py"],
    deps = [
        requirement("praw"),
    ],
)

