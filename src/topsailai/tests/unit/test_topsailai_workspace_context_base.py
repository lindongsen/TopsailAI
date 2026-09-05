"""
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-04-19
Purpose: Unit tests for workspace/context/base.py - ContextRuntimeBase class.
"""

import unittest
import json
import os
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

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_layer_specific_only(
        self, mock_random, mock_env_tool, mock_agent_base
    ):
        """Test that layer-specific env var is used when set."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        def _env_side_effect(key, **kwargs):
            if key == "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD":
                return 30
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return None
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_side_effect
        mock_random.choice.return_value = 13

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 30)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_legacy_fallback(
        self, mock_random, mock_env_tool, mock_agent_base
    ):
        """Test fallback to legacy shared env var when layer-specific is unset."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        def _env_side_effect(key, **kwargs):
            if key == "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD":
                return None
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return 20
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_side_effect
        mock_random.choice.return_value = 17

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 20)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_layer_specific_wins(
        self, mock_random, mock_env_tool, mock_agent_base
    ):
        """Test that layer-specific env var takes precedence over legacy shared var."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        def _env_side_effect(key, **kwargs):
            if key == "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD":
                return 35
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return 10
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_side_effect
        mock_random.choice.return_value = 13

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 35)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_quantity_threshold_neither_set(
        self, mock_env_tool, mock_agent_base
    ):
        """Test that threshold is disabled when neither env var is set."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = None

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.random')
    def test_get_quantity_threshold_layer_zero_falls_back(
        self, mock_random, mock_env_tool, mock_agent_base
    ):
        """Test that zero layer-specific value falls back to legacy shared var."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        def _env_side_effect(key, **kwargs):
            if key == "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD":
                return 0
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return 22
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_side_effect
        mock_random.choice.return_value = 19

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 22)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_quantity_threshold_negative_disabled(
        self, mock_env_tool, mock_agent_base
    ):
        """Test that negative values are treated as disabled."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        def _env_side_effect(key, **kwargs):
            if key == "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD":
                return -5
            if key == "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD":
                return -1
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_side_effect

        runtime = ContextRuntimeBase()
        result = runtime._get_quantity_threshold(
            "TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD"
        )

        self.assertEqual(result, 0)


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

class TestGetTailOffsetToKeep(unittest.TestCase):
    """Test suite for _get_tail_offset_to_keep_in_summary method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_tail_offset_from_env(self, mock_env_tool, mock_agent_base):
        """Test getting tail offset from environment variable."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = 5

        runtime = ContextRuntimeBase()
        result = runtime._get_tail_offset_to_keep_in_summary()

        self.assertEqual(result, 5)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_tail_offset_negative_converted_to_zero(self, mock_env_tool, mock_agent_base):
        """Test that negative tail offset is converted to 0."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = -5

        runtime = ContextRuntimeBase()
        result = runtime._get_tail_offset_to_keep_in_summary()

        self.assertEqual(result, 0)

    @patch('topsailai.workspace.context.base.AgentBase')
    def test_get_tail_offset_explicit_value(self, mock_agent_base):
        """Test using explicit tail_offset_to_keep value."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        runtime = ContextRuntimeBase()
        result = runtime._get_tail_offset_to_keep_in_summary(tail_offset_to_keep=10)

        self.assertEqual(result, 10)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_tail_offset_default_zero(self, mock_env_tool, mock_agent_base):
        """Test default tail offset is 0 when env var is unset."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = None

        runtime = ContextRuntimeBase()
        result = runtime._get_tail_offset_to_keep_in_summary()

        self.assertEqual(result, 0)


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


class TestSummaryProcessor(unittest.TestCase):
    """Test summary processor selection and shared-model safety."""

    def setUp(self):
        """Create a runtime with an active model."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        self.runtime = ContextRuntimeBase()
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model = MagicMock()
        self.runtime.ai_agent.llm_model._pending_native_tool_call_responses = []

    @patch("topsailai.workspace.context.base.PromptBase")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_agent_processor_borrows_active_model(self, mock_env_tool, mock_prompt_base):
        """The agent processor wraps the active model without taking ownership."""
        mock_env_tool.EnvReaderInstance.get.return_value = "agent_llm_model"
        prompt_ctl = MagicMock()
        mock_prompt_base.return_value = prompt_ctl

        chat = self.runtime._build_summary_chat("summary input", "summary system")

        self.assertIs(chat.llm_model, self.runtime.ai_agent.llm_model)
        self.assertFalse(chat.owns_llm_model)
        prompt_ctl.new_session.assert_called_once_with(
            "summary input", need_print_message=False
        )
        chat.close()
        self.runtime.ai_agent.llm_model.close.assert_not_called()

    @patch("topsailai.workspace.context.base.get_llm_chat")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_default_processor_uses_independent_chat(self, mock_env_tool, mock_get_llm_chat):
        """The default processor preserves the independent-chat behavior."""
        mock_env_tool.EnvReaderInstance.get.return_value = "llm_chat"
        expected = MagicMock()
        mock_get_llm_chat.return_value = expected

        result = self.runtime._build_summary_chat("summary input", "summary system")

        self.assertIs(result, expected)
        mock_get_llm_chat.assert_called_once()

    @patch("topsailai.workspace.context.base.get_llm_chat")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_pending_native_responses_fall_back_without_mutation(
        self, mock_env_tool, mock_get_llm_chat
    ):
        """Pending native responses remain untouched when reuse is unsafe."""
        mock_env_tool.EnvReaderInstance.get.return_value = "agent_llm_model"
        pending = [object()]
        self.runtime.ai_agent.llm_model._pending_native_tool_call_responses = pending
        expected = MagicMock()
        mock_get_llm_chat.return_value = expected

        result = self.runtime._build_summary_chat("summary input", "summary system")

        self.assertIs(result, expected)
        self.assertIs(
            self.runtime.ai_agent.llm_model._pending_native_tool_call_responses,
            pending,
        )
        self.assertEqual(len(pending), 1)

    @patch("topsailai.workspace.context.base.get_llm_chat")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_invalid_processor_falls_back(self, mock_env_tool, mock_get_llm_chat):
        """An invalid processor value falls back to the independent chat."""
        mock_env_tool.EnvReaderInstance.get.return_value = "unknown"
        expected = MagicMock()
        mock_get_llm_chat.return_value = expected

        result = self.runtime._build_summary_chat("summary input", "summary system")

        self.assertIs(result, expected)

    @patch("topsailai.workspace.context.base.get_llm_chat")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_missing_agent_model_falls_back(self, mock_env_tool, mock_get_llm_chat):
        """A missing active model falls back to the independent chat."""
        mock_env_tool.EnvReaderInstance.get.return_value = "agent_llm_model"
        self.runtime.ai_agent = None
        expected = MagicMock()
        mock_get_llm_chat.return_value = expected

        result = self.runtime._build_summary_chat("summary input", "summary system")

        self.assertIs(result, expected)



class TestGetCurrentTokens(unittest.TestCase):
    """Test suite for _get_current_tokens method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_agent = MagicMock()
        self.mock_agent.llm_model.tokenStat.current_tokens = 1234

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_current_tokens_default_cached(self, mock_env_tool, mock_agent_base):
        """Test default behavior returns cached tokenStat.current_tokens."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent

        result = runtime._get_current_tokens()

        self.assertEqual(result, 1234)
        mock_env_tool.EnvReaderInstance.check_bool.assert_called_once_with(
            "TOPSAILAI_REALTIME_TOKEN_CALCULATION", False
        )

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.count_tokens')
    def test_get_current_tokens_realtime_with_messages(
        self, mock_count_tokens, mock_env_tool, mock_agent_base
    ):
        """Test real-time token calculation from provided messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = True
        mock_count_tokens.return_value = 42

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent

        result = runtime._get_current_tokens(messages=[{"role": "user", "content": "hi"}])

        self.assertEqual(result, 42)
        mock_count_tokens.assert_called_once()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.count_tokens')
    def test_get_current_tokens_realtime_uses_default_messages(
        self, mock_count_tokens, mock_env_tool, mock_agent_base
    ):
        """Test real-time calculation falls back to _get_token_calculation_messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = True
        mock_count_tokens.return_value = 99

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent
        runtime.ai_agent.messages = [{"role": "user", "content": "hello"}]

        result = runtime._get_current_tokens()

        self.assertEqual(result, 99)
        mock_count_tokens.assert_called_once_with(str(runtime.ai_agent.messages))

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_current_tokens_no_agent_returns_none(self, mock_env_tool, mock_agent_base):
        """Test that None is returned when no ai_agent is available."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        runtime = ContextRuntimeBase()
        runtime.ai_agent = None

        result = runtime._get_current_tokens()

        self.assertIsNone(result)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_current_tokens_no_llm_model_returns_none(
        self, mock_env_tool, mock_agent_base
    ):
        """Test that None is returned when llm_model is not available."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.llm_model = None

        result = runtime._get_current_tokens()

        self.assertIsNone(result)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_get_current_tokens_no_token_stat_returns_none(
        self, mock_env_tool, mock_agent_base
    ):
        """Test that None is returned when tokenStat is not available."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = False

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.llm_model.tokenStat = None

        result = runtime._get_current_tokens()

        self.assertIsNone(result)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.count_tokens')
    def test_get_current_tokens_realtime_no_messages_returns_none(
        self, mock_count_tokens, mock_env_tool, mock_agent_base
    ):
        """Test real-time mode returns None when no messages are available."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.check_bool.return_value = True

        runtime = ContextRuntimeBase()
        runtime.ai_agent = None
        runtime.messages = None

        result = runtime._get_current_tokens()

        self.assertIsNone(result)
        mock_count_tokens.assert_not_called()



class TestSummarizeRuntimeMessages(unittest.TestCase):
    """Test suite for _summarize_runtime_messages method."""

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
    def test_runtime_summary_uses_token_calculation_messages(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Test that runtime summary uses _get_token_calculation_messages source."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.side_effect = lambda key, **kwargs: (
            "runtime" if key == "TOPSAILAI_CONTEXT_SUMMARY_MODE"
            else kwargs.get("default")
        )
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent
        runtime.ai_agent.messages = [{"role": "assistant", "content": "short"}]
        runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]

        # Simulate User2Agent override: _get_token_calculation_messages returns self.messages
        runtime._get_token_calculation_messages = lambda: runtime.messages

        with patch("topsailai.workspace.context.base.logger") as mock_logger:
            runtime._summarize_runtime_messages([])

        # The LLM should receive self.messages, not the short ai_agent.messages
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 20)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "msg0")
        mock_logger.warning.assert_not_called()

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_runtime_summary_uses_fallback_when_longer(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Defensive fallback: use caller messages when longer than runtime store.

        The base implementation keeps a defensive fallback that switches to the
        caller-provided messages when they are longer than the runtime-derived
        message list, protecting against a pruned runtime store.
        """
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.side_effect = lambda key, **kwargs: (
            "runtime" if key == "TOPSAILAI_CONTEXT_SUMMARY_MODE"
            else kwargs.get("default")
        )
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.session_id = "session-shorter-runtime"
        runtime.ai_agent = self.mock_agent
        runtime.ai_agent.messages = [{"role": "user", "content": "agent-msg"}]
        runtime.messages = [{"role": "user", "content": f"session-msg-{i}"} for i in range(20)]

        fallback = [{"role": "user", "content": f"fallback-{i}"} for i in range(20)]
        with patch("topsailai.workspace.context.base.logger") as mock_logger:
            runtime._summarize_runtime_messages(fallback)

        # Defensive fallback chooses the longer caller-supplied messages.
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 20)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-0")
        mock_logger.warning.assert_called_once_with(
            "[_summarize_runtime_messages] runtime messages not used: "
            "fallback_reason=runtime_messages_shorter_than_caller, "
            "selected_source=caller_messages, runtime_message_count=%s, "
            "caller_message_count=%s, session_id=%s, runtime_class=%s, "
            "runtime_method=_summarize_runtime_messages",
            1,
            20,
            "session-shorter-runtime",
            "ContextRuntimeBase",
        )

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_runtime_summary_uses_agent_messages_when_longer(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Runtime summary uses ai_agent.messages when it is the longer source."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = self.mock_agent
        runtime.ai_agent.messages = [{"role": "user", "content": f"agent-msg-{i}"} for i in range(25)]
        runtime.messages = [{"role": "user", "content": f"session-msg-{i}"} for i in range(20)]

        fallback = [{"role": "user", "content": f"fallback-{i}"} for i in range(20)]
        runtime._summarize_runtime_messages(fallback)

        # When ai_agent.messages is longer than fallback, runtime store is used.
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 25)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-msg-0")
    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_runtime_summary_fallback_to_caller_messages(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Test fallback to caller-provided messages when runtime store is empty."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.side_effect = lambda key, **kwargs: (
            "runtime" if key == "TOPSAILAI_CONTEXT_SUMMARY_MODE"
            else kwargs.get("default")
        )
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.session_id = "session-empty-runtime"
        runtime.ai_agent = self.mock_agent
        runtime.ai_agent.messages = []
        runtime.messages = []

        fallback = [{"role": "user", "content": f"fallback-{i}"} for i in range(10)]
        with patch("topsailai.workspace.context.base.logger") as mock_logger:
            runtime._summarize_runtime_messages(fallback)

        # Should fall back to caller-provided messages
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 10)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-0")
        mock_logger.warning.assert_called_once_with(
            "[_summarize_runtime_messages] runtime messages not used: "
            "fallback_reason=runtime_messages_unavailable, "
            "selected_source=caller_messages, runtime_message_count=%s, "
            "caller_message_count=%s, session_id=%s, runtime_class=%s, "
            "runtime_method=_summarize_runtime_messages",
            0,
            10,
            "session-empty-runtime",
            "ContextRuntimeBase",
        )


    @patch("topsailai.workspace.context.base.get_tools_for_chat")
    @patch("topsailai.workspace.context.base.env_tool")
    def test_runtime_summary_forwards_active_agent_tools_for_any_processor(
        self, mock_env_tool, mock_get_tools_for_chat
    ):
        """The common runtime send path preserves Agent2LLM tool schema order."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        available_tools = {"first": MagicMock(), "second": MagicMock()}
        ordered_schemas = {
            "first": {"type": "function", "function": {"name": "first"}},
            "second": {"type": "function", "function": {"name": "second"}},
        }
        mock_env_tool.is_use_tool_calls.return_value = True
        mock_env_tool.is_interactive_mode.return_value = False
        mock_get_tools_for_chat.return_value = ordered_schemas

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.available_tools = available_tools
        runtime.ai_agent.messages = [{"role": "user", "content": "original"}]
        runtime._get_summary_prompt = MagicMock(return_value="summary prompt")
        summary_chat = MagicMock()
        summary_chat.chat.return_value = "summary"
        runtime._build_summary_chat = MagicMock(return_value=summary_chat)

        runtime._summarize_runtime_messages(runtime.ai_agent.messages)

        mock_get_tools_for_chat.assert_called_once_with(available_tools)
        self.assertEqual(
            summary_chat.chat.call_args.kwargs["tools"],
            list(ordered_schemas.values()),
        )
        self.assertEqual(
            summary_chat.chat.call_args.kwargs["tool_choice"],
            "auto",
        )


class TestMessageEqual(unittest.TestCase):
    """Test suite for _message_equal semantic comparison helper."""

    def setUp(self):
        from topsailai.workspace.context.base import ContextRuntimeBase
        self.runtime = ContextRuntimeBase()

    def test_same_object_identity(self):
        """Identical object references are equal without deep comparison."""
        msg = {"role": "user", "content": "hello"}
        self.assertTrue(self.runtime._message_equal(msg, msg))

    def test_plain_string_equal(self):
        """Plain string equality is detected directly."""
        self.assertTrue(self.runtime._message_equal("hello", "hello"))

    def test_plain_string_not_equal(self):
        """Different plain strings are not equal."""
        self.assertFalse(self.runtime._message_equal("hello", "world"))

    def test_dict_equal_different_instances(self):
        """Dicts with identical content but different instances are equal."""
        a = {"role": "user", "content": "hello"}
        b = {"role": "user", "content": "hello"}
        self.assertIsNot(a, b)
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_dict_not_equal(self):
        """Dicts with different content are not equal."""
        a = {"role": "user", "content": "hello"}
        b = {"role": "assistant", "content": "hello"}
        self.assertFalse(self.runtime._message_equal(a, b))

    def test_list_equal(self):
        """Lists with identical content are equal."""
        a = [{"role": "user", "content": "hello"}]
        b = [{"role": "user", "content": "hello"}]
        self.assertIsNot(a, b)
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_json_string_vs_dict_equal(self):
        """A JSON string and its parsed dict are equal."""
        dict_msg = {"role": "user", "content": "hello"}
        str_msg = '{"role": "user", "content": "hello"}'
        self.assertTrue(self.runtime._message_equal(str_msg, dict_msg))
        self.assertTrue(self.runtime._message_equal(dict_msg, str_msg))

    def test_json_string_vs_list_equal(self):
        """A JSON string and its parsed list are equal."""
        list_msg = [{"role": "user", "content": "hello"}]
        str_msg = '[{"role": "user", "content": "hello"}]'
        self.assertTrue(self.runtime._message_equal(str_msg, list_msg))

    def test_non_json_string_vs_dict_not_equal(self):
        """A non-JSON string must not match a dict."""
        self.assertFalse(self.runtime._message_equal("not json", {"role": "user"}))

    def test_nested_content_equal(self):
        """Nested dict/list message content is compared by value."""
        a = {
            "role": "user",
            "content": {
                "step_name": "observation",
                "raw_text": "result",
                "items": [1, 2, {"x": 3}],
            },
        }
        b = {
            "role": "user",
            "content": {
                "step_name": "observation",
                "raw_text": "result",
                "items": [1, 2, {"x": 3}],
            },
        }
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_nested_content_order_matters(self):
        """List order is part of value equality."""
        a = {"role": "user", "content": {"items": [1, 2]}}
        b = {"role": "user", "content": {"items": [2, 1]}}
        self.assertFalse(self.runtime._message_equal(a, b))

    def test_content_string_json_vs_dict_equal(self):
        """Message whose content is a JSON string matches an equivalent dict content."""
        a = {
            "role": "user",
            "content": '{"step_name": "observation", "raw_text": "hello"}',
        }
        b = {
            "role": "user",
            "content": {"step_name": "observation", "raw_text": "hello"},
        }
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_none_equal(self):
        """None values are equal."""
        self.assertTrue(self.runtime._message_equal(None, None))

    def test_none_vs_string_not_equal(self):
        """None is not equal to a plain string."""
        self.assertFalse(self.runtime._message_equal(None, "hello"))

    def test_different_types_not_equal(self):
        """Different non-stringifiable types are not equal."""
        self.assertFalse(self.runtime._message_equal({"a": 1}, ["a", 1]))

    def test_content_string_json_vs_list_equal(self):
        """Message whose content is a JSON list string matches an equivalent list content."""
        a = {
            "role": "user",
            "content": '[{"step_name": "observation", "raw_text": "hello"}]',
        }
        b = {
            "role": "user",
            "content": [{"step_name": "observation", "raw_text": "hello"}],
        }
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_deeply_nested_json_string_equal(self):
        """Nested JSON strings inside dicts and lists are normalized and compared."""
        a = {
            "role": "user",
            "content": {
                "step_name": "observation",
                "raw_text": '{"items": [{"x": 1}, {"x": 2}]}',
            },
        }
        b = {
            "role": "user",
            "content": {
                "step_name": "observation",
                "raw_text": {"items": [{"x": 1}, {"x": 2}]},
            },
        }
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_mixed_list_with_json_strings_equal(self):
        """A list mixing JSON strings and dicts compares equal when normalized."""
        a = [
            {"role": "user", "content": '{"step_name": "task", "raw_text": "t1"}'},
            {"role": "assistant", "content": "ok"},
        ]
        b = [
            {"role": "user", "content": {"step_name": "task", "raw_text": "t1"}},
            {"role": "assistant", "content": "ok"},
        ]
        self.assertTrue(self.runtime._message_equal(a, b))

    def test_json_scalar_string_vs_python_scalar_equal(self):
        """JSON scalar strings normalize to Python scalars and compare equal."""
        self.assertTrue(self.runtime._message_equal("123", 123))
        self.assertTrue(self.runtime._message_equal("true", True))
        self.assertTrue(self.runtime._message_equal("null", None))
        self.assertTrue(self.runtime._message_equal('"hello"', "hello"))

    def test_plain_text_not_parsed_as_json(self):
        """Plain text strings that are not valid JSON remain as strings."""
        self.assertFalse(self.runtime._message_equal("hello", "world"))
        self.assertFalse(self.runtime._message_equal("not json", '{"key": "value"}'))

    def test_real_message_content_list_dict_format(self):
        """Real-world message content with list-dict format compares correctly."""
        a = {
            "role": "assistant",
            "content": [
                {
                    "step_name": "action",
                    "raw_text": '{"tool_call": "file_tool-read_file", "tool_args": {"file_path": "/tmp/a"}}',
                },
                {
                    "step_name": "observation",
                    "raw_text": "file content",
                },
            ],
        }
        b = {
            "role": "assistant",
            "content": [
                {
                    "step_name": "action",
                    "raw_text": {
                        "tool_call": "file_tool-read_file",
                        "tool_args": {"file_path": "/tmp/a"},
                    },
                },
                {
                    "step_name": "observation",
                    "raw_text": "file content",
                },
            ],
        }
        self.assertTrue(self.runtime._message_equal(a, b))


class TestMessageInList(unittest.TestCase):
    """Test suite for _message_in_list semantic membership helper."""

    def setUp(self):
        from topsailai.workspace.context.base import ContextRuntimeBase
        self.runtime = ContextRuntimeBase()

    def test_found_by_identity(self):
        """Message found by object identity returns True."""
        msg = {"role": "user", "content": "hello"}
        self.assertTrue(self.runtime._message_in_list(msg, [msg]))

    def test_found_by_equality(self):
        """Semantically equal message is found even as a different instance."""
        msg = {"role": "user", "content": "hello"}
        other = {"role": "user", "content": "hello"}
        self.assertTrue(self.runtime._message_in_list(msg, [other]))

    def test_found_by_json_normalization(self):
        """JSON-string message is found against dict list."""
        str_msg = '{"role": "user", "content": "hello"}'
        dict_msg = {"role": "user", "content": "hello"}
        self.assertTrue(self.runtime._message_in_list(str_msg, [dict_msg]))

    def test_not_found(self):
        """Different message is not found in list."""
        self.assertFalse(
            self.runtime._message_in_list(
                {"role": "user", "content": "hello"},
                [{"role": "assistant", "content": "hi"}],
            )
        )

    def test_empty_list(self):
        """Empty list always returns False."""
        self.assertFalse(self.runtime._message_in_list({"role": "user"}, []))


class TestMessageIndexInList(unittest.TestCase):
    """Test suite for _message_index_in_list helper."""

    def setUp(self):
        from topsailai.workspace.context.base import ContextRuntimeBase
        self.runtime = ContextRuntimeBase()

    def test_found_at_index_zero(self):
        """Message found at the first position returns 0."""
        msg = {"role": "user", "content": "first"}
        self.assertEqual(
            self.runtime._message_index_in_list(msg, [msg, {"role": "assistant"}]),
            0,
        )

    def test_found_by_content(self):
        """Semantically equal message returns its index."""
        a = {"role": "user", "content": "second"}
        b = {"role": "user", "content": "second"}
        self.assertEqual(
            self.runtime._message_index_in_list(
                a, [{"role": "system"}, b, {"role": "assistant"}]
            ),
            1,
        )

    def test_not_found_returns_minus_one(self):
        """Missing message returns -1."""
        self.assertEqual(
            self.runtime._message_index_in_list(
                {"role": "user"},
                [{"role": "assistant"}],
            ),
            -1,
        )


class TestTaskMessageHelpersWithSemanticEquality(unittest.TestCase):
    """Test task-message helpers using the new semantic equality."""

    def setUp(self):
        from topsailai.workspace.context.base import ContextRuntimeBase
        self.runtime = ContextRuntimeBase()

    def test_first_and_last_task_equal_different_instances(self):
        """Equal first/last task messages as different objects collapse to one."""
        task_a = {"role": "user", "content": {"step_name": "task", "raw_text": "t"}}
        task_b = {"role": "user", "content": {"step_name": "task", "raw_text": "t"}}
        messages = [task_a, {"role": "assistant", "content": "ok"}, task_b]
        result = self.runtime._get_first_and_last_task_messages(messages)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0], task_a)

    def test_first_and_last_task_different(self):
        """Different first/last task messages are both preserved."""
        task_a = {"role": "user", "content": {"step_name": "task", "raw_text": "a"}}
        task_b = {"role": "user", "content": {"step_name": "task", "raw_text": "b"}}
        messages = [task_a, {"role": "assistant", "content": "ok"}, task_b]
        result = self.runtime._get_first_and_last_task_messages(messages)
        self.assertEqual(len(result), 2)

    def test_merge_task_messages_avoids_duplicates_by_content(self):
        """Task message already present in new_messages by content is not re-inserted."""
        task = {"role": "user", "content": {"step_name": "task", "raw_text": "task1"}}
        original = [task, {"role": "assistant", "content": "summary"}]
        new_messages = [task]
        result = self.runtime._merge_task_messages(original, new_messages, [task])
        self.assertEqual(len(result), 1)

    def test_merge_task_messages_inserts_missing_task(self):
        """Missing task message is inserted before the summary message."""
        task = {"role": "user", "content": {"step_name": "task", "raw_text": "task1"}}
        original = [task, {"role": "assistant", "content": "old"}]
        summary = {"role": "assistant", "content": "summary"}
        new_messages = [summary]
        result = self.runtime._merge_task_messages(original, new_messages, [task])
        self.assertEqual(result, [task, summary])

    def test_merge_task_messages_predecessor_found_by_content(self):
        """Task predecessor is located by semantic equality, not object identity."""
        pred_a = {"role": "system", "content": "sys"}
        pred_b = {"role": "system", "content": "sys"}
        task = {"role": "user", "content": {"step_name": "task", "raw_text": "task1"}}
        original = [pred_a, task]
        new_messages = [pred_b]
        result = self.runtime._merge_task_messages(original, new_messages, [task])
        self.assertEqual(result, [pred_b, task])


class TestDynamicContextWatermarks(unittest.TestCase):
    """Test model-aware context limits and watermark classification."""

    def setUp(self):
        """Create an isolated runtime for each watermark test."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        self.runtime = ContextRuntimeBase()

    @patch("topsailai.workspace.context.base.env_tool")
    def test_resolve_model_max_context_exact_map_hit(self, mock_env_tool):
        """An exact model-name map entry takes precedence over the fallback."""
        def _get(key, **kwargs):
            values = {
                "TOPSAILAI_MODEL_MAX_CONTEXT_MAP": '{"model-a": 131072}',
                "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": 65536,
            }
            return values.get(key, kwargs.get("default"))

        mock_env_tool.EnvReaderInstance.get.side_effect = _get

        self.assertEqual(
            self.runtime._resolve_model_max_context("model-a"),
            131072,
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_resolve_model_max_context_uses_default_for_unknown_model(
        self, mock_env_tool
    ):
        """An unknown model uses the configured positive fallback context."""
        def _get(key, **kwargs):
            values = {
                "TOPSAILAI_MODEL_MAX_CONTEXT_MAP": '{"model-a": 131072}',
                "TOPSAILAI_MODEL_MAX_CONTEXT_DEFAULT": 65536,
            }
            return values.get(key, kwargs.get("default"))

        mock_env_tool.EnvReaderInstance.get.side_effect = _get

        self.assertEqual(
            self.runtime._resolve_model_max_context("model-b"),
            65536,
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_resolve_model_max_context_invalid_map_disables_guard(
        self, mock_env_tool
    ):
        """Invalid non-empty map JSON disables dynamic model resolution."""
        mock_env_tool.EnvReaderInstance.get.return_value = "not-json"

        self.assertIsNone(
            self.runtime._resolve_model_max_context("model-a")
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_resolve_model_max_context_is_not_cached(self, mock_env_tool):
        """Every resolution observes the current active configuration."""
        maps = iter([
            '{"model-a": 131072}',
            '{"model-a": 65536}',
        ])

        def _get(key, **kwargs):
            if key == "TOPSAILAI_MODEL_MAX_CONTEXT_MAP":
                return next(maps)
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _get

        self.assertEqual(
            self.runtime._resolve_model_max_context("model-a"),
            131072,
        )
        self.assertEqual(
            self.runtime._resolve_model_max_context("model-a"),
            65536,
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_watermark_ratios_defaults_are_exact(self, mock_env_tool):
        """The documented LOW and HIGH defaults are exactly 0.73 and 0.93."""
        mock_env_tool.EnvReaderInstance.get.side_effect = (
            lambda key, **kwargs: kwargs.get("default")
        )

        self.assertEqual(
            self.runtime._get_watermark_ratios(),
            (0.73, 0.93),
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_get_watermark_ratios_invalid_order_uses_defaults(
        self, mock_env_tool
    ):
        """Ratios not satisfying zero-low-high-one use safe defaults."""
        def _get(key, **kwargs):
            values = {
                "TOPSAILAI_CONTEXT_LOW_WATERMARK_RATIO": 0.95,
                "TOPSAILAI_CONTEXT_HIGH_WATERMARK_RATIO": 0.90,
            }
            return values.get(key, kwargs.get("default"))

        mock_env_tool.EnvReaderInstance.get.side_effect = _get

        self.assertEqual(
            self.runtime._get_watermark_ratios(),
            (0.73, 0.93),
        )

    def test_get_watermark_ratios_partially_invalid_uses_paired_defaults(self):
        """Either malformed ratio resets the LOW/HIGH pair to safe defaults."""
        invalid_pairs = (("invalid", "0.90"), ("0.50", "invalid"))
        for low_ratio, high_ratio in invalid_pairs:
            with self.subTest(low_ratio=low_ratio, high_ratio=high_ratio), patch.dict(
                os.environ,
                {
                    "TOPSAILAI_CONTEXT_LOW_WATERMARK_RATIO": low_ratio,
                    "TOPSAILAI_CONTEXT_HIGH_WATERMARK_RATIO": high_ratio,
                },
                clear=False,
            ):
                self.assertEqual(
                    self.runtime._get_watermark_ratios(),
                    (0.73, 0.93),
                )

    @patch.object(
        __import__(
            "topsailai.workspace.context.base",
            fromlist=["ContextRuntimeBase"],
        ).ContextRuntimeBase,
        "_resolve_model_max_context",
        return_value=131072,
    )
    @patch("topsailai.workspace.context.base.env_tool")
    def test_compute_context_limits_reserves_output_and_summary_margin(
        self, mock_env_tool, mock_resolve
    ):
        """Limits reserve MAX_TOKENS first and summary overhead second."""
        mock_env_tool.EnvReaderInstance.get.return_value = 8192

        self.assertEqual(
            self.runtime._compute_context_limits("model-a", 30000),
            (131072, 92880, 101072),
        )

    @patch("topsailai.workspace.context.base.env_tool")
    def test_estimate_safe_tokens_rounds_up(self, mock_env_tool):
        """The conservative token estimate applies its coefficient and rounds up."""
        mock_env_tool.EnvReaderInstance.get.return_value = 1.05

        self.assertEqual(self.runtime._estimate_safe_tokens(101), 107)

    def test_classification_priority_and_all_levels(self):
        """Classification returns one level with HARD-to-NORMAL priority."""
        from topsailai.workspace.context.base import (
            CONTEXT_WATERMARK_HARD,
            CONTEXT_WATERMARK_HIGH,
            CONTEXT_WATERMARK_LOW,
            CONTEXT_WATERMARK_NORMAL,
        )

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            return_value=(1000, 800, 900),
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ), patch.object(
            self.runtime,
            "_get_watermark_ratios",
            return_value=(0.73, 0.93),
        ):
            normal = self.runtime._classify_context_watermark(
                current_tokens=583,
                model_name="model-a",
                max_tokens=100,
            )
            low = self.runtime._classify_context_watermark(
                current_tokens=584,
                model_name="model-a",
                max_tokens=100,
            )
            high = self.runtime._classify_context_watermark(
                current_tokens=744,
                model_name="model-a",
                max_tokens=100,
            )
            hard = self.runtime._classify_context_watermark(
                current_tokens=900,
                model_name="model-a",
                max_tokens=100,
            )

        self.assertEqual(normal.level, CONTEXT_WATERMARK_NORMAL)
        self.assertEqual(low.level, CONTEXT_WATERMARK_LOW)
        self.assertEqual(high.level, CONTEXT_WATERMARK_HIGH)
        self.assertEqual(hard.level, CONTEXT_WATERMARK_HARD)

    def test_classification_reads_active_model_each_time(self):
        """Model switches and output-budget changes are used without stale limits."""
        from topsailai.workspace.context.base import (
            CONTEXT_WATERMARK_HARD,
            CONTEXT_WATERMARK_NORMAL,
        )

        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "large-model"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        def _limits(model_name, max_tokens):
            if model_name == "large-model" and max_tokens == 100:
                return (2000, 1700, 1900)
            return (1000, 700, 800)

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            side_effect=_limits,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ), patch.object(
            self.runtime,
            "_get_watermark_ratios",
            return_value=(0.73, 0.93),
        ):
            first = self.runtime._classify_context_watermark(current_tokens=850)
            self.runtime.ai_agent.llm_model.model_name = "small-model"
            self.runtime.ai_agent.llm_model.max_tokens = 200
            second = self.runtime._classify_context_watermark(current_tokens=850)

        self.assertEqual(first.level, CONTEXT_WATERMARK_NORMAL)
        self.assertEqual(second.level, CONTEXT_WATERMARK_HARD)

    def test_classification_non_positive_safe_budget_is_hard(self):
        """Invalid configuration with no safe input budget is always HARD."""
        from topsailai.workspace.context.base import CONTEXT_WATERMARK_HARD

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            return_value=(1000, -100, 0),
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            return_value=0,
        ), patch.object(
            self.runtime,
            "_get_watermark_ratios",
            return_value=(0.73, 0.93),
        ):
            result = self.runtime._classify_context_watermark(
                current_tokens=0,
                model_name="model-a",
                max_tokens=1000,
            )

        self.assertEqual(result.level, CONTEXT_WATERMARK_HARD)

    def test_summary_feasibility_rejects_input_above_model_context(self):
        """Summary input above the model context is a hard rejection."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "model-a"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            return_value=(1000, 800, 900),
        ), patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=1001,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ):
            allowed, reason, input_tokens, safe_limit = (
                self.runtime._check_dynamic_summary_feasibility([], 100, 50)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "summary_input_exceeds_model_context")
        self.assertEqual(input_tokens, 1001)
        self.assertEqual(safe_limit, 800)

    def test_summary_feasibility_rejects_input_above_safe_limit(self):
        """Summary input above the summary-safe limit is rejected preflight."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "model-a"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            return_value=(1000, 800, 900),
        ), patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=801,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ):
            allowed, reason, input_tokens, safe_limit = (
                self.runtime._check_dynamic_summary_feasibility([], 100, 50)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "summary_input_exceeds_safe_limit")
        self.assertEqual(input_tokens, 801)
        self.assertEqual(safe_limit, 800)

    def test_summary_feasibility_rejects_preserved_budget_above_safe_limit(self):
        """Preserved input plus summary reserve must fit the safe limit."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "model-a"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            return_value=(1000, 800, 900),
        ), patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=700,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ):
            allowed, reason, input_tokens, safe_limit = (
                self.runtime._check_dynamic_summary_feasibility([], 751, 50)
            )

        self.assertFalse(allowed)
        self.assertEqual(reason, "preserved_budget_exceeds_safe_limit")
        self.assertEqual(input_tokens, 700)
        self.assertEqual(safe_limit, 800)


class TestDynamicContextWatermarkExpansion(unittest.TestCase):
    """Exhaustive boundary tests for the dynamic context guard."""

    def setUp(self):
        """Create an isolated runtime."""
        from topsailai.workspace.context.base import ContextRuntimeBase
        self.runtime = ContextRuntimeBase()

    def _classify(self, safe_tokens, limits=(1000, 800, 900)):
        """Classify a deterministic safe-token value."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=limits), \
                patch.object(self.runtime, "_estimate_safe_tokens", return_value=safe_tokens), \
                patch.object(self.runtime, "_get_watermark_ratios", return_value=(0.73, 0.93)):
            return self.runtime._classify_context_watermark(
                current_tokens=safe_tokens, model_name="model-a", max_tokens=100
            )

    def test_compute_limits_coerces_invalid_output_budgets_to_zero(self):
        """None, non-numeric, and negative output budgets reserve no output tokens."""
        with patch.object(self.runtime, "_resolve_model_max_context", return_value=10000), \
                patch("topsailai.workspace.context.base.env_tool") as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 0
            for value in (None, "invalid", -100):
                with self.subTest(value=value):
                    self.assertEqual(
                        self.runtime._compute_context_limits("model-a", value),
                        (10000, 10000, 10000),
                    )

    def test_compute_limits_margin_variants(self):
        """Invalid, zero, and oversized margins use their exact documented semantics."""
        with patch.object(self.runtime, "_resolve_model_max_context", return_value=10000), \
                patch("topsailai.workspace.context.base.env_tool") as mock_env:
            for margin, expected in ((-1, (10000, 808, 9000)), (0, (10000, 9000, 9000)),
                                     (9500, (10000, -500, 9000))):
                with self.subTest(margin=margin):
                    mock_env.EnvReaderInstance.get.return_value = margin
                    self.assertEqual(
                        self.runtime._compute_context_limits("model-a", 1000), expected
                    )

    def test_estimate_safe_tokens_invalid_coefficients_fall_back(self):
        """Invalid coefficients fall back to 1.05 and log a warning."""
        invalid_coefficients = (
            None,
            0.99,
            float("nan"),
            float("inf"),
            float("-inf"),
            "invalid",
        )
        with patch("topsailai.workspace.context.base.env_tool") as mock_env, \
                patch("topsailai.workspace.context.base.logger") as mock_logger:
            for coefficient in invalid_coefficients:
                with self.subTest(coefficient=coefficient):
                    mock_env.EnvReaderInstance.get.return_value = coefficient
                    self.assertEqual(self.runtime._estimate_safe_tokens(100), 105)
            self.assertEqual(
                mock_logger.warning.call_count,
                len(invalid_coefficients),
            )

    def test_estimate_safe_tokens_extreme_and_non_positive_raw_values(self):
        """Extreme coefficients scale upward while non-positive input is clamped to zero."""
        with patch("topsailai.workspace.context.base.env_tool") as mock_env:
            mock_env.EnvReaderInstance.get.return_value = 100.0
            self.assertEqual(self.runtime._estimate_safe_tokens(3), 300)
            self.assertEqual(self.runtime._estimate_safe_tokens(0), 0)
            self.assertEqual(self.runtime._estimate_safe_tokens(-3), 0)

    def test_resolve_model_context_rejects_invalid_mapped_values(self):
        """Non-integer, zero, and negative mapped limits disable the guard."""
        with patch("topsailai.workspace.context.base.env_tool") as mock_env:
            for value in ("bad", 0, -1):
                with self.subTest(value=value):
                    mock_env.EnvReaderInstance.get.side_effect = lambda key, **kwargs: (
                        '{"model-a": %s}' % ('"bad"' if value == "bad" else value)
                        if key == "TOPSAILAI_MODEL_MAX_CONTEXT_MAP"
                        else kwargs.get("default")
                    )
                    self.assertIsNone(self.runtime._resolve_model_max_context("model-a"))

    def test_compute_limits_propagates_missing_model_limit(self):
        """Missing model capacity disables dynamic limit computation."""
        with patch.object(self.runtime, "_resolve_model_max_context", return_value=None):
            self.assertIsNone(self.runtime._compute_context_limits("model-a", 100))

    def test_non_positive_send_limit_is_hard(self):
        """Both zero and negative send limits classify as HARD."""
        from topsailai.workspace.context.base import CONTEXT_WATERMARK_HARD
        for limits in ((1000, 0, 0), (1000, -1, -100)):
            with self.subTest(limits=limits):
                self.assertEqual(self._classify(0, limits).level, CONTEXT_WATERMARK_HARD)

    def test_classification_equality_boundaries_are_inclusive(self):
        """Exact LOW, HIGH, and HARD boundaries enter their higher watermark."""
        from topsailai.workspace.context.base import (
            CONTEXT_WATERMARK_HARD, CONTEXT_WATERMARK_HIGH, CONTEXT_WATERMARK_LOW
        )
        self.assertEqual(self._classify(584).level, CONTEXT_WATERMARK_LOW)
        self.assertEqual(self._classify(744).level, CONTEXT_WATERMARK_HIGH)
        self.assertEqual(self._classify(900).level, CONTEXT_WATERMARK_HARD)

    def test_classification_just_below_boundaries_uses_lower_level(self):
        """A token below each boundary remains in the immediately lower level."""
        from topsailai.workspace.context.base import (
            CONTEXT_WATERMARK_HIGH, CONTEXT_WATERMARK_LOW, CONTEXT_WATERMARK_NORMAL
        )
        self.assertEqual(self._classify(583).level, CONTEXT_WATERMARK_NORMAL)
        self.assertEqual(self._classify(743).level, CONTEXT_WATERMARK_LOW)
        self.assertEqual(self._classify(899).level, CONTEXT_WATERMARK_HIGH)

    def test_invalid_watermark_ratio_variants_use_defaults(self):
        """Every invalid ratio shape falls back to 0.73 and 0.93."""
        variants = (
            (0, 0.9),
            (0.5, 1),
            (0.5, 0.5),
            (0.8, 0.7),
            (None, 0.9),
            (0.5, None),
        )
        with patch("topsailai.workspace.context.base.env_tool") as mock_env:
            for low, high in variants:
                with self.subTest(low=low, high=high):
                    mock_env.EnvReaderInstance.get.side_effect = [low, high]
                    self.assertEqual(
                        self.runtime._get_watermark_ratios(),
                        (0.73, 0.93),
                    )

    def test_classification_returns_none_when_realtime_tokens_unavailable(self):
        """Unavailable realtime token counts cannot be classified."""
        with patch.object(self.runtime, "_get_current_tokens", return_value=None):
            self.assertIsNone(self.runtime._classify_context_watermark())

    def test_explicit_model_arguments_override_active_model(self):
        """Explicit model and output budget arguments override active model attributes."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "active"
        self.runtime.ai_agent.llm_model.max_tokens = 999
        with patch.object(self.runtime, "_compute_context_limits", return_value=(1000, 800, 900)) as limits, \
                patch.object(self.runtime, "_estimate_safe_tokens", return_value=1), \
                patch.object(self.runtime, "_get_watermark_ratios", return_value=(.73, .93)):
            self.runtime._classify_context_watermark(1, "explicit", 123)
        limits.assert_called_once_with("explicit", 123)

    def test_classification_returns_none_when_dynamic_limits_disabled(self):
        """A disabled dynamic guard produces no watermark result."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=None):
            self.assertIsNone(self.runtime._classify_context_watermark(10, "model-a", 1))

    def test_watermark_result_fields_are_derived_exactly(self):
        """Classification exposes all derived limits and clamps negative output budget."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=(1000, 800, 1000)), \
                patch.object(self.runtime, "_estimate_safe_tokens", return_value=100), \
                patch.object(self.runtime, "_get_watermark_ratios", return_value=(.25, .75)):
            result = self.runtime._classify_context_watermark(90, "model-a", -1)
        self.assertEqual(result.current_tokens, 90)
        self.assertEqual(result.safe_tokens, 100)
        self.assertEqual(result.max_tokens, 0)
        self.assertEqual((result.low_limit, result.high_limit), (200.0, 600.0))

    def test_summary_feasibility_rejects_unavailable_input_tokens(self):
        """Unavailable summary token accounting is a hard rejection."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=(1000, 800, 900)), \
                patch.object(self.runtime, "_get_current_tokens", return_value=None):
            result = self.runtime._check_dynamic_summary_feasibility([], 1, 1)
        self.assertEqual(result, (False, "summary_input_tokens_unavailable", None, 800))

    def test_summary_feasibility_allows_when_dynamic_limits_disabled(self):
        """Disabled dynamic limits leave legacy summarization feasible."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=None):
            self.assertEqual(
                self.runtime._check_dynamic_summary_feasibility([], 1, 1),
                (True, "", None, None),
            )

    def test_summary_feasibility_handles_missing_agent_or_model(self):
        """Missing agent/model metadata does not crash model-limit resolution."""
        for agent in (None, MagicMock(llm_model=None)):
            with self.subTest(agent=agent):
                self.runtime.ai_agent = agent
                with patch.object(self.runtime, "_compute_context_limits", return_value=None) as limits:
                    self.runtime._check_dynamic_summary_feasibility([], 1, 1)
                limits.assert_called_once_with("", 0)

    def test_summary_feasibility_allowed_result_contains_budget_values(self):
        """A feasible summary returns exact input and safe-limit values."""
        with patch.object(self.runtime, "_compute_context_limits", return_value=(1000, 800, 900)), \
                patch.object(self.runtime, "_get_current_tokens", return_value=500), \
                patch.object(self.runtime, "_estimate_safe_tokens", side_effect=lambda value: value):
            self.assertEqual(
                self.runtime._check_dynamic_summary_feasibility([], 100, 50),
                (True, "", 500, 800),
            )

    def test_summary_feasibility_recomputes_limits_after_model_switch(self):
        """Feasibility uses the active model name on every preflight check."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "large-model"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        def _limits(model_name, max_tokens):
            self.assertEqual(max_tokens, 100)
            if model_name == "large-model":
                return 2000, 1700, 1900
            return 1000, 700, 900

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            side_effect=_limits,
        ) as compute_limits, patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=800,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ):
            first = self.runtime._check_dynamic_summary_feasibility([], 100, 50)
            self.runtime.ai_agent.llm_model.model_name = "small-model"
            second = self.runtime._check_dynamic_summary_feasibility([], 100, 50)

        self.assertEqual(first, (True, "", 800, 1700))
        self.assertEqual(
            second,
            (False, "summary_input_exceeds_safe_limit", 800, 700),
        )
        self.assertEqual(
            compute_limits.call_args_list,
            [
                unittest.mock.call("large-model", 100),
                unittest.mock.call("small-model", 100),
            ],
        )

    def test_summary_feasibility_recomputes_limits_after_max_tokens_change(self):
        """Feasibility uses the active output budget on every preflight check."""
        self.runtime.ai_agent = MagicMock()
        self.runtime.ai_agent.llm_model.model_name = "model-a"
        self.runtime.ai_agent.llm_model.max_tokens = 100

        def _limits(model_name, max_tokens):
            self.assertEqual(model_name, "model-a")
            return 1000, 800 - max_tokens, 900 - max_tokens

        with patch.object(
            self.runtime,
            "_compute_context_limits",
            side_effect=_limits,
        ) as compute_limits, patch.object(
            self.runtime,
            "_get_current_tokens",
            return_value=650,
        ), patch.object(
            self.runtime,
            "_estimate_safe_tokens",
            side_effect=lambda value: value,
        ):
            first = self.runtime._check_dynamic_summary_feasibility([], 100, 50)
            self.runtime.ai_agent.llm_model.max_tokens = 200
            second = self.runtime._check_dynamic_summary_feasibility([], 100, 50)

        self.assertEqual(first, (True, "", 650, 700))
        self.assertEqual(
            second,
            (False, "summary_input_exceeds_safe_limit", 650, 600),
        )
        self.assertEqual(
            compute_limits.call_args_list,
            [
                unittest.mock.call("model-a", 100),
                unittest.mock.call("model-a", 200),
            ],
        )

    def test_resolve_summary_input_message_variants(self):
        """Summary input selection honors mode and chooses the complete runtime list."""
        caller = [{"content": "caller-1"}, {"content": "caller-2"}]
        longer = caller + [{"content": "runtime"}]
        with patch("topsailai.workspace.context.base.env_tool") as mock_env:
            mock_env.EnvReaderInstance.get.return_value = "message"
            self.assertIs(self.runtime._resolve_summary_input_messages(caller), caller)
            mock_env.EnvReaderInstance.get.return_value = "runtime"
            for runtime_messages, expected in (([], caller), (caller[:1], caller), (longer, longer)):
                with self.subTest(runtime_messages=runtime_messages):
                    with patch.object(self.runtime, "_get_token_calculation_messages", return_value=runtime_messages):
                        self.assertEqual(self.runtime._resolve_summary_input_messages(caller), expected)

    def test_empty_and_whitespace_context_maps_disable_guard(self):
        """Empty map values with no default leave dynamic limits unconfigured."""
        with patch("topsailai.workspace.context.base.env_tool") as mock_env:
            for raw_map in ("", "   "):
                with self.subTest(raw_map=raw_map):
                    mock_env.EnvReaderInstance.get.side_effect = lambda key, **kwargs: (
                        raw_map if key == "TOPSAILAI_MODEL_MAX_CONTEXT_MAP" else 0
                    )
                    self.assertIsNone(self.runtime._resolve_model_max_context("model-a"))



class TestCachedTokensRuntimeSummarySource(unittest.TestCase):
    """Lock in cached-token utilization via the runtime (Agent2LLM) summary source.

    The summarizer intentionally consumes the runtime message store so the
    summary request reuses the prompt prefix from the immediately preceding
    Agent2LLM inference, enabling provider KV-cache reuse. After rebuilding,
    only the configured head/session/tail prefix remains stable for next inference.
    These tests pin source selection, prefix stability, mode switching,
    forwarded-length equivalence, defensive fallback, and extreme-length differential.
    """

    def _make_messages(self, count, prefix="msg"):
        """Create a list of distinct message dictionaries."""
        return [
            {"role": "user", "content": f"{prefix}-{i}"}
            for i in range(count)
        ]

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct1_runtime_summary_consumes_agent_messages_when_agent_present(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-1a: agent present -> forward ai_agent.messages (complete runtime)."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        agent_messages = self._make_messages(25, "agent")
        runtime.ai_agent.messages = agent_messages
        runtime.messages = self._make_messages(20, "session")

        runtime._summarize_runtime_messages([])

        # The forwarded prompt must be the exact agent runtime list.
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 25)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-0")
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[-1]["content"], "agent-24")

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct1_runtime_summary_consumes_session_messages_when_agent_absent(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-1b: absent agent -> summary LLM receives session fallback."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = None
        expected_session_messages = self._make_messages(15, "session")
        runtime.messages = expected_session_messages
        runtime._get_summary_prompt = MagicMock(return_value="summary prompt")

        runtime._summarize_runtime_messages([])

        self.assertEqual(mock_llm_chat.prompt_ctl.messages, expected_session_messages)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct2_summary_request_reuses_previous_agent2llm_prompt_prefix(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-2: summary request reuses the preceding inference prefix."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.agent_type = "test_agent"
        previous_inference_messages = [
            {"role": "system", "content": "stable system"},
            {"role": "user", "content": {"step_name": "task", "raw_text": "stable task"}},
            {"role": "assistant", "content": {"tool_calls": [{"id": "call-1"}]}},
            {"role": "tool", "content": "stable result", "tool_call_id": "call-1"},
        ]
        runtime.ai_agent.messages = previous_inference_messages
        runtime._get_summary_prompt = MagicMock(return_value="summary prompt")
        summary_chat = MagicMock()
        summary_chat.chat.return_value = "Summary"
        mock_get_llm_chat.return_value = summary_chat

        runtime._summarize_runtime_messages(list(previous_inference_messages))

        expected_prefix = json.dumps(previous_inference_messages, sort_keys=True, separators=(",", ":"))
        actual_prefix = json.dumps(
            summary_chat.prompt_ctl.messages,
            sort_keys=True,
            separators=(",", ":"),
        )
        self.assertEqual(actual_prefix, expected_prefix)
        self.assertEqual(summary_chat.prompt_ctl.messages, previous_inference_messages)
        summary_chat.chat.assert_called_once()
        self.assertIn("DONOT INVOKE ANY TOOLS", summary_chat.chat.call_args.args[0])

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct3_summary_mode_toggle_runtime_vs_message(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-3: SUMMARY_MODE toggle re-selects runtime vs message feed."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.messages = self._make_messages(8, "agent")

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        runtime_chat = MagicMock()
        runtime_chat.chat.return_value = "Runtime summary"
        mock_get_llm_chat.return_value = runtime_chat
        _, answer = runtime._summarize_messages(self._make_messages(3, "caller"))
        self.assertEqual(answer, "Runtime summary")
        self.assertEqual(len(runtime_chat.prompt_ctl.messages), 8)
        self.assertEqual(runtime_chat.prompt_ctl.messages[0]["content"], "agent-0")

        mock_env_tool.EnvReaderInstance.get.return_value = "message"
        message_chat = MagicMock()
        message_chat.chat.return_value = "Message summary"
        mock_get_llm_chat.return_value = message_chat
        _, answer = runtime._summarize_messages(self._make_messages(3, "caller"))
        self.assertEqual(answer, "Message summary")
        last_call_kwargs = mock_get_llm_chat.call_args.kwargs
        self.assertIn("message", last_call_kwargs)
        self.assertIn("caller-0", last_call_kwargs["message"])

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct6_forwards_full_runtime_length_equals_pre_summary_inference(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-6: summary feed equals the pre-summary runtime inference prompt."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        pre_summary_inference_prompt = self._make_messages(30, "agent")
        runtime.ai_agent.messages = pre_summary_inference_prompt
        runtime._summarize_runtime_messages(list(pre_summary_inference_prompt))

        self.assertEqual(mock_llm_chat.prompt_ctl.messages, pre_summary_inference_prompt)
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), len(pre_summary_inference_prompt))

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct7_force_does_not_disarm_defensive_fallback(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-7: public forced summarization still uses the longer caller list."""
        from topsailai.workspace.context.agent2llm import ContextRuntimeAgent2LLM

        def _env_get(key, **kwargs):
            if key == "TOPSAILAI_CONTEXT_SUMMARY_MODE":
                return "runtime"
            return kwargs.get("default")

        mock_env_tool.EnvReaderInstance.get.side_effect = _env_get
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeAgent2LLM()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.agent_type = "test_agent"
        runtime.ai_agent.get_work_memory_first_position.return_value = 0
        runtime.ai_agent.llm_model.tokenStat.current_tokens = 0
        runtime.ai_agent.messages = self._make_messages(2, "agent")
        caller = self._make_messages(40, "caller")
        runtime._can_summarize_agent2llm_messages = MagicMock(return_value=(True, 0))

        with patch.dict(os.environ, {
            "TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES": "0",
        }), patch.object(runtime, "_get_head_offset_to_keep_in_summary", return_value=0), \
                patch.object(runtime, "_get_tail_offset_to_keep_in_summary", return_value=0):
            answer = runtime.summarize_messages_for_processing(caller, force=True)

        self.assertEqual(answer, "Summarized content")
        mock_llm_chat.chat.assert_called_once()
        self.assertEqual(mock_llm_chat.prompt_ctl.messages, caller)
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), len(caller))

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    def test_p1b_preflight_input_matches_actual_summary_input(
        self, mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """Preflight resolves the same messages that the summary LLM receives."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.is_interactive_mode.return_value = False
        cases = (
            ("runtime-longer", "runtime", True, 4, 2),
            ("caller-longer", "runtime", True, 2, 4),
            ("runtime-empty", "runtime", True, 0, 3),
            ("agent-absent", "runtime", False, 0, 3),
            ("message-mode", "message", True, 4, 2),
        )
        for name, mode, has_agent, runtime_len, caller_len in cases:
            with self.subTest(name=name):
                def env_get(key, **kwargs):
                    if key == "TOPSAILAI_CONTEXT_SUMMARY_MODE":
                        return mode
                    return kwargs.get("default")

                mock_env_tool.EnvReaderInstance.get.side_effect = env_get
                runtime = ContextRuntimeBase()
                runtime._get_summary_prompt = MagicMock(return_value="summary prompt")
                caller = self._make_messages(caller_len, "caller")
                runtime.messages = self._make_messages(3, "session")
                if has_agent:
                    runtime.ai_agent = MagicMock()
                    runtime.ai_agent.messages = self._make_messages(runtime_len, "runtime")
                else:
                    runtime.ai_agent = None
                    runtime.messages = self._make_messages(runtime_len, "session")

                expected = runtime._resolve_summary_input_messages(caller)
                mock_llm_chat = MagicMock()
                mock_llm_chat.chat.return_value = "Summary"
                mock_get_llm_chat.return_value = mock_llm_chat
                runtime._summarize_messages(caller)

                if mode == "runtime":
                    actual = mock_llm_chat.prompt_ctl.messages
                else:
                    serialized = mock_get_llm_chat.call_args.kwargs["message"]
                    actual = json.loads(serialized[serialized.index("["):])
                self.assertEqual(actual, expected)

    @patch('topsailai.workspace.context.base.AgentBase')
    @patch('topsailai.workspace.context.base.get_llm_chat')
    @patch('topsailai.workspace.context.base.env_tool')
    @patch('topsailai.workspace.context.base.file_tool')
    @patch('topsailai.workspace.context.base.summary_tool')
    @patch('topsailai.workspace.context.base.story_tool')
    def test_ct8_extreme_length_differential_uses_longer_caller(
        self, mock_story_tool, mock_summary_tool, mock_file_tool,
        mock_env_tool, mock_get_llm_chat, mock_agent_base
    ):
        """CT-8: huge caller >> tiny runtime picks the longer caller list."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        mock_env_tool.EnvReaderInstance.get.return_value = "runtime"
        mock_env_tool.is_interactive_mode.return_value = False
        mock_file_tool.get_file_content_fuzzy.return_value = (None, "")
        mock_summary_tool.get_summary_prompt.return_value = None
        mock_story_tool.PROMPT_SUMMARY_TASK = "default prompt"
        mock_llm_chat = MagicMock()
        mock_llm_chat.chat.return_value = "Summarized content"
        mock_get_llm_chat.return_value = mock_llm_chat

        runtime = ContextRuntimeBase()
        runtime.ai_agent = MagicMock()
        runtime.ai_agent.messages = self._make_messages(1, "tiny")
        caller = self._make_messages(200, "huge")

        runtime._summarize_runtime_messages(caller)

        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 200)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "huge-0")
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[-1]["content"], "huge-199")


class TestSummaryHeadMessages(unittest.TestCase):
    """Test intrinsic summary-head selection modes."""

    def setUp(self):
        """Create an isolated runtime and representative messages."""
        from topsailai.workspace.context.base import ContextRuntimeBase

        self.runtime = ContextRuntimeBase()
        self.system = {"role": "system", "content": "system"}
        self.obs1 = {
            "role": "user",
            "content": {"step_name": "observation", "raw_text": "one"},
        }
        self.obs2 = {
            "role": "user",
            "content": json.dumps(
                {"step_name": "observation", "raw_text": "two"}
            ),
        }
        self.task = {
            "role": "user",
            "content": {"step_name": "task", "raw_text": "task"},
        }
        self.assistant = {"role": "assistant", "content": "answer"}

    def test_disabled_keeps_system_and_contiguous_opening_observations(self):
        """All contiguous opening observations survive after a system prefix."""
        messages = [self.system, self.obs1, self.obs2, self.task, self.assistant]

        result = self.runtime._get_summary_head_messages(
            messages, keep_first_task=False
        )

        self.assertEqual(result, [self.system, self.obs1, self.obs2])

    def test_disabled_stops_at_first_non_observation(self):
        """A later observation is not absorbed after the opening block ends."""
        messages = [self.obs1, self.assistant, self.obs2, self.task]

        result = self.runtime._get_summary_head_messages(
            messages, keep_first_task=False
        )

        self.assertEqual(result, [self.obs1])

    def test_disabled_without_task_never_uses_max_count_fallback(self):
        """No-task input keeps only the opening observations."""
        messages = [self.obs1, self.obs2] + [
            {"role": "assistant", "content": str(index)} for index in range(12)
        ]

        result = self.runtime._get_summary_head_messages(
            messages, max_count=1, keep_first_task=False
        )

        self.assertEqual(result, [self.obs1, self.obs2])

    def test_disabled_head_is_stable_across_summary_rounds(self):
        """A previous summary terminates the next round's opening block."""
        first_round = [self.obs1, self.obs2, self.task, self.assistant]
        first_head = self.runtime._get_summary_head_messages(
            first_round, keep_first_task=False
        )
        previous_summary = {"role": "assistant", "content": "summary one"}
        second_round = first_head + [previous_summary, self.task, self.assistant]

        second_head = self.runtime._get_summary_head_messages(
            second_round, keep_first_task=False
        )

        self.assertEqual(second_head, [self.obs1, self.obs2])
        self.assertNotIn(previous_summary, second_head)

    def test_default_environment_keeps_legacy_task_inclusive_head(self):
        """Unset configuration remains backward compatible."""
        messages = [self.obs1, self.task, self.assistant]

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE", None)
            result = self.runtime._get_summary_head_messages(messages)

        self.assertEqual(result, [self.obs1, self.task])

    def test_explicit_parameter_overrides_disabled_environment(self):
        """The explicit option takes precedence over process configuration."""
        messages = [self.obs1, self.task, self.assistant]

        with patch.dict(
            os.environ,
            {"TOPSAILAI_CTX_SUMMARY_KEEP_FIRST_TASK_MESSAGE": "0"},
        ):
            result = self.runtime._get_summary_head_messages(
                messages, keep_first_task=True
            )

        self.assertEqual(result, [self.obs1, self.task])

if __name__ == '__main__':
    unittest.main()
