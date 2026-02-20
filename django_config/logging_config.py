"""
Logging configuration for visa bulletin application
"""

import logging
import sys
from datetime import datetime


class LocalTimeFormatter(logging.Formatter):
    """Log timestamps in local time with timezone offset."""

    def formatTime(self, record, datefmt=None):
        dt = datetime.fromtimestamp(record.created).astimezone()
        if datefmt:
            return dt.strftime(datefmt)

        timestamp = dt.strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]
        tz_offset = dt.strftime("%z")
        return f"{timestamp} {tz_offset}"


def setup_logging(debug=True):
    """
    Configure logging for the application

    Args:
        debug: If True, set log level to DEBUG, otherwise INFO (default: True)
    """
    log_level = logging.DEBUG if debug else logging.INFO

    # Root logger configuration
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        LocalTimeFormatter(fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    )

    logging.basicConfig(
        level=log_level,
        handlers=[handler],
    )

    # Set specific loggers
    loggers = {
        "django": logging.WARNING,  # Reduce Django noise
        "django.request": logging.INFO,  # Log requests
        "django.db.backends": logging.WARNING if not debug else logging.DEBUG,
        "webapp": log_level,
        "lib": log_level,
        "extractors": log_level,
    }

    for logger_name, level in loggers.items():
        logging.getLogger(logger_name).setLevel(level)


# Convenience function to get logger
def get_logger(name):
    """Get a logger instance for the given name"""
    return logging.getLogger(name)
