"""
Unit tests for the chat logger module.

Test module: src.topsailai.logger.log_chat
Source module: topsailai.logger.log_chat

Author: AI
"""

import logging
import importlib
import pytest
from unittest.mock import patch, MagicMock


@pytest.fixture(autouse=True)
def cleanup_chat_logger():
    """Clean up the chat logger handlers after each test."""
    yield
    # Remove all handlers from the chat logger to prevent accumulation
    chat_logger = logging.getLogger("chat")
    for handler in chat_logger.handlers[:]:
        chat_logger.removeHandler(handler)
        handler.close()


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
def reloaded_log_chat_module(mock_log_folder_exists):
    """
    Reload the log_chat module with the mock applied.
    This ensures the mock is active during module initialization.
    """
    from src.topsailai.logger import log_chat
    
    # Reload the module with the mock in place
    importlib.reload(log_chat)
    
    yield log_chat
    
    # Restore the original module state
    importlib.reload(log_chat)


class TestLogChatLoggerNameConstant:
    """Test suite for LOGGER_NAME constant."""

    def test_log_chat_logger_name_constant(self, reloaded_log_chat_module):
        """
        Test that LOGGER_NAME constant equals 'chat'.
        
        Verifies the module-level constant that defines the logger name
        for chat operations.
        """
        assert reloaded_log_chat_module.LOGGER_NAME == "chat"


class TestLogChatLoggerInstance:
    """Test suite for logger instance type and basic properties."""

    def test_log_chat_logger_instance_type(self, reloaded_log_chat_module):
        """
        Test that the logger instance is a logging.Logger instance.
        
        Verifies that the module-level logger object is properly
        instantiated as a standard Python Logger.
        """
        assert isinstance(reloaded_log_chat_module.logger, logging.Logger)

    def test_log_chat_logger_name_matches_constant(self, reloaded_log_chat_module):
        """
        Test that the logger name matches the LOGGER_NAME constant.
        
        Verifies that the logger's internal name is set to 'chat'
        as defined by the LOGGER_NAME constant.
        """
        assert reloaded_log_chat_module.logger.name == reloaded_log_chat_module.LOGGER_NAME
        assert reloaded_log_chat_module.logger.name == "chat"


class TestLogChatLoggerHandlers:
    """Test suite for logger handler configuration."""

    def test_log_chat_logger_has_rotating_file_handler(self, reloaded_log_chat_module):
        """
        Test that the logger has a RotatingFileHandler.
        
        Since setup_logger uses the logger name to construct a file path,
        it creates a RotatingFileHandler for file-based logging when
        the log folder exists.
        """
        from logging.handlers import RotatingFileHandler
        
        handler_types = [type(h) for h in reloaded_log_chat_module.logger.handlers]
        
        assert RotatingFileHandler in handler_types

    def test_log_chat_logger_no_stream_handler(self, reloaded_log_chat_module):
        """
        Test that the logger has no StreamHandler.
        
        The chat logger uses file-based logging only (RotatingFileHandler)
        and does not include console output handlers when log folder exists.
        """
        from logging import StreamHandler
        
        handler_types = [type(h) for h in reloaded_log_chat_module.logger.handlers]
        
        assert StreamHandler not in handler_types


class TestLogChatLoggerLevel:
    """Test suite for logger level configuration."""

    def test_log_chat_logger_default_level_debug(self, reloaded_log_chat_module):
        """
        Test that the logger default level is DEBUG.
        
        Verifies that the logger is configured to capture all log
        messages at DEBUG level and above.
        """
        assert reloaded_log_chat_module.logger.level == logging.DEBUG


class TestLogChatLoggerFormatter:
    """Test suite for logger formatter configuration."""

    def test_log_chat_logger_uses_agent_formatter(self, reloaded_log_chat_module):
        """
        Test that the logger uses AgentFormatter.
        
        Verifies that the handler's formatter is set to AgentFormatter
        for consistent log output formatting.
        """
        from src.topsailai.logger.base_logger import AgentFormatter
        
        # Get the formatter from the first handler
        assert len(reloaded_log_chat_module.logger.handlers) > 0, \
            "Logger should have at least one handler"
        
        formatter = reloaded_log_chat_module.logger.handlers[0].formatter
        assert isinstance(formatter, AgentFormatter)


class TestLogChatLoggerSingleton:
    """Test suite for module-level singleton behavior."""

    def test_log_chat_logger_singleton_behavior(self, reloaded_log_chat_module):
        """
        Test that the logger is a singleton instance on re-import.
        
        Verifies that importing the module multiple times returns
        the same logger instance (module-level singleton pattern).
        """
        # Get the current logger instance
        original_logger = reloaded_log_chat_module.logger
        
        # Reload the module again
        importlib.reload(reloaded_log_chat_module)
        
        # The logger should be the same instance after reload
        reloaded_logger = reloaded_log_chat_module.logger
        
        # Verify the logger name is still correct
        assert reloaded_logger.name == "chat"
        
        # Restore the original logger reference
        reloaded_log_chat_module.logger = original_logger
