"""
Repository rule for Homebrew package manager dependency.

NOTE: This implementation is NOT hermetic - it uses system-installed Homebrew
and may auto-install it if missing. For hermetic builds, consider downloading
a specific Homebrew version to Bazel's external repository cache.

Caching: Repository rule checks are cached, but installations are not.
"""

def _homebrew_repository_impl(repository_ctx):
    """Repository rule implementation that ensures Homebrew is available."""
    
    # Check if Homebrew is already installed
    brew_check = repository_ctx.execute(
        ["which", "brew"],
        quiet = True,
        timeout = 5
    )
    
    if brew_check.return_code != 0:
        # Homebrew not found - try to install it
        print("Homebrew not found. Attempting to install...")
        
        # Detect OS - Homebrew only works on macOS and Linux
        os_name = repository_ctx.os.name.lower()
        uname_result = repository_ctx.execute(["uname", "-s"], quiet = True, timeout = 5)
        uname_output = uname_result.stdout.strip().lower() if uname_result.return_code == 0 else ""
        
        if "mac" in os_name or "darwin" in os_name or "darwin" in uname_output:
            # macOS - install Homebrew
            print("Installing Homebrew (this may take several minutes)...")
            install_result = repository_ctx.execute(
                ["bash", "-c", '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'],
                quiet = False,
                timeout = 900  # 15 minutes timeout for Homebrew installation
            )
            if install_result.return_code != 0:
                fail(
                    "Failed to install Homebrew.\n" +
                    "Error: " + install_result.stderr + "\n" +
                    "Please install Homebrew manually: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                )
        elif "linux" in os_name or "linux" in uname_output:
            # Linux - install Homebrew for Linux
            print("Installing Homebrew for Linux (this may take several minutes)...")
            install_result = repository_ctx.execute(
                ["bash", "-c", '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'],
                quiet = False,
                timeout = 900
            )
            if install_result.return_code != 0:
                fail(
                    "Failed to install Homebrew for Linux.\n" +
                    "Error: " + install_result.stderr + "\n" +
                    "Please install Homebrew manually: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""
                )
        else:
            fail(
                "Homebrew is not installed and automatic installation is not supported for this OS.\n" +
                "Please install Homebrew manually: visit https://brew.sh/"
            )
    
    # Verify Homebrew is now available
    verify_check = repository_ctx.execute(["which", "brew"], quiet = True, timeout = 5)
    if verify_check.return_code != 0:
        fail(
            "Homebrew installation verification failed.\n" +
            "Please ensure Homebrew is in your PATH and try again."
        )
    
    brew_path = verify_check.stdout.strip()
    print("✓ Homebrew found at: " + brew_path)
    
    # Get Homebrew prefix (needed for PATH setup)
    prefix_result = repository_ctx.execute(["brew", "--prefix"], quiet = True, timeout = 10)
    brew_prefix = prefix_result.stdout.strip() if prefix_result.return_code == 0 else "/opt/homebrew"
    
    # Create a BUILD file for the repository
    repository_ctx.file("BUILD", """
# Homebrew repository - ensures Homebrew is installed and available
# This is a system dependency, not a Bazel target

exports_files(["brew.sh"])

sh_binary(
    name = "homebrew",
    srcs = ["brew.sh"],
    visibility = ["//visibility:public"],
)

# Alias for convenience
alias(
    name = "brew",
    actual = ":homebrew",
    visibility = ["//visibility:public"],
)
""")
    
    # Create a wrapper script that calls the system Homebrew
    repository_ctx.file("brew.sh", """#!/bin/bash
# Wrapper script for Homebrew binary
# This ensures we use the system-installed Homebrew
exec brew "$@"
""", executable = True)
    
    # Store brew prefix in a file for other rules to use
    repository_ctx.file("prefix.txt", brew_prefix)

homebrew_repository = repository_rule(
    implementation = _homebrew_repository_impl,
    local = True,  # This is a local system dependency
    configure = True,  # Run during configuration phase
    # Note: Auto-installation breaks hermeticity. Consider downloading specific
    # Homebrew version to Bazel cache for true hermetic builds.
)

# Module extension for bzlmod
def _homebrew_extension_impl(module_ctx):
    """Module extension implementation for Homebrew."""
    homebrew_repository(name = "homebrew")

homebrew_extension = module_extension(
    implementation = _homebrew_extension_impl,
)
