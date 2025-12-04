# Developer Tools Setup Guide

## Current Status

✅ **GitHub Authentication**: Working
- `GITHUB_TOKEN` is set and accessible
- Git can access GitHub repositories
- Git credential helper is configured (osxkeychain)

❌ **Homebrew**: Not installed
❌ **GitHub CLI (gh)**: Not installed

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

## Next Steps

1. ✅ Install Homebrew
2. ✅ Install GitHub CLI
3. ✅ Authenticate with GitHub
4. ✅ Install essential developer tools
5. Install project-specific tools (bazelisk, pre-commit, etc.)

