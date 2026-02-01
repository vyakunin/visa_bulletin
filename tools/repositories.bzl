"""Repository definitions for external dependencies."""

load("//tools:ollama.bzl", "ollama_repository")

def setup_repositories():
    """Setup all external repositories."""
    ollama_repository(name = "ollama")








