#!/bin/bash
# Setup script for standard developer tools
# Run this script to install Homebrew, GitHub CLI, and other essential tools

set -e

echo "🚀 Setting up developer tools..."

# Check if running on macOS
if [[ "$OSTYPE" != "darwin"* ]]; then
    echo "❌ This script is designed for macOS. Exiting."
    exit 1
fi

# Step 1: Install Homebrew
if ! command -v brew &> /dev/null; then
    echo "📦 Installing Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    
    # Add Homebrew to PATH (for Apple Silicon Macs)
    if [[ -f /opt/homebrew/bin/brew ]]; then
        echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zshrc
        eval "$(/opt/homebrew/bin/brew shellenv)"
    # For Intel Macs
    elif [[ -f /usr/local/bin/brew ]]; then
        echo 'eval "$(/usr/local/bin/brew shellenv)"' >> ~/.zshrc
        eval "$(/usr/local/bin/brew shellenv)"
    fi
else
    echo "✅ Homebrew is already installed"
    # Ensure Homebrew is in PATH
    if [[ -f /opt/homebrew/bin/brew ]]; then
        eval "$(/opt/homebrew/bin/brew shellenv)"
    elif [[ -f /usr/local/bin/brew ]]; then
        eval "$(/usr/local/bin/brew shellenv)"
    fi
fi

# Step 2: Update Homebrew
echo "🔄 Updating Homebrew..."
brew update

# Step 3: Install GitHub CLI
if ! command -v gh &> /dev/null; then
    echo "🔐 Installing GitHub CLI..."
    brew install gh
else
    echo "✅ GitHub CLI is already installed"
fi

# Step 4: Authenticate with GitHub
echo "🔑 Setting up GitHub authentication..."
if ! gh auth status &> /dev/null; then
    echo "⚠️  GitHub CLI is not authenticated. Run: gh auth login"
    echo "   Or if you have GITHUB_TOKEN set, run: gh auth login --with-token <<< \$GITHUB_TOKEN"
    
    # Try to authenticate with existing token if available
    if [[ -n "$GITHUB_TOKEN" ]]; then
        echo "🔑 Attempting to authenticate with GITHUB_TOKEN..."
        echo "$GITHUB_TOKEN" | gh auth login --with-token || echo "⚠️  Token authentication failed. Please run 'gh auth login' manually."
    fi
else
    echo "✅ GitHub CLI is already authenticated"
    gh auth status
fi

# Step 5: Install other standard developer tools
echo "🛠️  Installing standard developer tools..."

# Essential command-line tools
TOOLS=(
    "git"              # Version control (usually pre-installed, but ensure latest)
    "curl"             # HTTP client (usually pre-installed)
    "wget"             # Alternative HTTP client
    "jq"               # JSON processor
    "tree"             # Directory tree viewer
    "htop"             # Better process viewer
    "tmux"             # Terminal multiplexer
    "vim"              # Text editor (usually pre-installed)
    "ripgrep"          # Fast text search (rg)
    "fd"               # Fast file finder
    "bat"              # Better cat with syntax highlighting
    "exa"              # Better ls (or use eza if exa is deprecated)
    "zsh"              # Shell (usually pre-installed)
    "fzf"              # Fuzzy finder
    "direnv"           # Environment variable management
    "watch"            # Execute command periodically
    "ncdu"             # Disk usage analyzer
    "tldr"             # Simplified man pages
)

echo "Installing: ${TOOLS[*]}"
for tool in "${TOOLS[@]}"; do
    if ! command -v "$tool" &> /dev/null; then
        echo "  📦 Installing $tool..."
        brew install "$tool" || echo "  ⚠️  Failed to install $tool"
    else
        echo "  ✅ $tool is already installed"
    fi
done

# Install eza (modern replacement for exa)
if ! command -v eza &> /dev/null; then
    echo "  📦 Installing eza (modern ls replacement)..."
    brew install eza || echo "  ⚠️  Failed to install eza"
fi

# Optional but recommended tools
echo ""
echo "💡 Optional but recommended tools you might want:"
echo "  - docker: Container platform"
echo "  - docker-compose: Multi-container Docker apps"
echo "  - node: JavaScript runtime"
echo "  - python@3.11: Python (if not using system Python)"
echo "  - bazelisk: Bazel version manager (for this project)"
echo "  - pre-commit: Git hooks framework"
echo "  - terraform: Infrastructure as code"
echo "  - kubectl: Kubernetes command-line tool"
echo "  - helm: Kubernetes package manager"
echo "  - awscli: AWS command-line interface"
echo "  - gcloud: Google Cloud SDK"
echo "  - postgresql: PostgreSQL database"
echo "  - redis: In-memory data store"
echo "  - nginx: Web server"

echo ""
echo "✅ Developer tools setup complete!"
echo ""
echo "📝 Next steps:"
echo "  1. If GitHub CLI authentication failed, run: gh auth login"
echo "  2. Verify GitHub access: gh auth status"
echo "  3. Test GitHub CLI: gh repo view vyakunin/visa_bulletin"
echo "  4. Install optional tools as needed: brew install <tool>"
echo ""
echo "💡 Tip: Run 'brew list' to see all installed packages"

