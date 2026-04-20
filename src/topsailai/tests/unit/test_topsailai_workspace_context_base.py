"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Unit tests for workspace/context/base.py - ContextRuntimeBase class.
"""

import unittest
from unittest.mock import MagicMock, patch


class TestContextRuntimeBaseInitialization(unittest.TestCase):
    """Test suite for ContextRuntimeBase initialization."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.agent_type = "test_agent"

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_init_default_values(self, mock_agent_base):
        """Test that default initialization sets correct default values."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()

        self.assertEqual(runtime.session_id, "")
        self.assertEqual(runtime.messages, [])
        self.assertIsNone(runtime.ai_agent)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_init_with_session_and_agent(self, mock_agent_base):
        """Test that init() sets session_id and ai_agent correctly."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.init("test_session_123", self.mock_agent)

        self.assertEqual(runtime.session_id, "test_session_123")
        self.assertEqual(runtime.ai_agent, self.mock_agent)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_init_resets_messages(self, mock_ctx_manager, mock_agent_base):
        """Test that init() resets messages from session storage."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_ctx_manager.get_messages_by_session.return_value = [
            {"role": "user", "content": "test"}
        ]

        runtime = ContextRuntimeBase()
        runtime.init("test_session", self.mock_agent)

        self.assertEqual(len(runtime.messages), 1)
        mock_ctx_manager.get_messages_by_session.assert_called_once_with("test_session")


class TestLastUserMessageProperty(unittest.TestCase):
    """Test suite for last_user_message property."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.json_tool')
    def test_last_user_message_with_messages(self, mock_json_tool, mock_agent_base):
        """Test getting last user message when messages exist."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        # The property iterates in reverse order
        # First it checks msg2 (index 1), finds user role -> returns msg2
        mock_json_tool.json_load.side_effect = [
            {"role": "user", "content": "last user message"},
        ]

        runtime = ContextRuntimeBase()
        runtime.messages = ["msg1", "msg2"]

        result = runtime.last_user_message

        self.assertEqual(result, "msg2")
        self.assertEqual(mock_json_tool.json_load.call_count, 1)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_last_user_message_empty(self, mock_agent_base):
        """Test last_user_message returns None when messages list is empty."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = []

        result = runtime.last_user_message

        self.assertIsNone(result)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.json_tool')
    def test_last_user_message_no_user_role(self, mock_json_tool, mock_agent_base):
        """Test last_user_message returns None when no user messages exist."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json_tool.json_load.return_value = {"role": "assistant", "content": "reply"}

        runtime = ContextRuntimeBase()
        runtime.messages = ["msg1", "msg2"]

        result = runtime.last_user_message

        self.assertIsNone(result)


class TestMessageOperations(unittest.TestCase):
    """Test suite for message operations."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.ctx_manager')
    def test_reset_messages_clears_list(self, mock_ctx_manager, mock_agent_base):
        """Test that reset_messages clears and reloads messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_ctx_manager.get_messages_by_session.return_value = []

        runtime = ContextRuntimeBase()
        runtime.session_id = "test_session"
        runtime.messages = [{"role": "user", "content": "old"}]

        runtime.reset_messages()

        self.assertEqual(runtime.messages, [])
        mock_ctx_manager.get_messages_by_session.assert_called_once_with("test_session")

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_append_message_adds_to_list(self, mock_agent_base):
        """Test that append_message adds message to the list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        message = {"role": "user", "content": "hello"}

        runtime.append_message(message)

        self.assertEqual(len(runtime.messages), 1)
        self.assertEqual(runtime.messages[0], message)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_append_message_empty_dict(self, mock_agent_base):
        """Test that append_message ignores empty message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()

        runtime.append_message({})

        self.assertEqual(len(runtime.messages), 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_append_message_none(self, mock_agent_base):
        """Test that append_message ignores None message."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()

        runtime.append_message(None)

        self.assertEqual(len(runtime.messages), 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_set_messages_replaces_list(self, mock_agent_base):
        """Test that set_messages replaces existing messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = [{"role": "user", "content": "old"}]

        new_messages = [{"role": "user", "content": "new1"}, {"role": "assistant", "content": "new2"}]
        runtime.set_messages(new_messages)

        self.assertEqual(len(runtime.messages), 2)
        self.assertEqual(runtime.messages[0]["content"], "new1")

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_set_messages_empty_list(self, mock_agent_base):
        """Test that set_messages with empty list clears messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = [{"role": "user", "content": "old"}]

        runtime.set_messages([])

        self.assertEqual(len(runtime.messages), 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_set_messages_same_reference(self, mock_agent_base):
        """Test that set_messages with same list reference does nothing."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.messages = [{"role": "user", "content": "test"}]

        # Set with same reference
        runtime.set_messages(runtime.messages)

        # Should still have 1 message
        self.assertEqual(len(runtime.messages), 1)


class TestGetQuantityThreshold(unittest.TestCase):
    """Test suite for _get_quantity_threshold method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_quantity_threshold_disabled(self, mock_env_tool, mock_agent_base):
        """Test that threshold returns 0 when disabled."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 0

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        self.assertEqual(result, 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_enabled(self, mock_random, mock_env_tool, mock_agent_base):
        """Test that threshold returns max of random choice and env value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 10
        mock_random.choice.return_value = 13

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        self.assertEqual(result, 13)
        mock_random.choice.assert_called_once()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_env_higher(self, mock_random, mock_env_tool, mock_agent_base):
        """Test that env value is used when higher than random choice."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 25
        mock_random.choice.return_value = 13

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold()

        self.assertEqual(result, 25)


class TestGetHeadOffsetToKeep(unittest.TestCase):
    """Test suite for _get_head_offset_to_keep_in_summary method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_head_offset_from_env(self, mock_env_tool, mock_agent_base):
        """Test getting head offset from environment variable."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 5

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary()

        self.assertEqual(result, 5)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_head_offset_negative_converted_to_zero(self, mock_env_tool, mock_agent_base):
        """Test that negative offset is converted to 0."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = -5

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary()

        self.assertEqual(result, 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_get_head_offset_explicit_value(self, mock_agent_base):
        """Test using explicit head_offset_to_keep value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        result = runtime._get_head_offset_to_keep_in_summary(head_offset_to_keep=10)

        self.assertEqual(result, 10)


class TestSummarizeMessages(unittest.TestCase):
    """Test suite for _summarize_messages method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.agent_type = "test_agent"

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    @patch('topsailai.workspace.context.base.json_tool')
    def test_summarize_messages_success(
        self, mock_json_tool, mock_story_tool, mock_summary_tool,
        mock_file_tool, mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Test successful message summarization."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_json_tool.json_dump.return_value = '[{"role": "user", "content": "test"}]'
        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent

        llm_chat, answer = runtime._summarize_messages([{"role": "user", "content": "test"}])

        self.assertEqual(answer, "Summarized content")
        mock_get_llm_chat.assert_called_once()

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_summarize_messages_empty_raises(self, mock_agent_base):
        """Test that empty messages raises AssertionError."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent

        with self.assertRaises(AssertionError) as context:
            runtime._summarize_messages([])

        self.assertIn("null of messages", str(context.exception))

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    @patch('topsailai.workspace.context.base.json_tool')
    def test_summarize_messages_string_input(
        self, mock_json_tool, mock_story_tool, mock_summary_tool,
        mock_file_tool, mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Test summarization with string input (not list)."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = None
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized string"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent

        llm_chat, answer = runtime._summarize_messages("string message")

        self.assertEqual(answer, "Summarized string")


if __name__ == '__main__':
    unittest.main()
