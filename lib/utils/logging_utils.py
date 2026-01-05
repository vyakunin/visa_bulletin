"""Script usage logging utility for tracking tool usage and effectiveness"""

import inspect
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Get workspace directory
WORKSPACE_DIR = Path(os.environ.get('BUILD_WORKSPACE_DIRECTORY', Path(__file__).parent.parent))
LOGS_DIR = WORKSPACE_DIR / 'logs'

# Ensure logs directory exists
LOGS_DIR.mkdir(exist_ok=True)

# Logging configuration
# These can be overridden via environment variables if needed
PERMANENT_LOG_FORMAT = os.environ.get('SCRIPT_LOGGER_FORMAT', '%(asctime)s - %(message)s')
PERMANENT_LOG_DATE_FORMAT = os.environ.get('SCRIPT_LOGGER_DATE_FORMAT', '%Y-%m-%d %H:%M:%S')
THROWAWAY_LOG_FORMAT = os.environ.get('SCRIPT_LOGGER_THROWAWAY_FORMAT', '%(message)s')  # JSON only

# Global context storage for throwaway scripts
_throwaway_context = {}

# Configure throwaway logger (shared log file)
_throwaway_logger = None


def _get_throwaway_logger() -> logging.Logger:
    """Get or create the throwaway script logger"""
    global _throwaway_logger
    if _throwaway_logger is None:
        _throwaway_logger = logging.getLogger('script_logger.throwaway')
        _throwaway_logger.setLevel(logging.INFO)
        _throwaway_logger.handlers = []  # Clear any existing handlers
        
        # Add file handler for throwaway log
        handler = logging.FileHandler(LOGS_DIR / 'throwaway_calls.log', mode='a')
        handler.setFormatter(logging.Formatter(THROWAWAY_LOG_FORMAT))
        _throwaway_logger.addHandler(handler)
        _throwaway_logger.propagate = False  # Don't propagate to root logger
    return _throwaway_logger


def _get_calling_script_path() -> Path:
    """Get the path of the script that imported this module"""
    # Walk up the call stack to find the first file that's not this module
    for frame_info in inspect.stack():
        frame = frame_info.frame
        filename = frame.f_globals.get('__file__')
        if filename and not filename.endswith('script_logger.py'):
            return Path(filename)
    # Fallback: use __main__ if available
    main_module = sys.modules.get('__main__')
    if main_module and hasattr(main_module, '__file__'):
        return Path(main_module.__file__)
    return Path('unknown_script.py')


def _is_script_file(filepath: Path) -> bool:
    """Check if a file looks like a script (not a library module)"""
    if not filepath.exists():
        return False
    # Check if it's in a common script location or has script-like name
    path_str = str(filepath)
    # Not in site-packages or .venv
    if 'site-packages' in path_str or '.venv' in path_str or 'venv' in path_str:
        return False
    # Check if file has shebang or looks like a script
    try:
        with open(filepath, 'r') as f:
            first_line = f.readline()
            if first_line.startswith('#!'):
                return True
    except (FileNotFoundError, PermissionError) as e:
        # Expected: file may not exist or be readable
        logger = logging.getLogger(__name__)
        logger.error(f"Cannot read file to check shebang: {filepath}: {e}", exc_info=True)
        return False  # Safe default if we can't read the file
    except Exception as e:
        # Unexpected error - log and use safe default
        logger = logging.getLogger(__name__)
        logger.error(f"Unexpected error reading file {filepath}: {e}", exc_info=True)
        return False  # Safe default if we can't determine
    return True  # Default to True if we can't determine


def _log_throwaway_entry(script_path: Path, args: dict | None = None, context: str | None = None):
    """Internal function to write throwaway log entry using logging module"""
    script_name = script_path.name
    
    # Merge any stored context
    final_context = context or _throwaway_context.get(script_path, 'No context provided')
    
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'script': script_name,
        'script_path': str(script_path),
        'args': args or {},
        'context': final_context,
    }
    
    # Use logging module instead of manual file I/O
    logger = _get_throwaway_logger()
    logger.info(json.dumps(log_entry, default=str))


# Auto-log on import for throwaway scripts
# Only log if imported by what looks like a script (not a library)
_throwaway_script_path = _get_calling_script_path()
if _is_script_file(_throwaway_script_path):
    # Extract args from sys.argv (skip script name)
    args_dict = {}
    if len(sys.argv) > 1:
        # Simple parsing: treat each arg as a key-value or flag
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg.startswith('--'):
                key = arg[2:].replace('-', '_')
                # Check if next arg is a value (not another flag)
                if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('--'):
                    args_dict[key] = sys.argv[i + 1]
                else:
                    args_dict[key] = True
            elif '=' in arg:
                key, value = arg.split('=', 1)
                args_dict[key.replace('-', '_')] = value
            else:
                args_dict[f'arg_{i}'] = arg
    
    _log_throwaway_entry(_throwaway_script_path, args_dict)


def log_context(context: str):
    """
    Add context to a throwaway script's log entry.
    
    Call this explicitly in your script to provide additional context about why
    the script was run or what it's doing.
    
    Args:
        context: Human-readable description of the script's purpose or context
    """
    script_path = _get_calling_script_path()
    _throwaway_context[script_path] = context
    # Re-log with updated context
    args_dict = {}
    if len(sys.argv) > 1:
        for i, arg in enumerate(sys.argv[1:], 1):
            if arg.startswith('--'):
                key = arg[2:].replace('-', '_')
                if i + 1 < len(sys.argv) and not sys.argv[i + 1].startswith('--'):
                    args_dict[key] = sys.argv[i + 1]
                else:
                    args_dict[key] = True
            elif '=' in arg:
                key, value = arg.split('=', 1)
                args_dict[key.replace('-', '_')] = value
            else:
                args_dict[f'arg_{i}'] = arg
    _log_throwaway_entry(script_path, args_dict, context)


class ScriptLogger:
    """Logger for permanent scripts - logs each call to script-specific log file"""
    
    def __init__(self, script_path: str | Path):
        """
        Initialize logger for a permanent script.
        
        Args:
            script_path: Path to the script file (used to determine log filename)
        """
        self.script_path = Path(script_path)
        self.script_name = self.script_path.stem
        
        # Use logging module with script-specific logger
        self.logger = logging.getLogger(f"script.{self.script_name}")
        self.logger.setLevel(logging.INFO)
        
        # Remove existing handlers to avoid duplicates
        self.logger.handlers = []
        
        # Add file handler using logging module
        handler = logging.FileHandler(LOGS_DIR / f"{self.script_name}.log", mode='a')
        handler.setFormatter(logging.Formatter(
            PERMANENT_LOG_FORMAT,
            datefmt=PERMANENT_LOG_DATE_FORMAT
        ))
        self.logger.addHandler(handler)
        self.logger.propagate = False  # Don't propagate to root logger
    
    def log_call(self, args: dict | None = None, context: str | None = None):
        """
        Log a script execution.
        
        Args:
            args: Dictionary of arguments passed to script
            context: Additional context about why script was run
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'script': str(self.script_path),
            'args': args or {},
            'context': context,
        }
        
        # Use logging module instead of manual file I/O
        self.logger.info(json.dumps(log_entry, default=str))
