"""
Unit tests for qos_tool module - QoS (Quality of Service) tools for monitoring and logging.

Test coverage:
- log_if_slow context manager (threshold checking, logging levels, custom logger)
- _get_log_function helper (string levels, integer levels, default logger)
- log_if_slow_decorator (with/without message, different log levels, custom logger)

Author: DawsonLin
"""

import logging
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestGetLogFunction(unittest.TestCase):
    """Test cases for _get_log_function helper."""

    def test_get_log_function_with_string_level_debug(self):
        """Test that 'debug' string level returns logger.debug."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('debug', mock_logger)

        self.assertEqual(log_func, mock_logger.debug)

    def test_get_log_function_with_string_level_info(self):
        """Test that 'info' string level returns logger.info."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('info', mock_logger)

        self.assertEqual(log_func, mock_logger.info)

    def test_get_log_function_with_string_level_warning(self):
        """Test that 'warning' string level returns logger.warning."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('warning', mock_logger)

        self.assertEqual(log_func, mock_logger.warning)

    def test_get_log_function_with_string_level_error(self):
        """Test that 'error' string level returns logger.error."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('error', mock_logger)

        self.assertEqual(log_func, mock_logger.error)

    def test_get_log_function_with_string_level_critical(self):
        """Test that 'critical' string level returns logger.critical."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('critical', mock_logger)

        self.assertEqual(log_func, mock_logger.critical)

    def test_get_log_function_with_uppercase_string_level(self):
        """Test that uppercase string levels work correctly."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('WARNING', mock_logger)

        self.assertEqual(log_func, mock_logger.warning)

    def test_get_log_function_with_integer_level(self):
        """Test that integer log levels work correctly."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        # logging.INFO = 20
        log_func = _get_log_function(logging.INFO, mock_logger)

        self.assertEqual(log_func, mock_logger.info)

    def test_get_log_function_with_invalid_string_level_defaults_to_warning(self):
        """Test that invalid string level defaults to warning."""
        from topsailai.utils.qos_tool import _get_log_function

        mock_logger = MagicMock()
        log_func = _get_log_function('invalid_level', mock_logger)

        self.assertEqual(log_func, mock_logger.warning)

    def test_get_log_function_without_logger_uses_default_logger(self):
        """Test that when no logger is provided, the default logger is used."""
        from topsailai.utils.qos_tool import _get_log_function
        from topsailai.logger import logger

        log_func = _get_log_function('info', None)

        self.assertEqual(log_func, logger.info)


class TestLogIfSlow(unittest.TestCase):
    """Test cases for log_if_slow context manager."""

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_logs_when_exceeds_threshold(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow logs a message when execution exceeds threshold."""
        from topsailai.utils.qos_tool import log_if_slow

        # Mock perf_counter to simulate elapsed time > threshold
        mock_perf_counter.side_effect = [0.0, 2.0]  # elapsed = 2.0s, threshold = 1.0s
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with log_if_slow(threshold=1.0, message="Slow operation"):
            pass

        mock_log_func.assert_called_once()
        call_args = mock_log_func.call_args[0][0]
        self.assertIn("Slow operation", call_args)
        self.assertIn("elapsed:", call_args)
        self.assertIn("threshold: 1.0s", call_args)

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_does_not_log_when_under_threshold(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow does not log when execution is under threshold."""
        from topsailai.utils.qos_tool import log_if_slow

        # Mock perf_counter to simulate elapsed time < threshold
        mock_perf_counter.side_effect = [0.0, 0.5]  # elapsed = 0.5s, threshold = 1.0s
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with log_if_slow(threshold=1.0, message="Slow operation"):
            pass

        mock_log_func.assert_not_called()

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_at_exact_threshold_does_not_log(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow does not log when elapsed equals threshold (strict > comparison)."""
        from topsailai.utils.qos_tool import log_if_slow

        # Mock perf_counter to simulate elapsed time == threshold
        mock_perf_counter.side_effect = [0.0, 1.0]  # elapsed = 1.0s, threshold = 1.0s
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with log_if_slow(threshold=1.0, message="Slow operation"):
            pass

        mock_log_func.assert_not_called()

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_uses_correct_log_level(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow uses the specified log level."""
        from topsailai.utils.qos_tool import log_if_slow

        mock_perf_counter.side_effect = [0.0, 2.0]
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with log_if_slow(threshold=1.0, message="Test", level="error"):
            pass

        mock_get_log_function.assert_called_once_with("error", None)

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_with_custom_logger(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow uses the provided custom logger."""
        from topsailai.utils.qos_tool import log_if_slow

        mock_perf_counter.side_effect = [0.0, 2.0]
        mock_logger = MagicMock()
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with log_if_slow(threshold=1.0, message="Test", logger_obj=mock_logger):
            pass

        mock_get_log_function.assert_called_once_with("warning", mock_logger)

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_executes_code_correctly(self, mock_perf_counter, mock_get_log_function):
        """Test that code inside log_if_slow executes correctly."""
        from topsailai.utils.qos_tool import log_if_slow

        mock_perf_counter.side_effect = [0.0, 0.1]
        mock_get_log_function.return_value = MagicMock()

        result = []
        with log_if_slow(threshold=1.0, message="Test"):
            result.append("executed")
            result.append("correctly")

        self.assertEqual(result, ["executed", "correctly"])

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_propagates_exceptions(self, mock_perf_counter, mock_get_log_function):
        """Test that exceptions inside log_if_slow are properly propagated."""
        from topsailai.utils.qos_tool import log_if_slow

        mock_perf_counter.side_effect = [0.0, 0.1]
        mock_get_log_function.return_value = MagicMock()

        with self.assertRaises(ValueError):
            with log_if_slow(threshold=1.0, message="Test"):
                raise ValueError("Test exception")

    @patch('topsailai.utils.qos_tool._get_log_function')
    @patch('topsailai.utils.qos_tool.time.perf_counter')
    def test_log_if_slow_logs_even_when_exception_occurs(self, mock_perf_counter, mock_get_log_function):
        """Test that log_if_slow still logs if threshold is exceeded even when exception occurs."""
        from topsailai.utils.qos_tool import log_if_slow

        # elapsed = 2.0s > threshold = 1.0s
        mock_perf_counter.side_effect = [0.0, 2.0]
        mock_log_func = MagicMock()
        mock_get_log_function.return_value = mock_log_func

        with self.assertRaises(ValueError):
            with log_if_slow(threshold=1.0, message="Slow operation"):
                raise ValueError("Test exception")

        # Should still log because finally block runs
        mock_log_func.assert_called_once()


class TestLogIfSlowDecorator(unittest.TestCase):
    """Test cases for log_if_slow_decorator."""

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_passes_threshold_to_context_manager(self, mock_log_if_slow):
        """Test that decorator passes threshold correctly to log_if_slow."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx

        @log_if_slow_decorator(threshold=2.5, message="Slow function")
        def test_func():
            return "result"

        # Setup context manager mock
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        result = test_func()

        self.assertEqual(result, "result")
        mock_log_if_slow.assert_called_once_with(threshold=2.5, message="Slow function", level="warning", logger_obj=None)

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_with_custom_message(self, mock_log_if_slow):
        """Test that decorator uses custom message."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0, message="Custom message")
        def test_func():
            pass

        test_func()

        call_kwargs = mock_log_if_slow.call_args[1]
        self.assertEqual(call_kwargs['message'], "Custom message")

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_with_default_message_uses_function_name(self, mock_log_if_slow):
        """Test that decorator generates default message with function name when no message provided."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0)
        def my_specific_function():
            pass

        my_specific_function()

        call_kwargs = mock_log_if_slow.call_args[1]
        self.assertEqual(call_kwargs['message'], "Function 'my_specific_function' took too long")

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_passes_log_level(self, mock_log_if_slow):
        """Test that decorator passes log level correctly."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0, level="error")
        def test_func():
            pass

        test_func()

        call_kwargs = mock_log_if_slow.call_args[1]
        self.assertEqual(call_kwargs['level'], "error")

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_with_custom_logger(self, mock_log_if_slow):
        """Test that decorator passes custom logger correctly."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_logger = MagicMock()
        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0, logger_obj=mock_logger)
        def test_func():
            pass

        test_func()

        call_kwargs = mock_log_if_slow.call_args[1]
        self.assertEqual(call_kwargs['logger_obj'], mock_logger)

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_preserves_function_metadata(self, mock_log_if_slow):
        """Test that decorator preserves function name and docstring."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0)
        def documented_function():
            """This is a docstring."""
            pass

        self.assertEqual(documented_function.__name__, "documented_function")
        self.assertEqual(documented_function.__doc__, "This is a docstring.")

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_with_function_arguments(self, mock_log_if_slow):
        """Test that decorated function correctly handles arguments."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0)
        def add(a, b):
            return a + b

        result = add(3, 5)
        self.assertEqual(result, 8)

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_with_keyword_arguments(self, mock_log_if_slow):
        """Test that decorated function correctly handles keyword arguments."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0)
        def greet(name, greeting="Hello"):
            return f"{greeting}, {name}!"

        result = greet("World", greeting="Hi")
        self.assertEqual(result, "Hi, World!")

    @patch('topsailai.utils.qos_tool.log_if_slow')
    def test_decorator_propagates_exceptions(self, mock_log_if_slow):
        """Test that exceptions from decorated function are propagated."""
        from topsailai.utils.qos_tool import log_if_slow_decorator

        mock_ctx = MagicMock()
        mock_log_if_slow.return_value = mock_ctx
        mock_ctx.__enter__ = MagicMock(return_value=None)
        mock_ctx.__exit__ = MagicMock(return_value=False)

        @log_if_slow_decorator(threshold=1.0)
        def failing_function():
            raise RuntimeError("Something went wrong")

        with self.assertRaises(RuntimeError):
            failing_function()


class TestIntegration(unittest.TestCase):
    """Integration tests for qos_tool module."""

    def test_log_if_slow_with_real_time(self):
        """Test log_if_slow with actual timing (no mocking)."""
        from topsailai.utils.qos_tool import log_if_slow
        import logging

        # Create a mock logger to capture log output
        log_records = []

        class TestHandler(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        test_logger = logging.getLogger("test_qos")
        test_logger.setLevel(logging.DEBUG)
        handler = TestHandler()
        test_logger.addHandler(handler)

        try:
            # Test that slow operation logs
            with log_if_slow(threshold=0.01, message="This should log", logger_obj=test_logger):
                time.sleep(0.02)  # Sleep for 20ms, threshold is 10ms

            self.assertEqual(len(log_records), 1)
            self.assertIn("This should log", log_records[0].getMessage())
        finally:
            test_logger.removeHandler(handler)

    def test_log_if_slow_with_fast_operation_no_log(self):
        """Test log_if_slow with fast operation does not log."""
        from topsailai.utils.qos_tool import log_if_slow
        import logging

        log_records = []

        class TestHandler(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        test_logger = logging.getLogger("test_qos_fast")
        test_logger.setLevel(logging.DEBUG)
        handler = TestHandler()
        test_logger.addHandler(handler)

        try:
            # Test that fast operation does not log
            with log_if_slow(threshold=1.0, message="This should not log", logger_obj=test_logger):
                pass  # Very fast operation

            self.assertEqual(len(log_records), 0)
        finally:
            test_logger.removeHandler(handler)

    def test_decorator_with_real_timing(self):
        """Test log_if_slow_decorator with actual timing."""
        from topsailai.utils.qos_tool import log_if_slow_decorator
        import logging

        log_records = []

        class TestHandler(logging.Handler):
            def emit(self, record):
                log_records.append(record)

        test_logger = logging.getLogger("test_decorator")
        test_logger.setLevel(logging.DEBUG)
        handler = TestHandler()
        test_logger.addHandler(handler)

        try:
            @log_if_slow_decorator(threshold=0.01, message="Decorator test", logger_obj=test_logger)
            def slow_func():
                time.sleep(0.02)

            slow_func()

            self.assertEqual(len(log_records), 1)
            self.assertIn("Decorator test", log_records[0].getMessage())
        finally:
            test_logger.removeHandler(handler)


if __name__ == "__main__":
    unittest.main()