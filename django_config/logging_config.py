"""
Logging configuration for visa bulletin application
"""

import logging
import sys

def setup_logging(debug=False):
    """
    Configure logging for the application
    
    Args:
        debug: If True, set log level to DEBUG, otherwise INFO
    """
    log_level = logging.DEBUG if debug else logging.INFO
    
    # Root logger configuration
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout)
        ]
    )
    
    # Set specific loggers
    loggers = {
        'django': logging.WARNING,  # Reduce Django noise
        'django.request': logging.INFO,  # Log requests
        'django.db.backends': logging.WARNING if not debug else logging.DEBUG,
        'webapp': log_level,
        'lib': log_level,
        'extractors': log_level,
    }
    
    for logger_name, level in loggers.items():
        logging.getLogger(logger_name).setLevel(level)


# Convenience function to get logger
def get_logger(name):
    """Get a logger instance for the given name"""
    return logging.getLogger(name)
