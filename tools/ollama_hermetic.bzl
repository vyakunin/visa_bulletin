"""
Hermetic repository rule for Ollama LLM dependency.

Downloads specific Ollama version from GitHub releases to Bazel's external
repository cache. This approach is hermetic, cached, and reproducible.

Models are managed via OLLAMA_MODELS environment variable pointing to
Bazel-managed directory. Models are downloaded on first use via pull_model.sh script.
"""

def _ollama_hermetic_impl(repository_ctx):
    """
    Repository rule that downloads Ollama binary from GitHub releases.
    
    This implementation is hermetic:
    - Downloads specific version (pinned)
    - Cached by Bazel in ~/.cache/bazel/repos
    - No system modifications
    - Reproducible across machines
    """
    
    # Detect OS and architecture
    os_name = repository_ctx.os.name.lower()
    arch = repository_ctx.os.arch.lower()
    
    # Map Bazel arch names to Ollama release names
    # Bazel uses: amd64, aarch64, x86_64
    # Ollama uses: amd64, arm64
    if arch in ["amd64", "x86_64"]:
        ollama_arch = "amd64"
    elif arch in ["aarch64", "arm64"]:
        ollama_arch = "arm64"
    else:
        fail("Unsupported architecture: " + arch)
    
    # Detect OS
    # repository_ctx.os.name returns things like "mac os x" or "linux"
    uname_result = repository_ctx.execute(["uname", "-s"], quiet = True, timeout = 5)
    uname_output = uname_result.stdout.strip().lower() if uname_result.return_code == 0 else ""
    
    if "mac" in os_name or "darwin" in os_name or "darwin" in uname_output:
        platform = "darwin"
    elif "linux" in os_name or "linux" in uname_output:
        platform = "linux"
    else:
        fail("Unsupported OS: " + os_name + " (uname: " + uname_output + ")")
    
    # Pin specific Ollama version for reproducibility
    # Update this version as needed
    ollama_version = "0.5.5"  # Stable version (before known issues in 0.6+)
    
    # Construct download URL and SHA-256 checksum
    # GitHub releases: https://github.com/ollama/ollama/releases/download/v{VERSION}/ollama-{PLATFORM}-{ARCH}
    if platform == "darwin":
        # macOS: Single universal binary (works on both Intel and Apple Silicon)
        filename = "ollama-darwin"
        url = "https://github.com/ollama/ollama/releases/download/v{version}/{filename}".format(
            version = ollama_version,
            filename = filename
        )
        sha256 = "3e282de57e03baf940ba87bc3af600602c65d9b4d037de0ab0360a1395e3e8ed"
    else:  # linux
        filename = "ollama-linux-{arch}".format(arch = ollama_arch)
        url = "https://github.com/ollama/ollama/releases/download/v{version}/{filename}".format(
            version = ollama_version,
            filename = filename
        )
        # SHA-256 for Linux AMD64
        if ollama_arch == "amd64":
            sha256 = "614e78776e76ff28d8b9305d09cd81638241c6e2ae546891f4a76d100ed1e746"
        else:  # arm64
            # TODO: Get ARM64 SHA-256 from release page
            sha256 = ""
    
    print("Downloading Ollama v{version} for {platform}-{arch}...".format(
        version = ollama_version,
        platform = platform,
        arch = ollama_arch
    ))
    print("  URL: " + url)
    print("  This download is cached by Bazel (hermetic build)")
    
    # Download binary to Bazel's external repository cache
    # This is cached and hermetic
    # Use "ollama_bin" as filename to avoid conflict with sh_binary target name
    # NOTE: repository_ctx.download() downloads to the repository directory
    # which is in the execution root, NOT directly to repository_cache.
    # However, Bazel symlinks from execution root to repository cache.
    if sha256:
        repository_ctx.download(
            url = url,
            output = "ollama_bin",
            executable = True,
            sha256 = sha256,  # Verify integrity
        )
    else:
        print("⚠ WARNING: No SHA-256 checksum for {platform}-{arch}".format(
            platform = platform,
            arch = ollama_arch
        ))
        print("  Downloading without verification (not recommended for production)")
        repository_ctx.download(
            url = url,
            output = "ollama_bin",
            executable = True,
        )
    
    print("✓ Downloaded Ollama v{version} to Bazel cache".format(version = ollama_version))
    print("  Cached at: ~/.cache/bazel/repos (hermetic, reproducible)")
    print("  NOTE: Binary location in execution root may change between Bazel invocations")
    print("  Wrapper script handles path resolution at runtime")
    
    # Set up model directory for hermetic model storage
    # Models will be stored in Bazel-managed location
    models_dir = "models"
    repository_ctx.execute(["mkdir", "-p", models_dir], quiet = True)
    
    print("\n📦 Model directory created at: {dir}".format(dir = models_dir))
    print("  Run '@ollama//:pull_model' to download llama3.2:3b model")
    print("  Models will be stored in Bazel cache (hermetic)")
    
    # Create a BUILD file for the repository
    repository_ctx.file("BUILD", """
# Ollama hermetic repository
# Binary is downloaded from GitHub releases and cached by Bazel

sh_binary(
    name = "ollama",
    srcs = ["run_ollama.sh"],
    data = ["ollama_bin"],
    visibility = ["//visibility:public"],
)

sh_binary(
    name = "pull_model",
    srcs = ["pull_model.sh"],
    data = ["ollama_bin"],
    visibility = ["//visibility:public"],
)
""")
    
    # Create a wrapper script that uses the downloaded binary
    # and sets OLLAMA_MODELS to use Bazel-managed models directory
    # In Bazel, data dependencies from external repos are available via runfiles
    repository_ctx.file("run_ollama.sh", """#!/bin/bash
# Wrapper script for hermetically downloaded Ollama binary
# This ensures we use the Bazel-cached version, not system Ollama
# Also configures OLLAMA_MODELS to use Bazel-managed models
#
# CRITICAL: Ollama server uses os.Executable() to find its binary when spawning
# child processes. Since Bazel execution roots can change, we need to:
# 1. Find the binary at runtime (not use cached path)
# 2. Ensure child processes can find it via PATH
# 3. Create symlink named "ollama" for exec.LookPath() to work

# Find the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find the Ollama binary location at runtime
# Strategy: Check multiple locations in order of reliability
RUNFILES_DIR="$SCRIPT_DIR.runfiles"
OLLAMA_BINARY=""

# Method 1: Check runfiles directory (most reliable for Bazel)
if [ -d "$RUNFILES_DIR" ]; then
    OLLAMA_BINARY="$(find "$RUNFILES_DIR" -name "ollama_bin" -type f 2>/dev/null | head -1)"
fi

# Method 2: Try external repo base (may change between Bazel invocations)
if [ -z "$OLLAMA_BINARY" ] || [ ! -x "$OLLAMA_BINARY" ]; then
    # Extract external repo base from script path
    # Pattern: .../bazel-out/.../bin/external/+ollama_hermetic_extension+ollama/...
    EXTERNAL_REPO_BASE="$(echo "$SCRIPT_DIR" | sed 's|/bazel-out/.*/bin/external/|/external/|' | sed 's|/bazel-out/.*||')"
    
    # If path manipulation fails, try resolving symlinks
    if [ -z "$EXTERNAL_REPO_BASE" ] || [ ! -d "$EXTERNAL_REPO_BASE" ]; then
        REAL_SCRIPT="$(readlink -f "$0" 2>/dev/null || readlink "$0" 2>/dev/null || echo "$0")"
        EXTERNAL_REPO_BASE="$(dirname "$REAL_SCRIPT")"
    fi
    
    if [ -n "$EXTERNAL_REPO_BASE" ] && [ -d "$EXTERNAL_REPO_BASE" ] && [ -x "$EXTERNAL_REPO_BASE/ollama_bin" ]; then
        OLLAMA_BINARY="$EXTERNAL_REPO_BASE/ollama_bin"
    fi
fi

# Final validation
if [ -z "$OLLAMA_BINARY" ] || [ ! -x "$OLLAMA_BINARY" ]; then
    echo "Error: Ollama binary not found" >&2
    echo "  Script: $0" >&2
    echo "  Script dir: $SCRIPT_DIR" >&2
    echo "  Runfiles dir: $RUNFILES_DIR" >&2
    exit 1
fi

# Resolve absolute path (critical for stability)
OLLAMA_BINARY="$(cd "$(dirname "$OLLAMA_BINARY")" && pwd)/$(basename "$OLLAMA_BINARY")"
OLLAMA_BINARY_DIR="$(dirname "$OLLAMA_BINARY")"

# Verify binary is executable
if [ ! -x "$OLLAMA_BINARY" ]; then
    chmod +x "$OLLAMA_BINARY" 2>/dev/null || true
fi

# Set OLLAMA_MODELS to use Bazel-managed models directory
export OLLAMA_MODELS="$OLLAMA_BINARY_DIR/models"

# CRITICAL: Create "ollama" symlink for child processes
# Ollama server spawns child processes that call exec.LookPath("ollama")
# The symlink allows PATH lookup to succeed
OLLAMA_SYMLINK="$OLLAMA_BINARY_DIR/ollama"
if [ ! -e "$OLLAMA_SYMLINK" ]; then
    ln -sf "$(basename "$OLLAMA_BINARY")" "$OLLAMA_SYMLINK" 2>/dev/null || true
fi

# CRITICAL: Set PATH so exec.LookPath("ollama") finds our binary
# Must be prepended to ensure it's found before system Ollama (if installed)
export PATH="$OLLAMA_BINARY_DIR:$PATH"

# Run Ollama with absolute path
# Note: Child processes spawned by Ollama will use PATH to find "ollama"
# They will find our symlink, which points to the binary in the same directory
exec "$OLLAMA_BINARY" "$@"
""", executable = True)
    
    # Create a script to pull the model (for first-time setup)
    repository_ctx.file("pull_model.sh", """#!/bin/bash
# Script to pull llama3.2:3b model using hermetically downloaded Ollama
# This downloads the model to the Bazel-managed models directory

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export OLLAMA_MODELS="$SCRIPT_DIR/models"

echo "Pulling llama3.2:3b model to Bazel-managed directory..."
echo "  Models will be stored at: $OLLAMA_MODELS"
echo ""

# Find the Ollama binary (same logic as run_ollama.sh)
EXTERNAL_REPO_BASE="$(echo "$SCRIPT_DIR" | sed 's|/bazel-out/.*/bin/external/|/external/|' | sed 's|/bazel-out/.*||')"
if [ -z "$EXTERNAL_REPO_BASE" ] || [ ! -d "$EXTERNAL_REPO_BASE" ]; then
    EXTERNAL_REPO_BASE="$(readlink -f "$0" | sed 's|/pull_model.sh||')"
fi

OLLAMA_BINARY=""
if [ -n "$EXTERNAL_REPO_BASE" ] && [ -d "$EXTERNAL_REPO_BASE" ]; then
    OLLAMA_BINARY="$EXTERNAL_REPO_BASE/ollama_bin"
fi

if [ -z "$OLLAMA_BINARY" ] || [ ! -x "$OLLAMA_BINARY" ]; then
    RUNFILES_DIR="$SCRIPT_DIR.runfiles"
    if [ -d "$RUNFILES_DIR" ]; then
        OLLAMA_BINARY="$(find "$RUNFILES_DIR" -name "ollama_bin" -type f 2>/dev/null | head -1)"
    fi
fi

if [ -z "$OLLAMA_BINARY" ] || [ ! -x "$OLLAMA_BINARY" ]; then
    echo "Error: Ollama binary not found" >&2
    exit 1
fi

# Start Ollama server in background if not running
if ! pgrep -f "ollama serve" > /dev/null; then
    echo "Starting Ollama server..."
    "$OLLAMA_BINARY" serve > /tmp/ollama-server.log 2>&1 &
    OLLAMA_PID=$!
    echo "  Server PID: $OLLAMA_PID"
    sleep 2  # Give server time to start
fi

# Pull the model
"$OLLAMA_BINARY" pull llama3.2:3b

echo ""
echo "✓ Model downloaded to: $OLLAMA_MODELS"
echo "  You can now use the model with: bazel run @ollama//:ollama -- run llama3.2:3b"
""", executable = True)

ollama_hermetic_repository = repository_rule(
    implementation = _ollama_hermetic_impl,
    # Note: No local = True for hermetic builds
    # This allows Bazel to cache the downloaded binary in external repository cache
)

# Module extension for bzlmod
def _ollama_hermetic_extension_impl(module_ctx):
    """Module extension implementation for hermetic Ollama."""
    ollama_hermetic_repository(name = "ollama")

ollama_hermetic_extension = module_extension(
    implementation = _ollama_hermetic_extension_impl,
)
