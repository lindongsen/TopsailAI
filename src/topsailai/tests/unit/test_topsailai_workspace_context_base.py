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
        runtime.ai_agent.messages = [{"role": "assistant", "content": "short"}]
        runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]

        # Simulate User2Agent override: _get_token_calculation_messages returns self.messages
        runtime._get_token_calculation_messages = lambda: runtime.messages

        runtime._summarize_runtime_messages([])

        # The LLM should receive self.messages, not the short ai_agent.messages
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 20)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "msg0")

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
        runtime.ai_agent.messages = [{"role": "user", "content": "agent-msg"}]
        runtime.messages = [{"role": "user", "content": f"session-msg-{i}"} for i in range(20)]

        fallback = [{"role": "user", "content": f"fallback-{i}"} for i in range(20)]
        runtime._summarize_runtime_messages(fallback)

        # Defensive fallback chooses the longer caller-supplied messages.
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 20)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-0")

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
        runtime.ai_agent.messages = []
        runtime.messages = []

        fallback = [{"role": "user", "content": f"fallback-{i}"} for i in range(10)]
        runtime._summarize_runtime_messages(fallback)

        # Should fall back to caller-provided messages
        self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 10)
        self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-0")


if __name__ == '__main__':
    unittest.main()
