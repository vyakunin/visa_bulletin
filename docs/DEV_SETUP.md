# Developer Tools Setup Guide

## Running this project's code — read this before concluding you can't

Nothing here needs a branch cut, a deploy, or a local Django install to exercise
app or model code against real data:

| To do this | Use |
|---|---|
| Run a script/module against a prod-copy DB, **with your uncommitted working tree** | `scripts/vqs/run_in_stg.sh -m scripts.vqs.<module> [args]` — mounts the working tree over `/app` in the same image the staging web container runs, joined to the staging compose network. Details: `PREDICTION_SYSTEM_OVERVIEW.md` §4. |
| Render a page / hit a view with uncommitted code | the same script — drive the Django test client from a module or `-c`; the page renders with your edits, nothing is exposed publicly |
| Build or test | `bazel build //...` / `bazel test //tests:...`. `MODULE.bazel` pins a **hermetic Python 3.11 toolchain**, so a system interpreter of another version is irrelevant. |

"There's no local Django" / "bazel needs a Python I don't have" are statements
about `$PATH`, not about this repo — both were asserted and both were wrong
(2026-07-29). Check the runner before reporting a verification as out of reach.

The rest of this file is workstation bootstrap for a **macOS** dev machine; the
minipc that runs the fleet needs none of it.

## Quick Setup

### Option 1: Automated Setup (Recommended)

Run the setup script:

```bash
./scripts/setup_dev_tools.sh
```

**Note**: This will require your password for sudo access when installing Homebrew.

### Option 2: Manual Setup

#### Step 1: Install Homebrew

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

After installation, add Homebrew to your PATH:

**For Apple Silicon Macs (M1/M2/M3):**
```bash
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
eval "$(/opt/homebrew/bin/brew shellenv)"
```

**For Intel Macs:**
```bash
echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zshrc
eval "$(/usr/local/bin/brew shellenv)"
```

#### Step 2: Install GitHub CLI

```bash
brew install gh
```

#### Step 3: Authenticate GitHub CLI

You have two options:

**Option A: Use existing GITHUB_TOKEN**
```bash
echo $GITHUB_TOKEN | gh auth login --with-token
```

**Option B: Interactive login**
```bash
gh auth login
```

Verify authentication:
```bash
gh auth status
```

## Standard Developer Tools

The setup script will install these essential tools:

### Essential Tools
- **git** - Version control (usually pre-installed)
- **curl** - HTTP client (usually pre-installed)
- **wget** - Alternative HTTP client
- **jq** - JSON processor
- **tree** - Directory tree viewer
- **htop** - Better process viewer
- **tmux** - Terminal multiplexer
- **vim** - Text editor (usually pre-installed)
- **ripgrep** (rg) - Fast text search
- **fd** - Fast file finder
- **bat** - Better cat with syntax highlighting
- **eza** - Modern ls replacement
- **fzf** - Fuzzy finder
- **direnv** - Environment variable management
- **watch** - Execute command periodically
- **ncdu** - Disk usage analyzer
- **tldr** - Simplified man pages

### Optional but Recommended Tools

Install as needed:

```bash
# Container & Orchestration
brew install docker docker-compose
brew install kubectl helm

# Cloud CLI Tools
brew install awscli
brew install --cask google-cloud-sdk

# Languages & Runtimes
brew install node
brew install python@3.11

# Build Tools (for this project)
brew install bazelisk

# Git Tools
brew install pre-commit

# Infrastructure as Code
brew install terraform

# Databases
brew install postgresql redis

# Web Server
brew install nginx
```

## Verify Installation

After setup, verify everything works:

```bash
# Check Homebrew
brew --version

# Check GitHub CLI
gh --version
gh auth status

# Test GitHub access
gh repo view vyakunin/visa_bulletin

# List installed tools
brew list
```

## Troubleshooting

### Homebrew Installation Issues

If Homebrew installation fails:
1. Ensure you have administrator privileges
2. Check Xcode Command Line Tools: `xcode-select --install`
3. Try manual installation from [brew.sh](https://brew.sh)

### GitHub CLI Authentication Issues

If `gh auth login` fails:
1. Check your `GITHUB_TOKEN` is valid: `echo $GITHUB_TOKEN`
2. Try token authentication: `echo $GITHUB_TOKEN | gh auth login --with-token`
3. Check token permissions on GitHub: Settings → Developer settings → Personal access tokens

### PATH Issues

If commands aren't found after installation:
1. Restart your terminal
2. Check your shell config: `cat ~/.zshrc | grep brew`
3. Manually source: `source ~/.zshrc`

### Django Model Resolution Errors

If you see errors like:
```
SystemCheckError: The field models.SalaryRecord.ingest_version was declared with a lazy reference 
to 'models.ingestversion', but app 'models' doesn't provide model 'ingestversion'.
```

**This is a common issue when using ForeignKey references to models in subdirectories.**

**Quick fix:** See `docs/DJANGO_MODEL_RESOLUTION_ISSUE.md` for complete solution.

**Summary:** You need to:
1. Import the model directly in files that reference it
2. Import in `models/__init__.py` for discovery
3. Add Bazel dependency in BUILD file

See the documentation for detailed steps and examples.

## Next Steps

1. ✅ Install Homebrew
2. ✅ Install GitHub CLI
3. ✅ Authenticate with GitHub
4. ✅ Install essential developer tools
5. Install project-specific tools (bazelisk, pre-commit, etc.)

