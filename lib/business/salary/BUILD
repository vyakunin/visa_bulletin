# Build file for salary business logic
# Following rule: One Bazel target per file

load("@rules_python//python:defs.bzl", "py_library")

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
    name = "employer_clustering",
    srcs = ["employer_clustering.py"],
    deps = [
        ":generic_words",
        "//lib/utils:location_utils",
        "//models:salary",
    ],
    visibility = ["//visibility:public"],
)

py_library(
    name = "clustering_evaluator",
    srcs = ["clustering_evaluator.py"],
    # Note: llm_verifier imported lazily in async methods to avoid circular dependency
    visibility = ["//visibility:public"],
)

py_library(
    name = "llm_verifier",
    srcs = ["llm_verifier.py"],
    deps = [
        ":clustering_evaluator",  # For EmployerPair and EvaluationOutcome dataclasses
        "//lib/utils:bazel_runfiles",  # Standard Bazel runfiles utilities
        "@visa_bulletin_pip//ollama",  # Ollama Python library for HTTP API
    ],
    data = [
        "//scripts/salary:llm_prompt_template.txt",  # Prompt template file
    ],
    visibility = ["//visibility:public"],
    # Clean interface for LLM-based employer pair verification.
    # Provides abstract base class and Ollama implementation.
)

# Convenience target that includes all salary business logic modules
py_library(
    name = "salary",
    srcs = ["__init__.py"],
    deps = [
        ":employer_clustering",
        ":clustering_evaluator",
        ":llm_verifier",
    ],
    visibility = ["//visibility:public"],
)

