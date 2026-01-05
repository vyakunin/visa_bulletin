# BUILD file for tools directory

load("@rules_python//python:defs.bzl", "py_binary")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "update_requirements_lock.sh",
])

py_binary(
    name = "update_requirements_lock",
    srcs = ["update_requirements_lock.py"],
    python_version = "PY3",
    deps = [],
    visibility = ["//visibility:public"],
)

# Ruff is now provided by http_archive (@ruff//:ruff_binary)
# Generate wrapper script and use it with sh_binary
genrule(
    name = "ruff_wrapper",
    outs = ["ruff.sh"],
    cmd = "echo '#!/bin/bash' > $@ && echo 'exec \"$${0}.runfiles/+_repo_rules+ruff/ruff\" \"$$@\"' >> $@",
    executable = True,
)

sh_binary(
    name = "ruff",
    srcs = [":ruff_wrapper"],
    data = ["@ruff//:ruff_binary"],
    visibility = ["//visibility:public"],
)

