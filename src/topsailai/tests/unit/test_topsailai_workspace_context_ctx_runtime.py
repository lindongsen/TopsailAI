"""
Unit tests for workspace/context/ctx_runtime.py module.

This module tests the ContextRuntimeData class which manages runtime context
for user sessions and AI agent interactions.

Author: mm-m25
Created: 2026-04-19
"""

import unittest
from unittest.mock import (
    MagicMock,
    patch,
    PropertyMock,
    call,
)
import os


class TestContextRuntimeData(unittest.TestCase):
    """Test suite for ContextRuntimeData class."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock environment variables
        self.env_patcher = patch.dict(os.environ, {
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "50",
            "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP": "5",
        })
        self.env_patcher.start()

        # Mock ctx_manager
        self.ctx_manager_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.ctx_manager'
        )
        self.mock_ctx_manager = self.ctx_manager_patcher.start()

        # Mock json_tool
        self.json_tool_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.json_tool'
        )
        self.mock_json_tool = self.json_tool_patcher.start()

        # Mock story_tool
        self.story_tool_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.story_tool'
        )
        self.mock_story_tool = self.story_tool_patcher.start()

        # Mock story_memory_tool
        self.story_memory_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.story_memory_tool'
        )
        self.mock_story_memory = self.story_memory_patcher.start()

        # Mock print_step
        self.print_step_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.print_step'
        )
        self.mock_print_step = self.print_step_patcher.start()

        # Import after mocking
        from topsailai.workspace.context.ctx_runtime import ContextRuntimeData
        self.runtime = ContextRuntimeData()

    def tearDown(self):
        """Clean up test fixtures."""
        self.env_patcher.stop()
        self.ctx_manager_patcher.stop()
        self.json_tool_patcher.stop()
        self.story_tool_patcher.stop()
        self.story_memory_patcher.stop()
        self.print_step_patcher.stop()


class TestAddSessionMessage(TestContextRuntimeData):
    """Test cases for add_session_message() method."""

    def test_add_session_message_basic(self):
        """Test adding a message with role and content."""
        with patch.object(self.runtime, 'append_message') as mock_append:
            self.runtime.add_session_message("user", "Hello, how are you?")
            mock_append.assert_called_once_with(
                {"role": "user", "content": "Hello, how are you?"}
            )

    def test_add_session_message_default_role(self):
        """Test that None role defaults to ASSISTANT."""
        with patch.object(self.runtime, 'append_message') as mock_append:
            self.runtime.add_session_message(None, "Hello")
            mock_append.assert_called_once_with(
                {"role": "assistant", "content": "Hello"}
            )

    def test_add_session_message_with_session_id(self):
        """Test message persistence when session_id exists."""
        self.runtime.session_id = "test_session_123"
        with patch.object(self.runtime, 'append_message') as mock_append:
            self.runtime.add_session_message("user", "Test message")

            mock_append.assert_called_once()
            self.mock_ctx_manager.add_session_message.assert_called_once_with(
                "test_session_123",
                {"role": "user", "content": "Test message"}
            )

    def test_add_session_message_without_session_id(self):
        """Test no persistence when session_id is None."""
        self.runtime.session_id = None
        with patch.object(self.runtime, 'append_message') as mock_append:
            self.runtime.add_session_message("user", "Test message")

            mock_append.assert_called_once()
            self.mock_ctx_manager.add_session_message.assert_not_called()


class TestAddSessionMessageDict(TestContextRuntimeData):
    """Test cases for add_session_message_dict() method."""

    def test_add_session_message_dict_basic(self):
        """Test adding a message dictionary."""
        message = {"role": "assistant", "content": "I am here to help."}
        with patch.object(self.runtime, 'append_message') as mock_append:
            self.runtime.add_session_message_dict(message)
            mock_append.assert_called_once_with(message)

    def test_add_session_message_dict_with_session(self):
        """Test adding dict with session persistence."""
        self.runtime.session_id = "session_456"
        message = {"role": "user", "content": "Test"}

        with patch.object(self.runtime, 'append_message'):
            self.runtime.add_session_message_dict(message)

            self.mock_ctx_manager.add_session_message.assert_called_once_with(
                "session_456", message
            )

    def test_add_session_message_dict_assertion(self):
        """Test that non-dict raises AssertionError."""
        with self.assertRaises(AssertionError):
            self.runtime.add_session_message_dict("not a dict")

    def test_add_session_message_dict_empty_session(self):
        """Test dict add without session."""
        self.runtime.session_id = ""
        message = {"role": "system", "content": "System prompt"}

        with patch.object(self.runtime, 'append_message'):
            self.runtime.add_session_message_dict(message)

            self.mock_ctx_manager.add_session_message.assert_not_called()


class TestDelSessionMessage(TestContextRuntimeData):
    """Test cases for del_session_message() method."""

    def test_del_session_message_valid_index(self):
        """Test deleting a message at valid index."""
        self.runtime.session_id = "session_789"
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
            {"role": "user", "content": "msg2"},
        ]

        # Mock raw messages from ctx_manager
        mock_raw_msg = MagicMock()
        mock_raw_msg.msg_id = "msg_id_1"
        self.mock_ctx_manager.get_messages_by_session.return_value = [MagicMock(), mock_raw_msg, MagicMock()]

        self.runtime.del_session_message(1)

        # Verify message deleted from local messages
        self.assertEqual(len(self.runtime.messages), 2)
        self.assertEqual(self.runtime.messages[0]["content"], "msg0")
        self.assertEqual(self.runtime.messages[1]["content"], "msg2")

        # Verify ctx_manager called
        self.mock_ctx_manager.del_session_messages.assert_called_once_with(
            "session_789", ["msg_id_1"]
        )

    def test_del_session_message_invalid_negative_index(self):
        """Test that negative index raises AssertionError."""
        self.runtime.messages = [{"role": "user", "content": "msg"}]

        with self.assertRaises(AssertionError):
            self.runtime.del_session_message(-1)

    def test_del_session_message_invalid_out_of_range(self):
        """Test that out-of-range index raises AssertionError."""
        self.runtime.messages = [{"role": "user", "content": "msg"}]

        with self.assertRaises(AssertionError):
            self.runtime.del_session_message(5)

    def test_del_session_message_without_session(self):
        """Test deletion without session_id (local only)."""
        self.runtime.session_id = None
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
        ]

        self.runtime.del_session_message(0)

        self.assertEqual(len(self.runtime.messages), 1)
        self.mock_ctx_manager.get_messages_by_session.assert_not_called()


class TestDelSessionMessages(TestContextRuntimeData):
    """Test cases for del_session_messages() method."""

    def test_del_session_messages_multiple(self):
        """Test deleting multiple messages."""
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "msg3"},
        ]

        self.mock_json_tool.json_load.side_effect = lambda x: x

        with patch.object(self.runtime, 'set_messages') as mock_set:
            deleted = self.runtime.del_session_messages([0, 2])

            self.assertEqual(sorted(deleted), [0, 2])
            mock_set.assert_called_once()
            call_args = mock_set.call_args[0][0]
            self.assertEqual(len(call_args), 2)

    def test_del_session_messages_skip_system(self):
        """Test that system messages are skipped during deletion."""
        self.runtime.messages = [
            {"role": "system", "content": "sys0"},
            {"role": "user", "content": "msg1"},
            {"role": "system", "content": "sys2"},
            {"role": "assistant", "content": "msg3"},
        ]

        self.mock_json_tool.json_load.side_effect = lambda x: x

        deleted = self.runtime.del_session_messages([0, 2])

        # System messages should not be in deleted list
        self.assertEqual(deleted, [])

    def test_del_session_messages_empty_indexes(self):
        """Test that empty indexes returns empty list."""
        deleted = self.runtime.del_session_messages([])
        self.assertEqual(deleted, [])

    def test_del_session_messages_with_session(self):
        """Test deletion with session persistence."""
        self.runtime.session_id = "session_test"
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
        ]

        self.mock_json_tool.json_load.side_effect = lambda x: x
        mock_raw_msgs = [MagicMock(msg_id="id0"), MagicMock(msg_id="id1")]
        self.mock_ctx_manager.get_messages_by_session.return_value = mock_raw_msgs

        with patch.object(self.runtime, 'set_messages'):
            deleted = self.runtime.del_session_messages([0])

        self.mock_ctx_manager.del_session_messages.assert_called_once_with(
            "session_test", ["id0"]
        )

    def test_del_session_messages_no_matching(self):
        """Test deletion when no messages match the indexes."""
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
        ]

        self.mock_json_tool.json_load.side_effect = lambda x: x

        deleted = self.runtime.del_session_messages([5, 10])

        self.assertEqual(deleted, [])



class TestGetCurrentTokens(TestContextRuntimeData):
    """Test cases for _get_current_tokens and _get_token_calculation_messages."""

    def test_get_token_calculation_messages_returns_session_messages(self):
        """Test User2Agent uses self.messages for real-time token calculation."""
        self.runtime.messages = [{"role": "user", "content": "session"}]
        result = self.runtime._get_token_calculation_messages()
        self.assertEqual(result, self.runtime.messages)

    def test_get_current_tokens_realtime_uses_session_messages(self):
        """Test real-time calculation uses session messages for User2Agent."""
        with patch.dict(os.environ, {"TOPSAILAI_REALTIME_TOKEN_CALCULATION": "1"}):
            self.runtime.messages = [{"role": "user", "content": "x" * 1000}]
            result = self.runtime._get_current_tokens()
            self.assertIsNotNone(result)
            self.assertGreater(result, 10)

    def test_get_current_tokens_default_uses_cached_stat(self):
        """Test default behavior returns cached tokenStat.current_tokens."""
        with patch.dict(os.environ, {"TOPSAILAI_REALTIME_TOKEN_CALCULATION": "0"}):
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.llm_model.tokenStat.current_tokens = 777
            result = self.runtime._get_current_tokens()
            self.assertEqual(result, 777)

class TestIsNeedSummarize(TestContextRuntimeData):
    """Test cases for is_need_summarize_for_processed() method."""

    def test_is_need_summarize_true(self):
        """Test returns True when messages >= threshold."""
        with patch.object(self.runtime, '_get_quantity_threshold', return_value=50):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(50)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertTrue(result)

    def test_is_need_summarize_false(self):
        """Test returns False when messages < threshold."""
        with patch.object(self.runtime, '_get_quantity_threshold', return_value=50):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(30)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertFalse(result)

    def test_is_need_summarize_threshold_zero(self):
        """Test returns False when threshold is 0 (disabled)."""
        with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(100)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertFalse(result)

    def test_is_need_summarize_by_tokens_disabled(self):
        """Test token check returns False when threshold is 0 (default/disabled)."""
        with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.llm_model.tokenStat.current_tokens = 999999

            result = self.runtime.is_need_summarize_for_processed()

            self.assertFalse(result)

    def test_is_need_summarize_by_tokens_below_threshold(self):
        """Test token check returns False when current tokens are below threshold."""
        with patch.dict(os.environ, {"TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "1000"}):
            with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
                self.runtime.ai_agent = MagicMock()
                self.runtime.ai_agent.llm_model.tokenStat.current_tokens = 500

                result = self.runtime.is_need_summarize_for_processed()

                self.assertFalse(result)

    def test_is_need_summarize_by_tokens_exceeded(self):
        """Test token check returns True when current tokens exceed threshold."""
        with patch.dict(os.environ, {"TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "1000"}):
            with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
                self.runtime.ai_agent = MagicMock()
                self.runtime.ai_agent.llm_model.tokenStat.current_tokens = 1500

                result = self.runtime.is_need_summarize_for_processed()

                self.assertTrue(result)

    def test_is_need_summarize_by_tokens_no_ai_agent(self):
        """Test token check returns False when ai_agent is not available."""
        with patch.dict(os.environ, {"TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "1000"}):
            with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
                self.runtime.ai_agent = None

                result = self.runtime.is_need_summarize_for_processed()

                self.assertFalse(result)

    def test_is_need_summarize_by_tokens_no_llm_model(self):
        """Test token check returns False when llm_model is not available."""
        with patch.dict(os.environ, {"TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "1000"}):
            with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
                self.runtime.ai_agent = MagicMock()
                self.runtime.ai_agent.llm_model = None

                result = self.runtime.is_need_summarize_for_processed()

                self.assertFalse(result)

    @patch('topsailai.workspace.context.base.random.choice', return_value=13)
    def test_is_need_summarize_uses_user2agent_env_var(self, mock_choice):
        """Test that TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD is used."""
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "20",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "50",
        }):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(20)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertTrue(result)

    @patch('topsailai.workspace.context.base.random.choice', return_value=13)
    def test_is_need_summarize_user2agent_falls_back_to_legacy(self, mock_choice):
        """Test fallback to legacy shared env var when user2agent var is unset."""
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "30",
        }):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(30)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertTrue(result)
    @patch('topsailai.workspace.context.base.random.choice', return_value=13)
    def test_is_need_summarize_user2agent_wins_over_legacy(self, mock_choice):
        """Test layer-specific env var takes precedence over legacy shared var."""
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "15",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "100",
        }):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(15)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertTrue(result)

    def test_is_need_summarize_user2agent_disabled(self):
        """Test quantity summarization disabled when both user2agent and legacy are unset."""
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD": "",
            "TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD": "",
        }):
            self.runtime.messages = [{"role": "user", "content": f"msg{i}"} for i in range(200)]

            result = self.runtime.is_need_summarize_for_processed()

            self.assertFalse(result)

    def test_is_need_summarize_by_tokens_realtime_enabled(self):
        """Test token check uses real-time calculation when enabled."""
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "10",
            "TOPSAILAI_REALTIME_TOKEN_CALCULATION": "1",
        }):
            with patch.object(self.runtime, '_get_quantity_threshold', return_value=0):
                self.runtime.messages = [{"role": "user", "content": "x" * 1000}]

                result = self.runtime.is_need_summarize_for_processed()

                self.assertTrue(result)


class TestSummarizeMessages(TestContextRuntimeData):
    """Test cases for summarize_messages_for_processed() method."""

    def test_summarize_messages_success(self):
        """Test successful message summarization."""
        self.runtime.session_id = "summary_session"
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
        ]

        # Mock summarization result
        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summarized content"}
        ]
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "This is the summary")) as mock_sum:
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0) as mock_offset:
                with patch.object(self.runtime, 'reset_messages'):
                    # Mock raw messages
                    mock_raw_msg = MagicMock()
                    mock_raw_msg.msg_id = "raw_id_0"
                    self.mock_ctx_manager.get_messages_by_session.return_value = [mock_raw_msg]

                    result = self.runtime.summarize_messages_for_processed()

                    self.assertEqual(result, "This is the summary")
                    mock_sum.assert_called_once()
                    mock_offset.assert_called_once()

    def test_summarize_messages_no_messages(self):
        """Test returns None when messages list is empty."""
        self.runtime.messages = []

        result = self.runtime.summarize_messages_for_processed()

        self.assertIsNone(result)

    def test_summarize_messages_none_messages(self):
        """Test returns None when messages is None."""
        self.runtime.messages = None

        result = self.runtime.summarize_messages_for_processed(messages=None)

        self.assertIsNone(result)

    def test_summarize_messages_interactive_mode(self):
        """Test summarization with interactive confirmation."""
        self.runtime.session_id = "interactive_session"
        self.runtime.messages = [{"role": "user", "content": "msg0"}]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Interactive summary")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                with patch.object(self.runtime, 'reset_messages'):
                    self.mock_ctx_manager.get_messages_by_session.return_value = []

                    with patch('builtins.input', return_value='yes'):
                        result = self.runtime.summarize_messages_for_processed(need_interactive=True)

        self.assertEqual(result, "Interactive summary")

    def test_summarize_messages_interactive_reject(self):
        """Test interactive mode rejects answer."""
        self.runtime.session_id = "reject_session"
        self.runtime.messages = [{"role": "user", "content": "msg0"}]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Rejected summary")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                with patch.object(self.runtime, 'reset_messages'):
                    self.mock_ctx_manager.get_messages_by_session.return_value = []

                    with patch('builtins.input', return_value='no'):
                        result = self.runtime.summarize_messages_for_processed(need_interactive=True)

        # Should return answer even when rejected
        self.assertEqual(result, "Rejected summary")

    def test_summarize_messages_persist_to_memory(self):
        """Test that summary is persisted to story_memory_tool."""
        self.runtime.session_id = "memory_session"
        self.runtime.messages = [{"role": "user", "content": "msg0"}]
        self.mock_story_memory.WORKSPACE = "/tmp/workspace"

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Memory summary"}
        ]
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Memory summary content")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                with patch.object(self.runtime, 'reset_messages'):
                    self.mock_ctx_manager.get_messages_by_session.return_value = []

                    self.runtime.summarize_messages_for_processed()

        self.mock_story_memory.write_memory.assert_called_once()

    def test_summarize_messages_no_summarization_result(self):
        """Test returns None when LLM returns no answer."""
        self.runtime.messages = [{"role": "user", "content": "msg0"}]

        mock_llm_chat = MagicMock()
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, None)):
            result = self.runtime.summarize_messages_for_processed()

        self.assertIsNone(result)

    def test_summarize_messages_without_session(self):
        """Test summarization without session_id."""
        self.runtime.session_id = None
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]
        
        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "No session summary")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages') as mock_set:
                    # Mock last_user_message property
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "msg0"}
                    ):
                        result = self.runtime.summarize_messages_for_processed()

        self.assertEqual(result, "No session summary")
        mock_set.assert_called_once()

    def test_summarize_preserves_task_messages_without_session(self):
        """Test that role=user, step_name=task messages are preserved when no session_id."""
        self.runtime.session_id = None
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task preserve"}}
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
            task_msg,
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary with task")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages') as mock_set:
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "msg0"}
                    ):
                        self.runtime.summarize_messages_for_processed()

        call_args = mock_set.call_args[0][0]
        contents = [m.get("content") for m in call_args]
        self.assertIn({"step_name": "task", "raw_text": "Task preserve"}, contents)

    def test_summarize_preserves_task_messages_with_session(self):
        """Test that head-portion messages are not deleted from session.

        head_portion extends from the beginning up to and including the first
        role=user, step_name=task message. With head_offset=0 the normal
        message that precedes the task message is still part of head_portion,
        so neither raw message should be deleted.
        """
        self.runtime.session_id = "task_session"
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task session"}}
        self.runtime.messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
            task_msg,
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        mock_raw_task = MagicMock()
        mock_raw_task.msg_id = "task_id"
        mock_raw_task.message = task_msg
        mock_raw_normal = MagicMock()
        mock_raw_normal.msg_id = "normal_id"
        mock_raw_normal.message = {"role": "user", "content": "msg0"}

        self.mock_ctx_manager.get_messages_by_session.return_value = [mock_raw_normal, mock_raw_task]

        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary with task")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                with patch.object(self.runtime, 'reset_messages'):
                    self.runtime.summarize_messages_for_processed()

        # Both raw messages are inside head_portion, so neither is deleted.
        deleted_calls = self.mock_ctx_manager.del_session_messages.call_args_list
        deleted_ids = []
        for call_args in deleted_calls:
            deleted_ids.extend(call_args[0][1])
        self.assertNotIn("normal_id", deleted_ids)
        self.assertNotIn("task_id", deleted_ids)

    def test_summarize_task_messages_preserve_chronological_order_without_session(self):
        """Test that only head-portion task messages survive summarization.

        The final message list follows:
            head_portion + [summary_answer] + [last_user_message]
        where head_portion extends up to and including the first task message.
        Later task messages are part of the summarized range.
        """
        self.runtime.session_id = None
        task_msg_1 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task one"}}
        task_msg_2 = {"role": "user", "content": {"step_name": "task", "raw_text": "Task two"}}
        normal_messages = [
            {"role": "user", "content": "msg0"},
            {"role": "assistant", "content": "msg1"},
            {"role": "user", "content": "msg2"},
            {"role": "assistant", "content": "msg3"},
            {"role": "user", "content": "msg4"},
        ]
        # Order: msg0, msg1, task1, msg2, msg3, task2, msg4
        self.runtime.messages = [
            normal_messages[0],
            normal_messages[1],
            task_msg_1,
            normal_messages[2],
            normal_messages[3],
            task_msg_2,
            normal_messages[4],
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary with tasks")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages') as mock_set:
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value=normal_messages[4]
                    ):
                        self.runtime.summarize_messages_for_processed()

        call_args = mock_set.call_args[0][0]
        contents = [m.get("content") for m in call_args]
        # task1 is inside head_portion and must survive as a standalone message.
        self.assertIn({"step_name": "task", "raw_text": "Task one"}, contents)
        # task2 is after head_portion and is summarized away.
        self.assertNotIn({"step_name": "task", "raw_text": "Task two"}, contents)
        idx_task1 = contents.index({"step_name": "task", "raw_text": "Task one"})
        idx_summary = contents.index("Summary")
        # Task one is in the head portion, so it precedes the summary.
        self.assertLess(idx_task1, idx_summary)



class TestSummarizeRuntimeMessagesForProcessed(TestContextRuntimeData):
    """Test runtime-mode summarization source selection for User2Agent."""

    def _make_messages(self, count, prefix="session"):
        """Helper to create distinct session messages."""
        return [{"role": "user", "content": f"{prefix}-msg-{i}"} for i in range(count)]

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_fallback_when_longer(self, mock_get_llm_chat):
        """User2Agent runtime summary falls back to caller messages when longer."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.runtime.session_id = None
            self.runtime.messages = self._make_messages(20, "session")
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.messages = [{"role": "assistant", "content": "short"}]

            mock_llm_chat = MagicMock()
            mock_llm_chat.prompt_ctl.messages = [
                {"role": "assistant", "content": "Summary"}
            ]
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(25, "fallback")

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "fallback-msg-24"}
                    ):
                        self.runtime.summarize_messages_for_processed(messages=fallback)

            # Defensive fallback prefers the longer caller-supplied messages.
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 25)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-msg-0")

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_agent_messages_when_longer(self, mock_get_llm_chat):
        """User2Agent runtime summary uses ai_agent.messages when it is longer."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.runtime.session_id = None
            self.runtime.messages = self._make_messages(20, "session")
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.messages = self._make_messages(25, "agent")

            mock_llm_chat = MagicMock()
            mock_llm_chat.prompt_ctl.messages = [
                {"role": "assistant", "content": "Summary"}
            ]
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(20, "fallback")

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "agent-msg-24"}
                    ):
                        self.runtime.summarize_messages_for_processed(messages=fallback)

            # When ai_agent.messages is longer than fallback, runtime store is used.
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 25)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-msg-0")

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_uses_agent_messages_when_both_long(self, mock_get_llm_chat):
        """User2Agent runtime summary still prefers ai_agent.messages when both are long."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.runtime.session_id = None
            self.runtime.messages = self._make_messages(20, "session")
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.messages = self._make_messages(20, "agent")

            mock_llm_chat = MagicMock()
            mock_llm_chat.prompt_ctl.messages = [
                {"role": "assistant", "content": "Summary"}
            ]
            mock_get_llm_chat.return_value = mock_llm_chat

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "session-msg-19"}
                    ):
                        self.runtime.summarize_messages_for_processed()

            # Per MEMO.md design, ai_agent.messages represents the complete
            # runtime context and is used for runtime summary.
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 20)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "agent-msg-0")

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_runtime_summary_fallback_when_session_messages_empty(self, mock_get_llm_chat):
        """User2Agent summary falls back to caller messages when session is empty."""
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.runtime.session_id = None
            self.runtime.messages = []
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.messages = []

            mock_llm_chat = MagicMock()
            mock_llm_chat.prompt_ctl.messages = [
                {"role": "assistant", "content": "Summary"}
            ]
            mock_get_llm_chat.return_value = mock_llm_chat

            fallback = self._make_messages(10, "fallback")

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "fallback-msg-9"}
                    ):
                        self.runtime.summarize_messages_for_processed(messages=fallback)

            # Should fall back to caller-provided messages
            self.assertEqual(len(mock_llm_chat.prompt_ctl.messages), 10)
            self.assertEqual(mock_llm_chat.prompt_ctl.messages[0]["content"], "fallback-msg-0")


if __name__ == '__main__':
    unittest.main()
