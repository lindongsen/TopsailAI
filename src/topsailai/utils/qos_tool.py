'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-20
Purpose: QoS (Quality of Service) tools for monitoring and logging
'''

import time
import logging
import functools
from contextlib import contextmanager
from typing import Optional, Union, Callable

from topsailai.logger import logger


@contextmanager
def log_if_slow(
    threshold: Union[int, float],
    message: str,
    level: Union[str, int] = "warning",
    logger_obj: Optional[logging.Logger] = None,
):
    """
    A context manager that logs a message if the execution time exceeds a specified threshold.

    Args:
        threshold: The time threshold in seconds. If execution time exceeds this value,
                   the message will be logged.
        message: The log message to output when the threshold is exceeded.
        level: The log level. Can be a string ('debug', 'info', 'warning', 'error', 'critical')
               or an integer (logging.DEBUG, logging.INFO, etc.). Defaults to 'warning'.
        logger_obj: Optional logger instance. If not provided, uses the default logger.

    Example:
        >>> with log_if_slow(threshold=1.0, message="Operation took too long"):
        ...     # some slow operation
        ...     time.sleep(2)
        # This will log: "Operation took too long" at warning level

        >>> with log_if_slow(threshold=0.5, message="Slow query", level="info"):
        ...     # some operation
        ...     pass
    """
    # Get the logger
    log_func = _get_log_function(level, logger_obj)

    start_time = time.perf_counter()
    try:
        yield
    finally:
        elapsed_time = time.perf_counter() - start_time
        if elapsed_time > threshold:
            log_func(f"{message} (elapsed: {elapsed_time:.3f}s, threshold: {threshold}s)")


def _get_log_function(
    level: Union[str, int],
    logger_obj: Optional[logging.Logger] = None,
):
    """
    Get the appropriate logging function based on the level.

    Args:
        level: The log level as string or integer.
        logger_obj: Optional logger instance.

    Returns:
        A callable logging function.
    """
    # Use default logger if not provided
    if logger_obj is None:
        logger_obj = logger

    # Convert string level to integer if needed
    if isinstance(level, str):
        level = level.lower()
        level_map = {
            'debug': logging.DEBUG,
            'info': logging.INFO,
            'warning': logging.WARNING,
            'error': logging.ERROR,
            'critical': logging.CRITICAL,
        }
        level_int = level_map.get(level, logging.WARNING)
    else:
        level_int = level

    # Return the appropriate logging function
    level_name = logging.getLevelName(level_int).lower()
    return getattr(logger_obj, level_name, logger_obj.warning)


def log_if_slow_decorator(
    threshold: Union[int, float],
    message: Optional[str] = None,
    level: Union[str, int] = "warning",
    logger_obj: Optional[logging.Logger] = None,
) -> Callable:
    """
    A decorator that logs a message if the function execution time exceeds a specified threshold.
    This decorator internally uses the `log_if_slow` context manager.

    Args:
        threshold: The time threshold in seconds. If execution time exceeds this value,
                   the message will be logged.
        message: The log message to output when the threshold is exceeded. If not provided,
                 a default message with the function name will be used.
        level: The log level. Can be a string ('debug', 'info', 'warning', 'error', 'critical')
               or an integer (logging.DEBUG, logging.INFO, etc.). Defaults to 'warning'.
        logger_obj: Optional logger instance. If not provided, uses the default logger.

    Example:
        >>> @log_if_slow_decorator(threshold=1.0, message="Function is too slow")
        ... def my_slow_function():
        ...     time.sleep(2)
        ...
        >>> my_slow_function()
        # This will log: "Function is too slow (elapsed: 2.000s, threshold: 1.0s)"

        >>> @log_if_slow_decorator(threshold=0.5, level="info")
        ... def another_function():
        ...     pass
        ...
        >>> another_function()
        # This will log: "Function 'another_function' took too long (elapsed: 0.001s, threshold: 0.5s)"
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            log_message = message or f"Function '{func.__name__}' took too long"
            with log_if_slow(threshold=threshold, message=log_message, level=level, logger_obj=logger_obj):
                return func(*args, **kwargs)
        return wrapper
    return decorator
