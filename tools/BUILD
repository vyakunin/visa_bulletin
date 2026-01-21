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