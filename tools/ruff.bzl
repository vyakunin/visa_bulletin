"""Hermetic, platform-selecting ruff binary for the pre-commit hook + //tools:ruff.

The earlier single-platform http_archive pinned macOS arm64
(ruff-aarch64-apple-darwin), which cannot execute on the x86_64 Linux host
(`Exec format error`) — blocking every commit there. This extension picks the
right GitHub release asset for the BUILD host (mac arm64 / linux x86_64) and
exposes it as @ruff//:ruff_binary, unchanged for callers.
"""

_RUFF_VERSION = "0.14.8"

# (os-substring, normalized-arch) -> (release strip-prefix, sha256)
_RUFF_BUILDS = {
    ("mac", "aarch64"): (
        "ruff-aarch64-apple-darwin",
        "4efc019832a6b9225f650ee256d31b2e875021cae662963d533c78b5cf865f52",
    ),
    ("linux", "amd64"): (
        "ruff-x86_64-unknown-linux-gnu",
        "dce933cd68e3ca69c64c277ce6671dcdee7adeeaa6ac5a15047a4c973b30741f",
    ),
}

_BUILD = 'filegroup(name = "ruff_binary", srcs = ["ruff"], visibility = ["//visibility:public"])'

def _norm_arch(arch):
    arch = arch.lower()
    if arch in ["amd64", "x86_64"]:
        return "amd64"
    if arch in ["aarch64", "arm64"]:
        return "aarch64"
    return arch

def _ruff_repo_impl(repository_ctx):
    os_name = repository_ctx.os.name.lower()
    arch = _norm_arch(repository_ctx.os.arch)
    os_key = "mac" if ("mac" in os_name or "darwin" in os_name) else ("linux" if "linux" in os_name else os_name)
    build = _RUFF_BUILDS.get((os_key, arch))
    if build == None:
        fail("No ruff build for os=%s arch=%s (have: %s)" % (os_name, arch, _RUFF_BUILDS.keys()))
    prefix, sha256 = build
    repository_ctx.download_and_extract(
        url = "https://github.com/astral-sh/ruff/releases/download/{v}/{p}.tar.gz".format(v = _RUFF_VERSION, p = prefix),
        sha256 = sha256,
        stripPrefix = prefix,
        type = "tar.gz",
    )
    repository_ctx.file("BUILD.bazel", _BUILD)

_ruff_repo = repository_rule(implementation = _ruff_repo_impl)

def _ruff_extension_impl(_module_ctx):
    _ruff_repo(name = "ruff")

ruff_extension = module_extension(implementation = _ruff_extension_impl)
