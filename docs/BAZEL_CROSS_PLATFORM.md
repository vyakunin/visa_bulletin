# Bazel Cross-Platform Binary Patterns

For cross-platform binaries, declare platform-specific repositories in `MODULE.bazel` and use `select()` in BUILD files. Bazel lazily fetches only the platform needed.

**Quick reference:**
- **Tarballs** → `http_archive` per platform
- **Single binaries** → `http_file` per platform (`http_file` target = `@repo//file`, not `//:file`)
- **Platform selection** → `select()` with `@platforms//os:*` or `config_setting` for arch-specific
- **Wrapper scripts** → `genrule` + `find` for dynamic binary location
- **Never** use module extensions for simple cross-platform downloads

## Pattern: Tarballs (http_archive)

```python
# MODULE.bazel
http_archive = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_archive")
http_archive(name = "tool_macos_arm64", urls = ["...darwin.tar.gz"], sha256 = "...",
    type = "tar.gz", strip_prefix = "tool-darwin",
    build_file_content = "filegroup(name = \"tool_binary\", srcs = [\"tool\"], visibility = [\"//visibility:public\"])")
http_archive(name = "tool_linux_x86_64", urls = ["...linux.tar.gz"], sha256 = "...",
    type = "tar.gz", strip_prefix = "tool-linux",
    build_file_content = "filegroup(name = \"tool_binary\", srcs = [\"tool\"], visibility = [\"//visibility:public\"])")
```

## Pattern: Single Binaries (http_file)

```python
# MODULE.bazel
http_file = use_repo_rule("@bazel_tools//tools/build_defs/repo:http.bzl", "http_file")
http_file(name = "tool_macos_arm64", urls = ["...tool-darwin"], sha256 = "...",
    downloaded_file_path = "tool_bin", executable = True)
http_file(name = "tool_linux_x86_64", urls = ["...tool-linux-amd64"], sha256 = "...",
    downloaded_file_path = "tool_bin", executable = True)
```

## Pattern: select() + genrule Wrapper

Use `genrule` to generate wrapper scripts (no separate .sh files). For cross-platform, use `find` since repository names differ per platform:

```python
# tools/BUILD
config_setting(name = "macos_arm64", constraint_values = ["@platforms//os:macos", "@platforms//cpu:aarch64"])
config_setting(name = "linux_x86_64", constraint_values = ["@platforms//os:linux", "@platforms//cpu:x86_64"])

genrule(
    name = "tool_wrapper", outs = ["tool.sh"],
    cmd = """cat > $@ <<'EOF'
#!/bin/bash
set -e
TOOL_BINARY="$$(find "$${0}.runfiles" -name "tool" -type f | head -1)"
[ -z "$$TOOL_BINARY" ] && { echo "Error: tool binary not found" >&2; exit 1; }
exec "$${TOOL_BINARY}" "$$@"
EOF
chmod +x $@""",
    executable = True,
)

sh_binary(
    name = "tool", srcs = [":tool_wrapper"],
    data = select({
        ":macos_arm64": ["@tool_macos_arm64//file"],
        ":linux_x86_64": ["@tool_linux_x86_64//file"],
        "//conditions:default": ["@tool_linux_x86_64//file"],
    }),
    visibility = ["//visibility:public"],
)
```

For single-platform (single repo), hardcode the runfiles path instead of `find`:
```python
cmd = "echo '#!/bin/bash' > $@ && echo 'exec \"$${0}.runfiles/+_repo_rules+ruff/ruff\" \"$$@\"' >> $@",
```

## Project Examples

**Ollama** (single binaries → `http_file` + `select()`):
```python
# MODULE.bazel: http_file(name = "ollama_macos_arm64|linux_x86_64|linux_arm64", ...)
# tools/ollama/BUILD: select() across 3 platforms + config_settings
```

**Ruff** (tarballs → `http_archive`, needs cross-platform update):
```python
# Should add per-platform http_archive + select() like Ollama
```

**Reference:** See `docs/CROSS_PLATFORM_RUFF_ANALYSIS.md` for full implementation guide.
