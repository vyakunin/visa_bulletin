"""
Repository rule to create @ollama repository with cross-platform Ollama targets.

Uses platform-specific http_file repositories with select() to choose the correct binary.
"""

def _ollama_repository_impl(repository_ctx):
    # Create BUILD file with cross-platform Ollama targets
    repository_ctx.file("BUILD", """
# Ollama hermetic repository - cross-platform using select()
# Uses platform-specific http_file repositories declared in MODULE.bazel

# Platform and architecture detection for selecting the correct Ollama binary
config_setting(
    name = "macos_arm64",
    constraint_values = [
        "@platforms//os:macos",
        "@platforms//cpu:aarch64",
    ],
)

config_setting(
    name = "macos_x86_64",
    constraint_values = [
        "@platforms//os:macos",
        "@platforms//cpu:x86_64",
    ],
)

config_setting(
    name = "linux_x86_64",
    constraint_values = [
        "@platforms//os:linux",
        "@platforms//cpu:x86_64",
    ],
)

config_setting(
    name = "linux_arm64",
    constraint_values = [
        "@platforms//os:linux",
        "@platforms//cpu:aarch64",
    ],
)

# Generate wrapper script for running Ollama
genrule(
    name = "run_ollama_sh",
    outs = ["run_ollama.sh"],
    cmd = \"\"\"cat > $@ <<'EOF'
#!/bin/bash
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
SCRIPT_DIR="$$(cd "$$(dirname "$$0")" && pwd)"

# Find the Ollama binary location at runtime
# Strategy: Check multiple locations in order of reliability
RUNFILES_DIR="$$SCRIPT_DIR.runfiles"
OLLAMA_BINARY=""

# Method 1: Check runfiles directory (most reliable for Bazel)
if [ -d "$$RUNFILES_DIR" ]; then
    OLLAMA_BINARY="$$(find "$$RUNFILES_DIR" -name "ollama_bin" -type f 2>/dev/null | head -1)"
fi

# Method 2: Try external repo base (may change between Bazel invocations)
if [ -z "$$OLLAMA_BINARY" ] || [ ! -x "$$OLLAMA_BINARY" ]; then
    # Extract external repo base from script path
    # Pattern: .../bazel-out/.../bin/external/+repo_name+ollama_bin
    EXTERNAL_REPO_BASE="$$(echo "$$SCRIPT_DIR" | sed 's|/bazel-out/.*/bin/external/|/external/|' | sed 's|/bazel-out/.*||')"
    
    # If path manipulation fails, try resolving symlinks
    if [ -z "$$EXTERNAL_REPO_BASE" ] || [ ! -d "$$EXTERNAL_REPO_BASE" ]; then
        REAL_SCRIPT="$$(readlink -f "$$0" 2>/dev/null || readlink "$$0" 2>/dev/null || echo "$$0")"
        EXTERNAL_REPO_BASE="$$(dirname "$$REAL_SCRIPT")"
    fi
    
    if [ -n "$$EXTERNAL_REPO_BASE" ] && [ -d "$$EXTERNAL_REPO_BASE" ] && [ -x "$$EXTERNAL_REPO_BASE/ollama_bin" ]; then
        OLLAMA_BINARY="$$EXTERNAL_REPO_BASE/ollama_bin"
    fi
fi

# Final validation
if [ -z "$$OLLAMA_BINARY" ] || [ ! -x "$$OLLAMA_BINARY" ]; then
    echo "Error: Ollama binary not found" >&2
    echo "  Script: $$0" >&2
    echo "  Script dir: $$SCRIPT_DIR" >&2
    echo "  Runfiles dir: $$RUNFILES_DIR" >&2
    exit 1
fi

# Resolve absolute path (critical for stability)
OLLAMA_BINARY="$$(cd "$$(dirname "$$OLLAMA_BINARY")" && pwd)/$$(basename "$$OLLAMA_BINARY")"
OLLAMA_BINARY_DIR="$$(dirname "$$OLLAMA_BINARY")"

# Verify binary is executable
if [ ! -x "$$OLLAMA_BINARY" ]; then
    chmod +x "$$OLLAMA_BINARY" 2>/dev/null || true
fi

# Set OLLAMA_MODELS to use Bazel-managed models directory
export OLLAMA_MODELS="$$OLLAMA_BINARY_DIR/models"

# CRITICAL: Create "ollama" symlink for child processes
# Ollama server spawns child processes that call exec.LookPath("ollama")
# The symlink allows PATH lookup to succeed
OLLAMA_SYMLINK="$$OLLAMA_BINARY_DIR/ollama"
if [ ! -e "$$OLLAMA_SYMLINK" ]; then
    ln -sf "$$(basename "$$OLLAMA_BINARY")" "$$OLLAMA_SYMLINK" 2>/dev/null || true
fi

# CRITICAL: Set PATH so exec.LookPath("ollama") finds our binary
# Must be prepended to ensure it's found before system Ollama (if installed)
export PATH="$$OLLAMA_BINARY_DIR:$$PATH"

# Run Ollama with absolute path
# Note: Child processes spawned by Ollama will use PATH to find "ollama"
# They will find our symlink, which points to the binary in the same directory
exec "$$OLLAMA_BINARY" "$$@"
EOF
chmod +x $@\"\"\",
    executable = True,
)

# Generate script to pull models
genrule(
    name = "pull_model_sh",
    outs = ["pull_model.sh"],
    cmd = \"\"\"cat > $@ <<'EOF'
#!/bin/bash
# Script to pull llama3.2:3b model using hermetically downloaded Ollama
# This downloads the model to the Bazel-managed models directory

SCRIPT_DIR="$$(cd "$$(dirname "$$0")" && pwd)"
export OLLAMA_MODELS="$$SCRIPT_DIR/models"

echo "Pulling llama3.2:3b model to Bazel-managed directory..."
echo "  Models will be stored at: $$OLLAMA_MODELS"
echo ""

# Find the Ollama binary (same logic as run_ollama.sh)
RUNFILES_DIR="$$SCRIPT_DIR.runfiles"
OLLAMA_BINARY=""

if [ -d "$$RUNFILES_DIR" ]; then
    OLLAMA_BINARY="$$(find "$$RUNFILES_DIR" -name "ollama_bin" -type f 2>/dev/null | head -1)"
fi

if [ -z "$$OLLAMA_BINARY" ] || [ ! -x "$$OLLAMA_BINARY" ]; then
    EXTERNAL_REPO_BASE="$$(echo "$$SCRIPT_DIR" | sed 's|/bazel-out/.*/bin/external/|/external/|' | sed 's|/bazel-out/.*||')"
    if [ -z "$$EXTERNAL_REPO_BASE" ] || [ ! -d "$$EXTERNAL_REPO_BASE" ]; then
        EXTERNAL_REPO_BASE="$$(readlink -f "$$0" | sed 's|/pull_model.sh||')"
    fi
    if [ -n "$$EXTERNAL_REPO_BASE" ] && [ -d "$$EXTERNAL_REPO_BASE" ] && [ -x "$$EXTERNAL_REPO_BASE/ollama_bin" ]; then
        OLLAMA_BINARY="$$EXTERNAL_REPO_BASE/ollama_bin"
    fi
fi

if [ -z "$$OLLAMA_BINARY" ] || [ ! -x "$$OLLAMA_BINARY" ]; then
    echo "Error: Ollama binary not found" >&2
    exit 1
fi

# Start Ollama server in background if not running
if ! pgrep -f "ollama serve" > /dev/null; then
    echo "Starting Ollama server..."
    "$$OLLAMA_BINARY" serve > /tmp/ollama-server.log 2>&1 &
    OLLAMA_PID=$$!
    echo "  Server PID: $$OLLAMA_PID"
    sleep 2  # Give server time to start
fi

# Pull the model
"$$OLLAMA_BINARY" pull llama3.2:3b

echo ""
echo "✓ Model downloaded to: $$OLLAMA_MODELS"
echo "  You can now use the model with: bazel run @ollama//:ollama -- run llama3.2:3b"
EOF
chmod +x $@\"\"\",
    executable = True,
)

# Main Ollama binary target - uses select() to choose platform-specific repository
# Note: macOS uses universal binary (works on both Intel and Apple Silicon)
# http_file creates a filegroup named "file" containing the downloaded file
sh_binary(
    name = "ollama",
    srcs = [":run_ollama_sh"],
    data = select({
        ":macos_arm64": ["@ollama_macos_arm64//file"],
        ":macos_x86_64": ["@ollama_macos_arm64//file"],  # Universal binary
        ":linux_x86_64": ["@ollama_linux_x86_64//file"],
        ":linux_arm64": ["@ollama_linux_arm64//file"],
        "//conditions:default": ["@ollama_linux_x86_64//file"],
    }),
    visibility = ["//visibility:public"],
)

# Pull model target
sh_binary(
    name = "pull_model",
    srcs = [":pull_model_sh"],
    data = select({
        ":macos_arm64": ["@ollama_macos_arm64//file"],
        ":macos_x86_64": ["@ollama_macos_arm64//file"],  # Universal binary
        ":linux_x86_64": ["@ollama_linux_x86_64//file"],
        ":linux_arm64": ["@ollama_linux_arm64//file"],
        "//conditions:default": ["@ollama_linux_x86_64//file"],
    }),
    visibility = ["//visibility:public"],
)
""")

ollama_repository = repository_rule(
    implementation = _ollama_repository_impl,
)
