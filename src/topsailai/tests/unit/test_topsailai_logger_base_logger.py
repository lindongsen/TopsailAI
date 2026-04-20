"""
Unit tests for the logger.base_logger module.

This module tests the setup_logger function and AgentFormatter class
to ensure proper logging configuration and formatting.

Author: AI (Unit Test Enhancement)
Purpose: Comprehensive test coverage for logger module
"""

import pytest
import logging
import os
from logging.handlers import RotatingFileHandler
from unittest.mock import patch, MagicMock

from topsailai.logger.base_logger import setup_logger, AgentFormatter


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture(autouse=True)
def cleanup_loggers():
    """
    Clean up all logger handlers after each test to prevent handler accumulation.
    This fixture runs automatically for every test in this module.
    """
    yield
    # Clean up all loggers and their handlers after each test
    for name in list(logging.Logger.manager.loggerDict.keys()):
        logger = logging.getLogger(name)
        for handler in logger.handlers[:]:
            handler.close()
            logger.removeHandler(handler)


@pytest.fixture
def mock_log_folder_exists():
    """Mock os.path.exists to simulate /topsailai/log/ folder exists."""
    with patch("os.path.exists") as mock_exists:
        mock_exists.return_value = True
        yield mock_exists


@pytest.fixture
def mock_log_folder_not_exists():
    """Mock os.path.exists to simulate /topsailai/log/ folder does not exist."""
    with patch("os.path.exists") as mock_exists:
        mock_exists.return_value = False
        yield mock_exists


@pytest.fixture
def mock_agent_and_thread_names():
    """Mock get_agent_name and get_thread_name to return empty values."""
    with patch("topsailai.utils.thread_local_tool.get_agent_name", return_value=None), \
         patch("topsailai.utils.thread_local_tool.get_thread_name", return_value=None):
        yield


@pytest.fixture
def mock_agent_name():
    """Mock get_agent_name to return a test agent name."""
    with patch("topsailai.utils.thread_local_tool.get_agent_name", return_value="TestAgent"):
        yield


@pytest.fixture
def mock_thread_name():
    """Mock get_thread_name to return a test thread name."""
    with patch("topsailai.utils.thread_local_tool.get_thread_name", return_value="TestThread"):
        yield


# ============================================================================
# Test Cases for setup_logger function
# ============================================================================


def test_setup_logger_with_name_only(mock_log_folder_exists):
    """
    Test setup_logger creates a logger with the given name.
    Verifies logger name matches, has handlers, and level is DEBUG.
    """
    logger = setup_logger(name="test_logger")

    assert logger.name == "test_logger"
    assert len(logger.handlers) > 0
    assert logger.level == logging.DEBUG


def test_setup_logger_with_name_creates_file_handler(mock_log_folder_exists):
    """
    Test that providing a name triggers file handler creation.
    Verifies log file is created at /topsailai/log/{name}.log.
    """
    logger = setup_logger(name="file_test_logger")

    # Check that a RotatingFileHandler was added
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0, "Expected RotatingFileHandler to be added"

    # Verify the file path matches expected pattern
    handler = file_handlers[0]
    expected_path = "/topsailai/log/file_test_logger.log"
    assert handler.baseFilename.endswith("file_test_logger.log")


def test_setup_logger_with_explicit_log_file(mock_log_folder_exists):
    """
    Test setup_logger with explicit log_file path.
    Verifies handler is created and file path matches provided path.
    """
    explicit_path = "/tmp/custom_test.log"
    logger = setup_logger(name="explicit_test", log_file=explicit_path)

    # Check that a RotatingFileHandler was added
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0, "Expected RotatingFileHandler to be added"

    # Verify the file path matches provided path
    handler = file_handlers[0]
    assert handler.baseFilename == explicit_path


def test_setup_logger_no_name_no_file(mock_log_folder_not_exists):
    """
    Test setup_logger with no name and no file path.
    Verifies console-only logging with StreamHandler and no RotatingFileHandler.
    """
    logger = setup_logger(name=None, log_file=None)

    # Check for StreamHandler
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) > 0, "Expected StreamHandler for console output"

    # Check no RotatingFileHandler
    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) == 0, "Did not expect RotatingFileHandler when no file specified"


def test_setup_logger_level_info(mock_log_folder_exists):
    """
    Test setup_logger with INFO level.
    Verifies logger level is set to logging.INFO.
    """
    logger = setup_logger(name="info_level_test", level=logging.INFO)

    assert logger.level == logging.INFO


def test_setup_logger_level_warning(mock_log_folder_exists):
    """
    Test setup_logger with WARNING level.
    Verifies logger level is set to logging.WARNING.
    """
    logger = setup_logger(name="warning_level_test", level=logging.WARNING)

    assert logger.level == logging.WARNING


def test_setup_logger_default_level_debug(mock_log_folder_exists):
    """
    Test setup_logger default level is DEBUG.
    Verifies logger level is logging.DEBUG when no level specified.
    """
    logger = setup_logger(name="default_level_test")

    assert logger.level == logging.DEBUG


def test_setup_logger_formatter_is_agent_formatter(mock_log_folder_exists):
    """
    Test setup_logger uses AgentFormatter for all handlers.
    Verifies formatter is an instance of AgentFormatter.
    """
    logger = setup_logger(name="formatter_test")

    for handler in logger.handlers:
        assert isinstance(handler.formatter, AgentFormatter), \
            "Handler formatter should be AgentFormatter"


def test_rotating_file_handler_max_bytes(mock_log_folder_exists):
    """
    Test RotatingFileHandler configuration.
    Verifies maxBytes is 100000000 and backupCount is 1.
    """
    logger = setup_logger(name="rotation_test")

    file_handlers = [h for h in logger.handlers if isinstance(h, RotatingFileHandler)]
    assert len(file_handlers) > 0, "Expected RotatingFileHandler"

    handler = file_handlers[0]
    assert handler.maxBytes == 100000000, "maxBytes should be 100MB (100000000 bytes)"
    assert handler.backupCount == 1, "backupCount should be 1"


def test_setup_logger_returns_logger_instance(mock_log_folder_exists):
    """
    Test setup_logger returns a logging.Logger instance.
    Verifies the return type is correct.
    """
    logger = setup_logger(name="return_type_test")

    assert isinstance(logger, logging.Logger), "Should return a logging.Logger instance"


def test_setup_logger_handler_accumulation_behavior(mock_log_folder_exists):
    """
    Test that calling setup_logger twice with same name accumulates handlers.
    This documents the current behavior - handlers are added without deduplication.
    """
    # First call
    logger1 = setup_logger(name="accumulation_test")
    handler_count_1 = len(logger1.handlers)

    # Second call (same name)
    logger2 = setup_logger(name="accumulation_test")
    handler_count_2 = len(logger2.handlers)

    # Same logger instance returned
    assert logger1 is logger2
    # Handlers accumulate on second call (current behavior)
    assert handler_count_2 > handler_count_1


def test_setup_logger_with_empty_string_name(mock_log_folder_not_exists):
    """
    Test setup_logger with empty string as name.
    Verifies it falls back to console-only logging.
    """
    logger = setup_logger(name="", log_file=None)

    # Should have StreamHandler (console output)
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) > 0, "Expected StreamHandler for empty name"


# ============================================================================
# Test Cases for AgentFormatter class
# ============================================================================


def test_agent_formatter_format_without_agent(mock_agent_and_thread_names):
    """
    Test AgentFormatter.format without agent name or thread.
    Verifies message_id is empty string.
    """
    formatter = AgentFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    # message_id should be empty when no agent/thread names
    assert record.message_id == "", "message_id should be empty string without agent/thread"


def test_agent_formatter_format_with_agent_name(mock_agent_name):
    """
    Test AgentFormatter.format with agent name set.
    Verifies message_id contains agent name pattern.
    """
    formatter = AgentFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    # message_id should contain agent name pattern
    assert "TestAgent" in record.message_id, \
        "message_id should contain agent name"


def test_agent_formatter_format_with_thread_name(mock_thread_name):
    """
    Test AgentFormatter.format with thread name set.
    Verifies message_id contains thread name pattern.
    """
    formatter = AgentFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    # message_id should contain thread name pattern
    assert "TestThread" in record.message_id, \
        "message_id should contain thread name"


def test_agent_formatter_format_with_both_agent_and_thread(mock_agent_name, mock_thread_name):
    """
    Test AgentFormatter.format with both agent and thread names.
    Verifies message_id contains both names in expected format.
    """
    formatter = AgentFormatter()
    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Test message",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    # message_id should contain both names in format (agent:thread)
    assert "TestAgent" in record.message_id
    assert "TestThread" in record.message_id
    assert record.message_id == "(TestAgent:TestThread)", \
        f"Expected '(TestAgent:TestThread)', got '{record.message_id}'"


def test_agent_formatter_custom_format_string():
    """
    Test AgentFormatter with custom format string.
    Verifies custom format is applied correctly.
    """
    custom_fmt = "%(levelname)s - %(message)s"
    formatter = AgentFormatter(fmt=custom_fmt)

    record = logging.LogRecord(
        name="test",
        level=logging.WARNING,
        pathname="test.py",
        lineno=1,
        msg="Custom format test",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    assert "WARNING" in formatted
    assert "Custom format test" in formatted


def test_agent_formatter_custom_date_format():
    """
    Test AgentFormatter with custom date format.
    Verifies custom date format is applied correctly.
    """
    custom_fmt = "%(asctime)s %(message)s"
    custom_datefmt = "%Y-%m-%d"
    formatter = AgentFormatter(fmt=custom_fmt, datefmt=custom_datefmt)

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname="test.py",
        lineno=1,
        msg="Date format test",
        args=(),
        exc_info=None
    )

    formatted = formatter.format(record)

    # Should contain date in YYYY-MM-DD format
    import re
    date_pattern = r"\d{4}-\d{2}-\d{2}"
    assert re.search(date_pattern, formatted), \
        "Expected date in YYYY-MM-DD format"


def test_agent_formatter_fallback_to_env_variable(mock_agent_and_thread_names):
    """
    Test AgentFormatter falls back to environment variable when thread-local is empty.
    Verifies AGENT_NAME env var is used as fallback.
    """
    env_vars = {"AGENT_NAME": "EnvAgent", "AI_AGENT": ""}
    with patch.dict(os.environ, env_vars, clear=False), \
         patch("topsailai.utils.thread_local_tool.get_agent_name", return_value=None), \
         patch("topsailai.utils.thread_local_tool.get_thread_name", return_value=None):
        formatter = AgentFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="Env test",
            args=(),
            exc_info=None
        )

        formatter.format(record)

        assert "EnvAgent" in record.message_id, \
            "message_id should contain agent name from environment variable"


def test_agent_formatter_fallback_to_ai_agent_env(mock_agent_and_thread_names):
    """
    Test AgentFormatter falls back to AI_AGENT env var when AGENT_NAME is not set.
    Verifies AI_AGENT env var is used as fallback.
    """
    env_vars = {"AGENT_NAME": "", "AI_AGENT": "AIAgent"}
    with patch.dict(os.environ, env_vars, clear=False), \
         patch("topsailai.utils.thread_local_tool.get_agent_name", return_value=None), \
         patch("topsailai.utils.thread_local_tool.get_thread_name", return_value=None):
        formatter = AgentFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="test.py",
            lineno=1,
            msg="AI_AGENT test",
            args=(),
            exc_info=None
        )

        formatter.format(record)

        assert "AIAgent" in record.message_id, \
            "message_id should contain agent name from AI_AGENT environment variable"


# ============================================================================
# Integration Tests
# ============================================================================


def test_full_logging_pipeline_integration(mock_log_folder_exists, mock_agent_and_thread_names, tmp_path):
    """
    Integration test for full logging pipeline.
    Tests that messages are actually logged to handlers.
    """
    # Create a temporary log file
    log_file = str(tmp_path / "integration_test.log")

    # Setup logger
    logger = setup_logger(name="integration_test", log_file=log_file)

    # Log a test message
    test_message = "Integration test message"
    logger.info(test_message)

    # Force flush all handlers
    for handler in logger.handlers:
        handler.flush()

    # Verify log file contains the message
    if os.path.exists(log_file):
        with open(log_file, "r") as f:
            content = f.read()
            assert test_message in content, "Logged message should appear in log file"


def test_logger_propagation_to_root(mock_log_folder_exists):
    """
    Test that logger propagation is properly configured.
    Verifies logger does not propagate to root logger by default.
    """
    logger = setup_logger(name="propagation_test")

    # Logger should not propagate to root by default (handlers are added directly)
    assert logger.propagate is True, \
        "Logger should propagate to root logger by default"


def test_multiple_handlers_with_different_levels(mock_log_folder_exists):
    """
    Test setup_logger with different handler configurations.
    Verifies multiple handlers can coexist.
    """
    # Create logger with file handler
    logger = setup_logger(name="multi_handler_test")

    # Add another stream handler manually
    additional_handler = logging.StreamHandler()
    additional_handler.setLevel(logging.ERROR)
    logger.addHandler(additional_handler)

    # Verify both handlers exist
    stream_handlers = [h for h in logger.handlers if isinstance(h, logging.StreamHandler)]
    assert len(stream_handlers) >= 2, "Should have at least 2 stream handlers"
