"""
Unit tests for topsailai.tools.ctx_tool module.

Tests context retrieval functionality, message archiving,
error handling, and edge cases.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, '/root/ai/TopsailAI/src/topsailai')

from topsailai.tools.ctx_tool import (
    retrieve_msg,
    TOOLS,
)


class TestRetrieveMsgWithNoAgent(unittest.TestCase):
    """Test retrieve_msg when agent object is None."""

    def test_retrieve_msg_returns_empty_when_agent_is_none(self):
        """Test that retrieve_msg returns empty string when agent is None."""
        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=None):
            result = retrieve_msg("test_msg_id")
            self.assertEqual(result, "")

    def test_retrieve_msg_logs_error_when_agent_is_none(self):
        """Test that retrieve_msg logs error when agent is None."""
        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=None):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                retrieve_msg("test_msg_id")
                mock_logger.error.assert_called_once_with("no found agent object")


class TestRetrieveMsgWithAgent(unittest.TestCase):
    """Test retrieve_msg when agent object exists."""

    def test_retrieve_msg_returns_message_from_hook(self):
        """Test that retrieve_msg returns message from hook."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = "test message content"
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("msg_123")
            self.assertEqual(result, "test message content")
            mock_manager.retrieve_message.assert_called_once_with("msg_123")

    def test_retrieve_msg_returns_empty_when_message_not_found(self):
        """Test that retrieve_msg returns empty string when message not found."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = ""
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("nonexistent_msg")
            self.assertEqual(result, "")

    def test_retrieve_msg_logs_error_when_message_not_found(self):
        """Test that retrieve_msg logs error when message not found."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = ""
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                result = retrieve_msg("nonexistent_msg")
                mock_logger.error.assert_called_once()
                call_args = mock_logger.error.call_args[0][0]
                self.assertIn("nonexistent_msg", call_args)

    def test_retrieve_msg_searches_multiple_hooks(self):
        """Test that retrieve_msg searches through multiple hooks."""
        mock_agent = MagicMock()
        mock_manager1 = MagicMock()
        mock_manager1.retrieve_message.return_value = ""
        mock_manager2 = MagicMock()
        mock_manager2.retrieve_message.return_value = "found message"
        mock_manager3 = MagicMock()
        mock_agent.hooks_ctx_history = [mock_manager1, mock_manager2, mock_manager3]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("msg_456")
            self.assertEqual(result, "found message")
            # Should stop after finding the message
            mock_manager3.retrieve_message.assert_not_called()

    def test_retrieve_msg_with_empty_hooks_list(self):
        """Test retrieve_msg when hooks_ctx_history is empty."""
        mock_agent = MagicMock()
        mock_agent.hooks_ctx_history = []

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                result = retrieve_msg("msg_789")
                self.assertEqual(result, "")
                mock_logger.error.assert_called_once()


class TestRetrieveMsgEdgeCases(unittest.TestCase):
    """Test retrieve_msg edge cases."""

    def test_retrieve_msg_with_empty_string_msg_id(self):
        """Test retrieve_msg with empty string msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = ""
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                result = retrieve_msg("")
                self.assertEqual(result, "")

    def test_retrieve_msg_with_unicode_msg_id(self):
        """Test retrieve_msg with unicode msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = "unicode message"
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("msg_测试_123")
            self.assertEqual(result, "unicode message")

    def test_retrieve_msg_with_special_characters_msg_id(self):
        """Test retrieve_msg with special characters in msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = "special chars message"
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("msg-id_123.special@chars")
            self.assertEqual(result, "special chars message")

    def test_retrieve_msg_with_long_msg_id(self):
        """Test retrieve_msg with long msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = "long message"
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            long_msg_id = "msg_" + "a" * 1000
            result = retrieve_msg(long_msg_id)
            self.assertEqual(result, "long message")

    def test_retrieve_msg_returns_first_found_message(self):
        """Test that retrieve_msg returns first found message."""
        mock_agent = MagicMock()
        mock_manager1 = MagicMock()
        mock_manager1.retrieve_message.return_value = "first message"
        mock_manager2 = MagicMock()
        mock_manager2.retrieve_message.return_value = "second message"
        mock_agent.hooks_ctx_history = [mock_manager1, mock_manager2]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            result = retrieve_msg("msg_abc")
            self.assertEqual(result, "first message")


class TestToolsConstant(unittest.TestCase):
    """Test TOOLS constant."""

    def test_tools_is_dict(self):
        """Test that TOOLS is a dictionary."""
        self.assertIsInstance(TOOLS, dict)

    def test_tools_contains_retrieve_msg(self):
        """Test that TOOLS contains retrieve_msg."""
        self.assertIn("retrieve_msg", TOOLS)

    def test_tools_retrieve_msg_is_callable(self):
        """Test that TOOLS['retrieve_msg'] is callable."""
        self.assertTrue(callable(TOOLS["retrieve_msg"]))

    def test_tools_retrieve_msg_is_correct_function(self):
        """Test that TOOLS['retrieve_msg'] is the correct function."""
        from topsailai.tools.ctx_tool import retrieve_msg as direct_func
        self.assertEqual(TOOLS["retrieve_msg"], direct_func)


class TestRetrieveMsgInvalidInputs(unittest.TestCase):
    """Test retrieve_msg with invalid inputs."""

    def test_retrieve_msg_with_none_msg_id(self):
        """Test retrieve_msg with None msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = ""
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                result = retrieve_msg(None)
                self.assertEqual(result["status"], "invalid_request")
                self.assertIn("msg_id", result["reason"])

    def test_retrieve_msg_with_integer_msg_id(self):
        """Test retrieve_msg with integer msg_id."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = ""
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch('topsailai.tools.ctx_tool.get_agent_object', return_value=mock_agent):
            with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
                result = retrieve_msg(12345)
                self.assertEqual(result["status"], "invalid_request")
                self.assertIn("msg_id", result["reason"])


if __name__ == '__main__':
    unittest.main()


class TestRetrieveMsgNativeToolCallsDisabled(unittest.TestCase):
    """Test retrieve_msg short-circuits when native tool calls are enabled."""

    def setUp(self):
        self._orig_use = os.environ.get("USE_TOOL_CALLS")
        self._orig_topsailai_use = os.environ.get("TOPSAILAI_USE_TOOL_CALLS")

    def tearDown(self):
        if self._orig_use is None:
            os.environ.pop("USE_TOOL_CALLS", None)
        else:
            os.environ["USE_TOOL_CALLS"] = self._orig_use
        if self._orig_topsailai_use is None:
            os.environ.pop("TOPSAILAI_USE_TOOL_CALLS", None)
        else:
            os.environ["TOPSAILAI_USE_TOOL_CALLS"] = self._orig_topsailai_use

    def test_retrieve_msg_disabled_when_native_tool_calls_enabled(self):
        """Test that retrieve_msg returns empty when native tool calls are enabled."""
        os.environ["TOPSAILAI_USE_TOOL_CALLS"] = "1"
        with patch('topsailai.tools.ctx_tool.get_agent_object') as mock_get_agent:
            result = retrieve_msg("any_msg_id")
            self.assertEqual(result, "")
            # Agent lookup must not happen when disabled.
            mock_get_agent.assert_not_called()

    def test_retrieve_msg_logs_warning_when_disabled(self):
        """Test that retrieve_msg logs a warning (not an error) when disabled."""
        os.environ["TOPSAILAI_USE_TOOL_CALLS"] = "1"
        with patch('topsailai.tools.ctx_tool.logger') as mock_logger:
            retrieve_msg("any_msg_id")
            mock_logger.warning.assert_called_once()
            mock_logger.error.assert_not_called()

    def test_flag_tool_enabled_false_when_native_tool_calls_enabled(self):
        """Test that FLAG_TOOL_ENABLED is False when native tool calls are enabled."""
        os.environ["TOPSAILAI_USE_TOOL_CALLS"] = "1"
        import importlib
        mod = importlib.import_module("topsailai.tools.ctx_tool")
        importlib.reload(mod)
        self.assertFalse(mod.FLAG_TOOL_ENABLED)

    def test_flag_tool_enabled_true_when_native_tool_calls_disabled(self):
        """Test that FLAG_TOOL_ENABLED is True when native tool calls are disabled."""
        os.environ.pop("TOPSAILAI_USE_TOOL_CALLS", None)
        os.environ.pop("USE_TOOL_CALLS", None)
        import importlib
        mod = importlib.import_module("topsailai.tools.ctx_tool")
        importlib.reload(mod)
        self.assertTrue(mod.FLAG_TOOL_ENABLED)


class TestRetrieveMsgAvailability(unittest.TestCase):
    """Test retrieve_msg availability across archive and tool-call modes."""

    def test_retrieve_msg_available_when_archive_enabled_and_tool_calls_disabled(self):
        """Test retrieval when archiving is enabled and native tool calls are disabled."""
        mock_agent = MagicMock()
        mock_manager = MagicMock()
        mock_manager.retrieve_message.return_value = "archived message"
        mock_agent.hooks_ctx_history = [mock_manager]

        with patch("topsailai.tools.ctx_tool.is_use_tool_calls", return_value=False):
            with patch("topsailai.tools.ctx_tool.is_archive_message_enabled", return_value=True):
                with patch("topsailai.tools.ctx_tool.get_agent_object", return_value=mock_agent):
                    result = retrieve_msg("msg_enabled")

        self.assertEqual(result, "archived message")
        mock_manager.retrieve_message.assert_called_once_with("msg_enabled")

    def test_retrieve_msg_disabled_when_archive_disabled(self):
        """Test retrieval short-circuits when archiving is disabled."""
        with patch("topsailai.tools.ctx_tool.is_use_tool_calls", return_value=False):
            with patch("topsailai.tools.ctx_tool.is_archive_message_enabled", return_value=False):
                with patch("topsailai.tools.ctx_tool.get_agent_object") as mock_get_agent:
                    result = retrieve_msg("msg_disabled")

        self.assertEqual(result, "")
        mock_get_agent.assert_not_called()

    def test_retrieve_msg_disabled_when_native_tool_calls_enabled(self):
        """Test native tool calls still disable retrieval when archiving is enabled."""
        with patch("topsailai.tools.ctx_tool.is_use_tool_calls", return_value=True):
            with patch("topsailai.tools.ctx_tool.is_archive_message_enabled", return_value=True):
                with patch("topsailai.tools.ctx_tool.get_agent_object") as mock_get_agent:
                    result = retrieve_msg("msg_native_tools")

        self.assertEqual(result, "")
        mock_get_agent.assert_not_called()

    def test_flag_tool_enabled_false_when_archive_disabled(self):
        """Test the tool registry flag is false when archiving is disabled."""
        import importlib

        original = os.environ.get("TOPSAILAI_ARCHIVE_MESSAGE_ENABLED")
        mod = importlib.import_module("topsailai.tools.ctx_tool")
        try:
            os.environ["TOPSAILAI_ARCHIVE_MESSAGE_ENABLED"] = "0"
            importlib.reload(mod)
            self.assertFalse(mod.FLAG_TOOL_ENABLED)
        finally:
            if original is None:
                os.environ.pop("TOPSAILAI_ARCHIVE_MESSAGE_ENABLED", None)
            else:
                os.environ["TOPSAILAI_ARCHIVE_MESSAGE_ENABLED"] = original
            importlib.reload(mod)
