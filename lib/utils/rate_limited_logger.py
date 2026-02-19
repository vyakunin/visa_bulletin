"""
Rate-limited logging utility for reducing log spam while maintaining visibility.

This module provides a reusable RateLimitedLogger class that implements
common rate-limiting patterns for application logging.
"""

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)


class RateLimitedLogger:
    """
    Rate-limited logger that logs frequently at first, then reduces frequency.
    
    Common pattern:
    - First N logs: always log (to confirm it's working)
    - After that: log at most once per X seconds (time-based rate limiting)
    - Optionally: log immediately if a condition is met (e.g., very significant event)
    
    Example usage:
        rate_logger = RateLimitedLogger(
            initial_count=5,
            min_interval_seconds=5.0,
            logger=logger,
            log_level=logging.INFO
        )
        
        for item in items:
            if rate_logger.should_log():
                rate_logger.log(f"Processing item {item}")
    
    Or with conditional immediate logging:
        rate_logger = RateLimitedLogger(
            initial_count=5,
            min_interval_seconds=5.0,
            logger=logger,
            immediate_condition=lambda: removed > total * 0.9  # Log immediately if >90% removed
        )
        
        if rate_logger.should_log(immediate_condition_value=removed > total * 0.9):
            rate_logger.log(f"Pre-filtered {total} -> {after} records")
    """

    def __init__(
        self,
        initial_count: int = 5,
        min_interval_seconds: float = 5.0,
        logger: logging.Logger | None = None,
        log_level: int = logging.INFO,
        immediate_condition: Callable[[], bool] | None = None,
    ):
        """
        Initialize rate-limited logger.
        
        Args:
            initial_count: Number of initial logs to always emit (default: 5)
            min_interval_seconds: Minimum seconds between logs after initial_count (default: 5.0)
            logger: Logger instance to use (default: module logger)
            log_level: Log level to use (default: logging.INFO)
            immediate_condition: Optional callable that returns True to log immediately
                                 (bypasses rate limiting)
        """
        self.initial_count = initial_count
        self.min_interval_seconds = min_interval_seconds
        self.logger = logger or logging.getLogger(__name__)
        self.log_level = log_level
        self.immediate_condition = immediate_condition

        # State tracking
        self._log_count = 0  # Number of times logging actually occurred
        self._attempt_count = 0  # Total number of log attempts (including suppressed)
        self._last_log_time = 0.0

    def should_log(self, immediate_condition_value: bool = False) -> bool:
        """
        Check if logging should occur based on rate limiting rules.
        
        Args:
            immediate_condition_value: If True, bypasses rate limiting and logs immediately
        
        Returns:
            True if should log, False otherwise
        """
        current_time = time.time()

        # Immediate condition bypasses rate limiting
        if immediate_condition_value or (self.immediate_condition and self.immediate_condition()):
            return True

        # First N logs: always log
        if self._log_count < self.initial_count:
            return True

        # After first N: log at most once per min_interval_seconds
        if current_time - self._last_log_time >= self.min_interval_seconds:
            return True

        return False

    def log(self, message: str, immediate_condition_value: bool = False, include_suppressed_count: bool = True):
        """
        Log a message if rate limiting allows it.
        
        Args:
            message: Message to log
            immediate_condition_value: If True, bypasses rate limiting and logs immediately
            include_suppressed_count: If True, appends suppressed count to message if any messages were suppressed (default: True)
        """
        self._attempt_count += 1

        if self.should_log(immediate_condition_value=immediate_condition_value):
            # Add suppressed count if requested and there are suppressed messages
            if include_suppressed_count and self._attempt_count > self._log_count + 1:
                suppressed = self._attempt_count - self._log_count - 1
                if suppressed > 0:
                    message += f" (and {suppressed} more similar messages)"

            self.logger.log(self.log_level, message)
            self._log_count += 1
            # Reset attempt count to log count after outputting suppressed count
            # This prevents double-counting suppressed messages in future logs
            if include_suppressed_count and self._attempt_count > self._log_count:
                self._attempt_count = self._log_count
            self._last_log_time = time.time()

    @property
    def log_count(self) -> int:
        """Get the number of times logging has occurred."""
        return self._log_count

    @property
    def attempt_count(self) -> int:
        """Get the total number of log attempts (including suppressed)."""
        return self._attempt_count

    @property
    def suppressed_count(self) -> int:
        """Get the number of suppressed log attempts."""
        return max(0, self._attempt_count - self._log_count)

    def reset(self):
        """Reset the rate limiter state (useful for new runs/contexts)."""
        self._log_count = 0
        self._attempt_count = 0
        self._last_log_time = 0.0

