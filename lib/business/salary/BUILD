# Build file for salary business logic
# Following rule: One Bazel target per file

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
    cmd = "for f in $(SRCS); do if [ \"$$(basename $$f)\" = \"__init__.py\" ]; then echo '__init__.py must not exist in lib/business/salary. See .cursor/rules/general_code_health.mdc' >&2; exit 1; fi; done; touch $(OUTS)",
    visibility = ["//tests:__pkg__"],
)

py_library(
    name = "generic_words",
    srcs = ["generic_words.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "cluster_utils",
    srcs = ["cluster_utils.py"],
    visibility = ["//visibility:public"],
)

py_library(
    name = "employer_config",
    srcs = ["employer_config.py"],
    deps = [
        ":generic_words",
        "//lib/utils:location_utils",
        "//models:salary",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "job_title_config",
    srcs = ["job_title_config.py"],
    deps = [
        ":generic_words",
        "//models:job_title",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "employer_clustering",
    srcs = ["employer_clustering.py"],
    deps = [
        ":employer_config",
        ":generic_words",
        "//lib/business:clustering_engine",
        "//lib/utils:location_utils",
        "//models:salary",
        "@visa_bulletin_pip//rapidfuzz",
    ],
    visibility = ["//visibility:public"],
)

# clustering_evaluator + llm_verifier removed 2026-06-20 with the Ollama LLM
# employer-pair verifier (Ollama retired; live clustering is rule-based + fuzzy).

py_library(
    name = "job_title_stats",
    srcs = ["job_title_stats.py"],
    deps = [
        ":common_stats",
        "//models:salary",
        "//models:job_title",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "employer_stats",
    srcs = ["employer_stats.py"],
    deps = [
        "//models:salary",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "similar_titles",
    srcs = ["similar_titles.py"],
    deps = [
        ":job_title_stats",
        "//models:job_title",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "slug_redirects",
    srcs = ["slug_redirects.py"],
    deps = [
        "//models:job_title",
        "//models:salary",
    ],
    visibility = ["//visibility:public"],
)

exports_files(["employer_renames.yaml"])

py_library(
    name = "employer_renames",
    srcs = ["employer_renames.py"],
    data = [":employer_renames.yaml"],
    deps = [
        ":slug_redirects",
        "//lib/utils:bazel_runfiles",
        "//models:salary",
        requirement("pyyaml"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "common_stats",
    srcs = ["common_stats.py"],
    deps = [
        "//models/enums:visa_program",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "h1b_sponsors",
    srcs = ["h1b_sponsors.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "h1b_salary_pair",
    srcs = ["h1b_salary_pair.py"],
    deps = [
        "//models:salary",
        "//models/enums:visa_program",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "job_title_chart_builder",
    srcs = ["job_title_chart_builder.py"],
    deps = [
        ":common_chart_builder",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "common_chart_builder",
    srcs = ["common_chart_builder.py"],
    deps = [
        "@visa_bulletin_pip//plotly",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "market_overview",
    srcs = ["market_overview.py"],
    deps = [
        ":common_stats",
        "//models:salary",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "soc_occupations",
    srcs = ["soc_occupations.py"],
    deps = [
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "occupation_stats",
    srcs = ["occupation_stats.py"],
    deps = [
        ":common_stats",
        ":soc_occupations",
        "//models:salary",
        requirement("Django"),
    ],
    visibility = ["//visibility:public"],
)
