#!/bin/bash
# Check if Ollama is installed and available
# Used by Bazel to enforce Ollama as a dependency

set -e

# Check if ollama command exists
if ! command -v ollama &> /dev/null; then
    echo "ERROR: Ollama is not installed or not in PATH"
    echo "Install with: brew install ollama (macOS) or visit https://ollama.ai/"
    exit 1
fi

# Check if Ollama service is running
if ! ollama list &> /dev/null; then
    echo "ERROR: Ollama is installed but service is not running"
    echo "Start Ollama with: ollama serve"
    exit 1
fi

# Check if a suitable model is available
MODELS=$(ollama list 2>/dev/null | grep -E "llama3.2:3b|mistral" || true)
if [ -z "$MODELS" ]; then
    echo "ERROR: Ollama is installed but no suitable model found"
    echo "Install a model with: ollama pull llama3.2:3b"
    exit 1
fi

echo "✓ Ollama is installed and ready"
exit 0








