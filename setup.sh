#!/bin/bash

# Visa Bulletin Parser - Environment Setup Script
# This script sets up the Python virtual environment and installs dependencies

set -e  # Exit on error

VENV_PATH=~/visa-bulletin-venv
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "======================================"
echo "Visa Bulletin Parser - Setup"
echo "======================================"
echo ""

# Check if Python 3 is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Error: Python 3 is not installed"
    echo "Please install Python 3.11 or higher"
    exit 1
fi

# Check Python version
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2)
echo "✓ Found Python $PYTHON_VERSION"
echo ""

# Create virtual environment if it doesn't exist
if [ -d "$VENV_PATH" ]; then
    echo "⚠️  Virtual environment already exists at $VENV_PATH"
    read -p "Do you want to recreate it? (y/N): " -n 1 -r
    echo ""
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        echo "Removing existing virtual environment..."
        rm -rf "$VENV_PATH"
    else
        echo "Using existing virtual environment"
    fi
fi

if [ ! -d "$VENV_PATH" ]; then
    echo "Creating virtual environment at $VENV_PATH..."
    python3 -m venv "$VENV_PATH"
    echo "✓ Virtual environment created"
    echo ""
fi

# Activate virtual environment
echo "Activating virtual environment..."
source "$VENV_PATH/bin/activate"
echo "✓ Virtual environment activated"
echo ""

# Upgrade pip
echo "Upgrading pip..."
pip install --upgrade pip --quiet
echo "✓ pip upgraded"
echo ""

# Install requirements
if [ -f "$PROJECT_DIR/requirements.txt" ]; then
    echo "Installing dependencies from requirements.txt..."
    pip install -r "$PROJECT_DIR/requirements.txt"
    echo "✓ Dependencies installed"
    echo ""
else
    echo "⚠️  Warning: requirements.txt not found"
    echo ""
fi

# Create saved_pages directory if it doesn't exist
if [ ! -d "$PROJECT_DIR/saved_pages" ]; then
    echo "Creating saved_pages directory..."
    mkdir -p "$PROJECT_DIR/saved_pages"
    echo "✓ saved_pages directory created"
    echo ""
fi

echo "======================================"
echo "✓ Setup Complete!"
echo "======================================"
echo ""
echo "Virtual environment location: $VENV_PATH"
echo ""
echo "To activate the environment in the future, run:"
echo "  source ~/visa-bulletin-venv/bin/activate"
echo ""
echo "To run the script:"
echo "  cd $PROJECT_DIR"
echo "  source ~/visa-bulletin-venv/bin/activate"
echo "  python refresh_data.py"
echo ""
echo "To deactivate when done:"
echo "  deactivate"
echo ""

