"""
Repository rule and module extension for Ollama LLM dependency.

⚠️ DEPRECATED: This implementation is NOT hermetic and is superseded by ollama_hermetic.bzl.

This uses system-installed Ollama via Homebrew or manual installation.
For hermetic builds (recommended), use ollama_hermetic.bzl which downloads
a specific Ollama binary version to Bazel's external repository cache.

This file is kept for reference but should not be used in new code.
See MODULE.bazel for the current hermetic implementation.
"""

def _ollama_repository_impl(repository_ctx):
    """Repository rule implementation that ensures Ollama is available."""
    
    # Check if Ollama is already installed
    ollama_check = repository_ctx.execute(
        ["which", "ollama"],
        quiet = True,
        timeout = 5
    )
    
    if ollama_check.return_code != 0:
        # Ollama not found - try to install it
        print("Ollama not found. Attempting to install...")
        
        # Detect OS and install accordingly
        # repository_ctx.os.name returns "mac os x" for macOS, "linux" for Linux
        os_name = repository_ctx.os.name.lower()
        uname_result = repository_ctx.execute(["uname", "-s"], quiet = True, timeout = 5)
        uname_output = uname_result.stdout.strip().lower() if uname_result.return_code == 0 else ""
        
        if "mac" in os_name or "darwin" in os_name or "darwin" in uname_output:
            # macOS - use Homebrew (which should be installed via @homebrew dependency)
            # Check if Homebrew is available (it should be, but verify)
            brew_check = repository_ctx.execute(["which", "brew"], quiet = True, timeout = 5)
            if brew_check.return_code == 0:
                print("Installing Ollama via Homebrew (this may take a few minutes)...")
                # Use bash -c to ensure we're using the system PATH
                install_result = repository_ctx.execute(
                    ["bash", "-c", "brew install ollama"],
                    quiet = False,
                    timeout = 600  # 10 minutes timeout for installation
                )
                if install_result.return_code != 0:
                    fail(
                        "Failed to install Ollama via Homebrew.\n" +
                        "Error: " + install_result.stderr + "\n" +
                        "Please install manually: brew install ollama"
                    )
            else:
                fail(
                    "Ollama is not installed and Homebrew is not available.\n" +
                    "Homebrew should have been installed automatically. Please check the @homebrew repository.\n" +
                    "Or install manually: brew install ollama"
                )
        elif "linux" in os_name:
            # Linux - use curl script from Ollama
            print("Installing Ollama via official installer (this may take a few minutes)...")
            install_result = repository_ctx.execute(
                ["bash", "-c", "curl -fsSL https://ollama.ai/install.sh | sh"],
                quiet = False,
                timeout = 600
            )
            if install_result.return_code != 0:
                fail(
                    "Failed to install Ollama.\n" +
                    "Error: " + install_result.stderr + "\n" +
                    "Please install manually: curl -fsSL https://ollama.ai/install.sh | sh"
                )
        else:
            fail(
                "Ollama is not installed and automatic installation is not supported for this OS.\n" +
                "Please install Ollama manually: visit https://ollama.ai/"
            )
    
    # Verify Ollama is now available
    verify_check = repository_ctx.execute(["which", "ollama"], quiet = True)
    if verify_check.return_code != 0:
        fail(
            "Ollama installation verification failed.\n" +
            "Please ensure Ollama is in your PATH and try again."
        )
    
    ollama_path = verify_check.stdout.strip()
    print("✓ Ollama found at: " + ollama_path)
    
    # Check if a model is available (try listing models)
    # This might fail if Ollama service isn't running, which is OK
    model_check = repository_ctx.execute(["ollama", "list"], quiet = True, timeout = 10)
    if model_check.return_code != 0:
        # Ollama might not be running - that's OK, we'll handle it at runtime
        print("Note: Ollama service may not be running. Start with: ollama serve")
    else:
        # Check if a suitable model exists
        if "llama3.2:3b" not in model_check.stdout and "mistral" not in model_check.stdout:
            print("Note: No suitable model found. Install with: ollama pull llama3.2:3b")
    
    # Create a BUILD file for the repository
    repository_ctx.file("BUILD", """
# Ollama repository - ensures Ollama is installed and available
# This is a system dependency, not a Bazel target

exports_files(["ollama.sh"])

sh_binary(
    name = "ollama",
    srcs = ["ollama.sh"],
    visibility = ["//visibility:public"],
)
""")
    
    # Create a wrapper script that calls the system Ollama
    repository_ctx.file("ollama.sh", """#!/bin/bash
# Wrapper script for Ollama binary
# This ensures we use the system-installed Ollama
exec ollama "$@"
""", executable = True)

ollama_repository = repository_rule(
    implementation = _ollama_repository_impl,
    local = True,  # This is a local system dependency
    configure = True,  # Run during configuration phase
    # Note: Auto-installation breaks hermeticity. Consider downloading specific
    # Ollama binary version to Bazel cache for true hermetic builds.
)

# Module extension for bzlmod
def _ollama_extension_impl(module_ctx):
    """
    Module extension implementation for Ollama.
    
    Note: This depends on @homebrew being available. Ensure homebrew extension
    is loaded before ollama extension in MODULE.bazel.
    """
    # Homebrew should already be set up by the homebrew_extension
    # We can verify it's available by checking for the repository
    ollama_repository(name = "ollama")

ollama_extension = module_extension(
    implementation = _ollama_extension_impl,
    # Tag classes can be used to declare dependencies, but for now we rely on
    # MODULE.bazel ordering to ensure Homebrew is set up first
)
