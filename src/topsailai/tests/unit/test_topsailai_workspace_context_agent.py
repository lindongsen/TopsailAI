"""
Unit tests for workspace/context/agent.py - ContextRuntimeUtils and ContextRuntimeAIAgent classes.

This module tests the context runtime utilities for managing AI agent sessions
and messages, including session management, message handling, and tool operations.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import MagicMock, patch


class TestContextRuntimeUtils(unittest.TestCase):
    """Test suite for ContextRuntimeUtils class."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock ContextRuntimeData
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-123"
        self.mock_ctx_runtime_data.messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        self.mock_ctx_runtime_data.ai_agent = MagicMock()

        # Import after mocking
        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeUtils
            self.utils_class = ContextRuntimeUtils
            self.utils = self.utils_class(self.mock_ctx_runtime_data)

    def test_init_with_ctx_runtime_data(self):
        """Test initialization with ContextRuntimeData."""
        self.assertEqual(self.utils.ctx_runtime_data, self.mock_ctx_runtime_data)

    def test_session_id_property(self):
        """Test session_id property returns correct value."""
        self.assertEqual(self.utils.session_id, "test-session-123")

    def test_messages_property(self):
        """Test messages property returns correct list."""
        expected_messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"}
        ]
        self.assertEqual(self.utils.messages, expected_messages)

    def test_ai_agent_property(self):
        """Test ai_agent property returns correct agent."""
        self.assertEqual(self.utils.ai_agent, self.mock_ctx_runtime_data.ai_agent)

    def test_session_id_empty(self):
        """Test session_id property with empty session."""
        self.mock_ctx_runtime_data.session_id = ""
        utils = self.utils_class(self.mock_ctx_runtime_data)
        self.assertEqual(utils.session_id, "")

    def test_messages_empty(self):
        """Test messages property with empty messages."""
        self.mock_ctx_runtime_data.messages = []
        utils = self.utils_class(self.mock_ctx_runtime_data)
        self.assertEqual(utils.messages, [])


class TestContextRuntimeAIAgent(unittest.TestCase):
    """Test suite for ContextRuntimeAIAgent class."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock ContextRuntimeData
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-456"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.append_message = MagicMock()

        # Mock AI agent
        self.mock_ai_agent = MagicMock()
        self.mock_ai_agent.messages = [
            {"role": "user", "content": "Test message"}
        ]
        self.mock_ctx_runtime_data.ai_agent = self.mock_ai_agent

        # Import after mocking
        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeAIAgent
            self.agent_class = ContextRuntimeAIAgent
            self.agent = self.agent_class(self.mock_ctx_runtime_data)

    def test_init_inheritance(self):
        """Test that ContextRuntimeAIAgent inherits from ContextRuntimeUtils."""
        from topsailai.workspace.context.agent import ContextRuntimeUtils
        self.assertIsInstance(self.agent, ContextRuntimeUtils)

    def test_init_with_ctx_runtime_data(self):
        """Test initialization with ContextRuntimeData."""
        self.assertEqual(self.agent.ctx_runtime_data, self.mock_ctx_runtime_data)

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_with_provided_message(self, mock_ctx_manager):
        """Test add_session_message with provided message."""
        message = {"role": "user", "content": "New message"}
        self.agent.add_session_message(message)

        # Verify message was added to session
        mock_ctx_manager.add_session_message.assert_called_once_with(
            "test-session-456", message
        )
        # Verify message was appended to runtime data
        self.mock_ctx_runtime_data.append_message.assert_called_once_with(message)

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_without_provided_message(self, mock_ctx_manager):
        """Test add_session_message without provided message uses last agent message."""
        self.agent.add_session_message()

        # Verify last message from ai_agent was used
        expected_message = self.mock_ai_agent.messages[-1]
        mock_ctx_manager.add_session_message.assert_called_once_with(
            "test-session-456", expected_message
        )
        self.mock_ctx_runtime_data.append_message.assert_called_once_with(expected_message)

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_no_session_id(self, mock_ctx_manager):
        """Test add_session_message when session_id is empty."""
        self.mock_ctx_runtime_data.session_id = ""
        agent = self.agent_class(self.mock_ctx_runtime_data)
        message = {"role": "user", "content": "Test"}

        agent.add_session_message(message)

        # Verify ctx_manager was not called
        mock_ctx_manager.add_session_message.assert_not_called()
        # But message was still appended
        self.mock_ctx_runtime_data.append_message.assert_called_once_with(message)

    def test_add_runtime_messages_with_messages(self):
        """Test add_runtime_messages when there are runtime messages."""
        self.mock_ctx_runtime_data.messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Context message"}
        ]

        self.agent.add_runtime_messages()

        # Verify messages were added to ai_agent
        self.assertEqual(
            self.mock_ai_agent.messages,
            [
                {"role": "user", "content": "Test message"},
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Context message"}
            ]
        )

    def test_add_runtime_messages_empty(self):
        """Test add_runtime_messages when there are no runtime messages."""
        self.mock_ctx_runtime_data.messages = []
        initial_messages = self.mock_ai_agent.messages.copy()

        self.agent.add_runtime_messages()

        # Verify no messages were added
        self.assertEqual(self.mock_ai_agent.messages, initial_messages)

    def test_add_runtime_messages_none(self):
        """Test add_runtime_messages when messages is None."""
        self.mock_ctx_runtime_data.messages = None
        initial_messages = self.mock_ai_agent.messages.copy()

        self.agent.add_runtime_messages()

        # Verify no messages were added
        self.assertEqual(self.mock_ai_agent.messages, initial_messages)


class TestContextRuntimeUtilsEdgeCases(unittest.TestCase):
    """Test suite for edge cases in ContextRuntimeUtils."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ctx_runtime_data = MagicMock()

    def test_init_with_none_session_id(self):
        """Test initialization with None session_id."""
        self.mock_ctx_runtime_data.session_id = None
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = None

        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeUtils
            utils = ContextRuntimeUtils(self.mock_ctx_runtime_data)
            self.assertIsNone(utils.session_id)

    def test_init_with_none_messages(self):
        """Test initialization with None messages."""
        self.mock_ctx_runtime_data.session_id = "session"
        self.mock_ctx_runtime_data.messages = None
        self.mock_ctx_runtime_data.ai_agent = None

        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeUtils
            utils = ContextRuntimeUtils(self.mock_ctx_runtime_data)
            self.assertIsNone(utils.messages)

    def test_init_with_none_ai_agent(self):
        """Test initialization with None ai_agent."""
        self.mock_ctx_runtime_data.session_id = "session"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = None

        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeUtils
            utils = ContextRuntimeUtils(self.mock_ctx_runtime_data)
            self.assertIsNone(utils.ai_agent)


class TestContextRuntimeAIAgentEdgeCases(unittest.TestCase):
    """Test suite for edge cases in ContextRuntimeAIAgent."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.append_message = MagicMock()

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_empty_agent_messages(self, mock_ctx_manager):
        """Test add_session_message when ai_agent has no messages."""
        self.mock_ai_agent = MagicMock()
        self.mock_ai_agent.messages = []
        self.mock_ctx_runtime_data.ai_agent = self.mock_ai_agent

        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeAIAgent
            agent = ContextRuntimeAIAgent(self.mock_ctx_runtime_data)

            # Should raise AssertionError
            with self.assertRaises(AssertionError):
                agent.add_session_message()

    @patch("topsailai.workspace.context.agent.ctx_manager")
    def test_add_session_message_with_various_roles(self, mock_ctx_manager):
        """Test add_session_message with different message roles."""
        self.mock_ai_agent = MagicMock()
        self.mock_ai_agent.messages = [
            {"role": "system", "content": "System"},
            {"role": "user", "content": "User"},
            {"role": "assistant", "content": "Assistant"}
        ]
        self.mock_ctx_runtime_data.ai_agent = self.mock_ai_agent

        with patch("topsailai.workspace.context.agent.ContextRuntimeData"):
            from topsailai.workspace.context.agent import ContextRuntimeAIAgent
            agent = ContextRuntimeAIAgent(self.mock_ctx_runtime_data)

            # Test with assistant message
            agent.add_session_message()
            expected_message = self.mock_ai_agent.messages[-1]
            mock_ctx_manager.add_session_message.assert_called_with(
                "test-session", expected_message
            )


if __name__ == "__main__":
    unittest.main()
