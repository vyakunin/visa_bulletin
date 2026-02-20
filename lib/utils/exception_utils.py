"""Exception handling utilities for distinguishing recoverable vs unrecoverable errors"""

import logging
from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

# Unrecoverable errors that should abort operations
UNRECOVERABLE_ERRORS = (ModuleNotFoundError, ImportError)


def is_unrecoverable_error(exception: Exception) -> bool:
    """
    Check if an exception is unrecoverable (should abort operation).

    Args:
        exception: Exception to check

    Returns:
        True if exception is unrecoverable (ImportError, ModuleNotFoundError)
    """
    return isinstance(exception, UNRECOVERABLE_ERRORS)


def handle_unrecoverable_errors(
    log_message: str | None = None,
    logger_instance: logging.Logger | None = None,
    on_unrecoverable: Callable[[Exception], None] | None = None,
    on_recoverable: Callable[[Exception], None] | None = None,
    suppress_recoverable: bool = False,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator to distinguish between unrecoverable and recoverable errors.

    Unrecoverable errors (ImportError, ModuleNotFoundError) are logged and re-raised.
    Recoverable errors can be handled via callback and optionally suppressed.

    Args:
        log_message: Custom log message for unrecoverable errors.
                    If None, uses default message with function name.
        logger_instance: Logger to use. If None, uses module logger.
        on_unrecoverable: Optional callback called before re-raising unrecoverable errors.
        on_recoverable: Optional callback called for recoverable errors.
                       If suppress_recoverable=True, exception is suppressed after callback.
        suppress_recoverable: If True and on_recoverable is provided, suppress recoverable
                             errors after calling callback. If False, propagate normally.

    Example 1: Only handle unrecoverable errors (default):
        @handle_unrecoverable_errors(
            log_message=f"[Run {run.id}] Unrecoverable error in validation"
        )
        def validate_data(run):
            return plugin.validate_post_ingest(run)

    Example 2: Handle and suppress recoverable errors:
        error_count = 0
        def handle_recoverable(e):
            nonlocal error_count
            error_count += 1
            logger.error(f"Error: {e}")

        @handle_unrecoverable_errors(
            on_recoverable=handle_recoverable,
            suppress_recoverable=True
        )
        def transform_record(record):
            return plugin.transform(record)
    """
    log = logger_instance or logger

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        @wraps(func)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R | None:
            try:
                return func(*args, **kwargs)
            except UNRECOVERABLE_ERRORS as e:
                # Unrecoverable errors: configuration issues, missing dependencies
                message = log_message or f"Unrecoverable error in {func.__name__}: {e}"
                log.error(message, exc_info=True)

                # Call optional callback for state updates
                if on_unrecoverable:
                    on_unrecoverable(e)

                # Always re-raise unrecoverable errors
                raise
            except Exception as e:
                # Recoverable errors: data issues, parsing problems, etc.
                if on_recoverable:
                    on_recoverable(e)
                    if suppress_recoverable:
                        # Suppress the exception after handling
                        return None
                # If no callback or suppress_recoverable=False, propagate normally
                raise

        return wrapper

    return decorator
