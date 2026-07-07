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

# services.py (remote SSH service mgmt) is used by steps.py for remote/staging
# pipeline runs. The AWS-only instance / traffic_switch / orchestrate modules were
# removed when Lightsail was retired (homeserver + Cloudflare now).
py_library(
    name = "services",
    srcs = ["services.py"],
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
        ":pipeline",
        ":runner",
        ":services",
        ":smoke",
        ":steps",
    ],
)
