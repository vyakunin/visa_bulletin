"""Unit tests for exception_utils module.

Tests that verify:
1. handle_unrecoverable_errors decorator distinguishes unrecoverable vs recoverable errors
2. Unrecoverable errors (ImportError, ModuleNotFoundError) are re-raised
3. Recoverable errors can be handled with callbacks
4. suppress_recoverable flag works correctly
5. Logging and callbacks are called appropriately
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
import logging

from lib.utils.exception_utils import (
    handle_unrecoverable_errors,
    is_unrecoverable_error,
    UNRECOVERABLE_ERRORS,
)


class TestIsUnrecoverableError(unittest.TestCase):
    """Test is_unrecoverable_error helper function"""
    
    def test_import_error_is_unrecoverable(self):
        """Test that ImportError is identified as unrecoverable"""
        self.assertTrue(is_unrecoverable_error(ImportError("module not found")))
    
    def test_module_not_found_error_is_unrecoverable(self):
        """Test that ModuleNotFoundError is identified as unrecoverable"""
        self.assertTrue(is_unrecoverable_error(ModuleNotFoundError("module not found")))
    
    def test_other_errors_are_not_unrecoverable(self):
        """Test that other exceptions are not identified as unrecoverable"""
        self.assertFalse(is_unrecoverable_error(ValueError("invalid value")))
        self.assertFalse(is_unrecoverable_error(KeyError("missing key")))
        self.assertFalse(is_unrecoverable_error(RuntimeError("runtime error")))
        self.assertFalse(is_unrecoverable_error(Exception("generic error")))


class TestHandleUnrecoverableErrorsDecorator(unittest.TestCase):
    """Test handle_unrecoverable_errors decorator"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.mock_logger = Mock(spec=logging.Logger)
        self.error_count = 0
    
    def test_unrecoverable_error_is_re_raised(self):
        """Test that unrecoverable errors are logged and re-raised"""
        @handle_unrecoverable_errors(
            log_message="Test unrecoverable error",
            logger_instance=self.mock_logger
        )
        def test_func():
            raise ImportError("module not found")
        
        with self.assertRaises(ImportError) as context:
            test_func()
        
        self.assertEqual(str(context.exception), "module not found")
        self.mock_logger.error.assert_called_once()
        call_args = self.mock_logger.error.call_args
        self.assertIn("Test unrecoverable error", call_args[0][0])
        self.assertTrue(call_args[1].get('exc_info', False))
    
    def test_unrecoverable_error_calls_on_unrecoverable_callback(self):
        """Test that on_unrecoverable callback is called before re-raising"""
        callback_called = []
        
        @handle_unrecoverable_errors(
            log_message="Test error",
            logger_instance=self.mock_logger,
            on_unrecoverable=lambda e: callback_called.append(e)
        )
        def test_func():
            raise ModuleNotFoundError("module not found")
        
        with self.assertRaises(ModuleNotFoundError):
            test_func()
        
        self.assertEqual(len(callback_called), 1)
        self.assertIsInstance(callback_called[0], ModuleNotFoundError)
    
    def test_recoverable_error_propagates_by_default(self):
        """Test that recoverable errors propagate normally by default"""
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger
        )
        def test_func():
            raise ValueError("invalid value")
        
        with self.assertRaises(ValueError) as context:
            test_func()
        
        self.assertEqual(str(context.exception), "invalid value")
        # Should not log recoverable errors by default
        self.mock_logger.error.assert_not_called()
    
    def test_recoverable_error_with_callback_but_no_suppress(self):
        """Test that recoverable errors call callback but still propagate"""
        callback_called = []
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_recoverable=lambda e: callback_called.append(e),
            suppress_recoverable=False
        )
        def test_func():
            raise ValueError("invalid value")
        
        with self.assertRaises(ValueError):
            test_func()
        
        self.assertEqual(len(callback_called), 1)
        self.assertIsInstance(callback_called[0], ValueError)
    
    def test_recoverable_error_suppressed_when_flag_set(self):
        """Test that recoverable errors are suppressed when suppress_recoverable=True"""
        callback_called = []
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_recoverable=lambda e: callback_called.append(e),
            suppress_recoverable=True
        )
        def test_func():
            raise ValueError("invalid value")
        
        # Should not raise, should return None
        result = test_func()
        self.assertIsNone(result)
        self.assertEqual(len(callback_called), 1)
        self.assertIsInstance(callback_called[0], ValueError)
    
    def test_successful_execution_returns_value(self):
        """Test that successful execution returns the function's return value"""
        @handle_unrecoverable_errors()
        def test_func():
            return "success"
        
        result = test_func()
        self.assertEqual(result, "success")
    
    def test_successful_execution_with_suppress_recoverable(self):
        """Test that successful execution works even with suppress_recoverable=True"""
        @handle_unrecoverable_errors(
            on_recoverable=lambda e: None,
            suppress_recoverable=True
        )
        def test_func():
            return "success"
        
        result = test_func()
        self.assertEqual(result, "success")
    
    def test_default_log_message_uses_function_name(self):
        """Test that default log message includes function name"""
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger
        )
        def my_test_function():
            raise ImportError("test error")
        
        with self.assertRaises(ImportError):
            my_test_function()
        
        call_args = self.mock_logger.error.call_args
        self.assertIn("my_test_function", call_args[0][0])
    
    def test_custom_log_message_is_used(self):
        """Test that custom log message is used when provided"""
        @handle_unrecoverable_errors(
            log_message="Custom error message",
            logger_instance=self.mock_logger
        )
        def test_func():
            raise ImportError("test error")
        
        with self.assertRaises(ImportError):
            test_func()
        
        call_args = self.mock_logger.error.call_args
        self.assertIn("Custom error message", call_args[0][0])
    
    def test_on_recoverable_callback_with_error_counting(self):
        """Test on_recoverable callback with error counting pattern"""
        error_count = 0
        
        def handle_recoverable(e):
            nonlocal error_count
            error_count += 1
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_recoverable=handle_recoverable,
            suppress_recoverable=True
        )
        def test_func():
            raise ValueError("error 1")
        
        # First error
        result = test_func()
        self.assertIsNone(result)
        self.assertEqual(error_count, 1)
        
        # Second error
        result = test_func()
        self.assertIsNone(result)
        self.assertEqual(error_count, 2)
    
    def test_unrecoverable_error_takes_precedence_over_recoverable_handler(self):
        """Test that unrecoverable errors are handled even if on_recoverable is provided"""
        recoverable_called = []
        unrecoverable_called = []
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_unrecoverable=lambda e: unrecoverable_called.append(e),
            on_recoverable=lambda e: recoverable_called.append(e),
            suppress_recoverable=True
        )
        def test_func():
            raise ImportError("unrecoverable")
        
        with self.assertRaises(ImportError):
            test_func()
        
        # Unrecoverable callback should be called
        self.assertEqual(len(unrecoverable_called), 1)
        # Recoverable callback should NOT be called
        self.assertEqual(len(recoverable_called), 0)
    
    def test_function_arguments_passed_through(self):
        """Test that function arguments are passed through correctly"""
        @handle_unrecoverable_errors()
        def test_func(arg1, arg2, kwarg1=None):
            return f"{arg1}-{arg2}-{kwarg1}"
        
        result = test_func("a", "b", kwarg1="c")
        self.assertEqual(result, "a-b-c")
    
    def test_function_keyword_arguments_passed_through(self):
        """Test that keyword arguments are passed through correctly"""
        @handle_unrecoverable_errors()
        def test_func(**kwargs):
            return kwargs
        
        result = test_func(a=1, b=2)
        self.assertEqual(result, {"a": 1, "b": 2})
    
    def test_multiple_unrecoverable_errors(self):
        """Test handling of both ImportError and ModuleNotFoundError"""
        errors_raised = []
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_unrecoverable=lambda e: errors_raised.append(type(e).__name__)
        )
        def test_func_import():
            raise ImportError("import error")
        
        @handle_unrecoverable_errors(
            logger_instance=self.mock_logger,
            on_unrecoverable=lambda e: errors_raised.append(type(e).__name__)
        )
        def test_func_module_not_found():
            raise ModuleNotFoundError("module not found")
        
        with self.assertRaises(ImportError):
            test_func_import()
        
        with self.assertRaises(ModuleNotFoundError):
            test_func_module_not_found()
        
        self.assertEqual(errors_raised, ["ImportError", "ModuleNotFoundError"])
    
    def test_recoverable_error_types(self):
        """Test that various recoverable error types are handled correctly"""
        callback_called = []
        
        @handle_unrecoverable_errors(
            on_recoverable=lambda e: callback_called.append(type(e).__name__),
            suppress_recoverable=True
        )
        def test_func():
            raise ValueError("value error")
        
        test_func()
        self.assertEqual(callback_called, ["ValueError"])
        
        @handle_unrecoverable_errors(
            on_recoverable=lambda e: callback_called.append(type(e).__name__),
            suppress_recoverable=True
        )
        def test_func2():
            raise KeyError("key error")
        
        test_func2()
        self.assertEqual(callback_called, ["ValueError", "KeyError"])

