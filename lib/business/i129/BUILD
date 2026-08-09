# Build file for I-129 petition business logic (actual-pay comparison).
# Following rule: One Bazel target per file.

load("@rules_python//python:defs.bzl", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

# All .py files in this dir. If __init__.py is added, no_init_check fails the build.
filegroup(
    name = "all_py",
    srcs = glob(["*.py"]),
    visibility = ["//tests:__pkg__"],
)

# Fails the build if __init__.py is in this directory (enforces no __init__.py rule).
genrule(
    name = "no_init_check",
    srcs = [":all_py"],
    outs = ["no_init_ok.txt"],
    cmd = "for f in $(SRCS); do if [ \"$$(basename $$f)\" = \"__init__.py\" ]; then echo '__init__.py must not exist in lib/business/i129. See .cursor/rules/general_code_health.mdc' >&2; exit 1; fi; done; touch $(OUTS)",
    visibility = ["//tests:__pkg__"],
)

py_library(
    name = "pay_comparison",
    srcs = ["pay_comparison.py"],
    deps = [
        "//lib/business/salary:soc_occupations",
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "employer_linker",
    srcs = ["employer_linker.py"],
    deps = [
        "//models:i129",
        "//models:salary",
        "//models:uscis_employer",
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "approval_stats",
    srcs = ["approval_stats.py"],
    deps = [
        "//models:uscis_employer",
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "demographic_pay",
    srcs = ["demographic_pay.py"],
    deps = [
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "demographic_pay_panel",
    srcs = ["demographic_pay_panel.py"],
    deps = [
        ":demographic_pay",
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)
