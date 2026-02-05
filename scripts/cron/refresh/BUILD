# scripts/cron/refresh - pipeline and orchestrator (no __init__.py)

load("@rules_python//python:defs.bzl", "py_library")

py_library(
    name = "config",
    srcs = ["config.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "checkpoint",
    srcs = ["checkpoint.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "runner",
    srcs = ["runner.py"],
    deps = [":checkpoint", ":config"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "disk",
    srcs = ["disk.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "discovery",
    srcs = ["discovery.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "smoke",
    srcs = ["smoke.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "steps",
    srcs = ["steps.py"],
    deps = [":config", ":runner", ":smoke"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "pipeline",
    srcs = ["pipeline.py"],
    deps = [":checkpoint", ":config", ":discovery", ":steps"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "instance",
    srcs = ["instance.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "traffic_switch",
    srcs = ["traffic_switch.py"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

py_library(
    name = "orchestrate",
    srcs = ["orchestrate.py"],
    deps = [":config", ":instance", ":pipeline", ":runner", ":traffic_switch"],
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
)

# Aggregate for entry point binaries
py_library(
    name = "refresh",
    visibility = ["//scripts/cron:__pkg__", "//tests:__pkg__"],
    deps = [
        ":checkpoint",
        ":config",
        ":discovery",
        ":disk",
        ":instance",
        ":orchestrate",
        ":pipeline",
        ":runner",
        ":smoke",
        ":steps",
        ":traffic_switch",
    ],
)
