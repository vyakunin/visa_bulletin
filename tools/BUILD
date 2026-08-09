# BUILD file for tools directory

load("@rules_python//python:defs.bzl", "py_binary", "py_library")
load("@visa_bulletin_pip//:requirements.bzl", "requirement")

exports_files([
    "update_requirements_lock.sh",
    "bazel_dep_check.py",
])

# The tracked pre-commit gate. Installed into $GIT_COMMON_DIR/hooks by
# scripts/install_git_hooks.sh; exported so //tests:test_pre_commit_hook can run
# the real script rather than a copy of its logic.
exports_files(["hooks/pre-commit"])

# Undeclared-Bazel-dep checker. Stdlib only, so the pre-commit hook can run it
# with plain python3 against the real working tree — Bazel's glob() cannot cross
# package boundaries, so a sandboxed target can never see all 45 BUILD files.
# The logic is pinned by //tests:test_bazel_dep_check.
py_library(
    name = "bazel_dep_check",
    srcs = ["bazel_dep_check.py"],
    visibility = ["//visibility:public"],
)

py_binary(
    name = "update_requirements_lock",
    srcs = ["update_requirements_lock.py"],
    python_version = "PY3",
    deps = [],
    visibility = ["//visibility:public"],
)

# Ruff is now provided by http_archive (@ruff//:ruff_binary)
# Generate wrapper script with dynamic binary resolution
genrule(
    name = "ruff_wrapper",
    outs = ["ruff.sh"],
    cmd = """cat > $@ <<'EOF'
#!/bin/bash
# Find ruff binary in runfiles (works regardless of repository name)
set -e
RUFF_BINARY="$$(find "$${0}.runfiles" -name "ruff" | grep -v "_main/tools/ruff$$" | head -1)"
if [ -z "$$RUFF_BINARY" ]; then
  echo "Error: Could not find ruff binary in runfiles" >&2
  exit 1
fi
exec "$${RUFF_BINARY}" "$$@"
EOF
chmod +x $@""",
    executable = True,
)

sh_binary(
    name = "ruff",
    srcs = [":ruff_wrapper"],
    data = ["@ruff//:ruff_binary"],
    visibility = ["//visibility:public"],
)
