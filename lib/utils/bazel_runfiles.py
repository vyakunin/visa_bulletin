"""
Bazel runfiles utilities for accessing data dependencies.

Uses the standard rules_python.runfiles library for cross-platform compatibility.
This library handles all path variations automatically - no need for multiple path attempts.
"""

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Try to import the standard Bazel runfiles library
try:
    from rules_python.python.runfiles import runfiles
    _RUNFILES_AVAILABLE = True
except ImportError:
    _RUNFILES_AVAILABLE = False
    logger.debug("Bazel runfiles library not available (non-Bazel environment)")


def get_data_file_path(workspace_path: str) -> Optional[Path]:
    """
    Get the path to a Bazel data file using the standard runfiles library.
    
    The standard library handles all path variations automatically (tests vs binaries,
    different platforms, etc.), so we don't need multiple path attempts.
    
    Args:
        workspace_path: Path relative to workspace root (e.g., "scripts/salary/llm_prompt_template.txt")
                        The standard library will try with and without workspace prefix automatically.
    
    Returns:
        Path to the file if found, None otherwise
    
    Example:
        >>> template_path = get_data_file_path("scripts/salary/llm_prompt_template.txt")
        >>> if template_path:
        ...     with open(template_path) as f:
        ...         content = f.read()
    """
    if not _RUNFILES_AVAILABLE:
        # Fallback for non-Bazel environments (development, direct Python execution)
        workspace_dir = os.environ.get('BUILD_WORKSPACE_DIRECTORY')
        if workspace_dir:
            fallback_path = Path(workspace_dir) / workspace_path
            if fallback_path.exists():
                return fallback_path
        logger.debug(f"Runfiles library not available, fallback failed for: {workspace_path}")
        return None
    
    try:
        r = runfiles.Create()
        # Standard library handles workspace prefix automatically
        # Try with workspace name prefix first (standard format)
        workspace_name = "visa_bulletin"
        full_path = f"{workspace_name}/{workspace_path}"
        resolved = r.Rlocation(full_path)
        
        if resolved and Path(resolved).exists():
            return Path(resolved)
        
        # Try without workspace prefix (some Bazel setups)
        resolved = r.Rlocation(workspace_path)
        if resolved and Path(resolved).exists():
            return Path(resolved)
        
        logger.debug(f"Data file not found in runfiles: {workspace_path}")
        return None
    except Exception as e:
        logger.error(f"Error accessing runfiles: {e}", exc_info=True)
        return None


def get_template_file(template_name: str, template_dir: str = "scripts/salary") -> Optional[Path]:
    """
    Get the path to a template file.
    
    Convenience wrapper for get_data_file_path specifically for template files.
    
    Args:
        template_name: Name of the template file (e.g., "llm_prompt_template.txt")
        template_dir: Directory containing the template (default: "scripts/salary")
    
    Returns:
        Path to the template file if found, None otherwise
    """
    template_path = f"{template_dir}/{template_name}"
    return get_data_file_path(template_path)








