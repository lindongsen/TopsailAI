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
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "0",
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

        # Mock print_info
        self.print_info_patcher = patch(
            'topsailai.workspace.context.ctx_runtime.print_info'
        )
        self.mock_print_info = self.print_info_patcher.start()

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
        self.print_info_patcher.stop()


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

    def setUp(self):
        """Disable the new guard for legacy summarization behavior tests."""
        super().setUp()
        self.guard_patcher = patch.object(
            self.runtime,
            '_can_summarize_user2agent_messages',
            return_value=(True, 100),
        )
        self.guard_patcher.start()

    def tearDown(self):
        """Restore the real guard after each summarization test."""
        if self.guard_patcher is not None:
            self.guard_patcher.stop()
        super().tearDown()

    def _use_real_summary_guard(self):
        """Restore the real guard for a guard-specific integration test."""
        self.guard_patcher.stop()
        self.guard_patcher = None

    def _can_summarize_with_real_guard(
            self,
            messages,
            head_offset,
            tail_offset,
            force=False,
        ):
        """Invoke the class implementation hidden by the legacy-test patch."""
        return type(self.runtime)._can_summarize_user2agent_messages(
            self.runtime,
            messages,
            head_offset,
            tail_offset,
            force=force,
        )

    def _budget_messages(self):
        """Return messages containing overlapping preserved partitions."""
        task = {"role": "user", "content": {"step_name": "task", "raw_text": "task"}}
        return [
            task,
            {"role": "assistant", "content": "compressible"},
            {"role": "user", "content": "last user"},
        ]

    def test_summary_partitions_deduplicate_overlapping_preserved_messages(self):
        """Head, tail, and last-user overlap must not duplicate token input."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()

        preserved, compressible = self.runtime._build_user2agent_summary_partitions(
            messages,
            head_offset_to_keep=1,
            tail_offset_to_keep=1,
        )

        self.assertEqual(preserved, [messages[0], messages[2]])
        self.assertEqual(compressible, [messages[1]])

    def test_preserved_budget_above_threshold_skips_correct_formula(self):
        """P=63000 and R=4096 must be rejected for T=64000."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[70000, 63000]):
                allowed, current_tokens = self._can_summarize_with_real_guard(
                    messages, 0, 0
                )

        self.assertFalse(allowed)
        self.assertEqual(current_tokens, 70000)

    def test_preserved_budget_equal_threshold_is_allowed(self):
        """P plus R equal to T remains feasible when it reduces tokens."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[70000, 59904]):
                allowed, _ = self._can_summarize_with_real_guard(messages, 0, 0)

        self.assertTrue(allowed)

    def test_zero_threshold_disables_only_threshold_budget_check(self):
        """T=0 permits a useful summary while retaining no-growth protection."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[10000, 5000]):
                allowed, _ = self._can_summarize_with_real_guard(messages, 0, 0)

        self.assertTrue(allowed)

    def test_zero_reserve_reduces_check_to_preserved_above_threshold(self):
        """R=0 allows P equal to T and rejects P above T."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "0",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[70000, 64000]):
                allowed_equal, _ = self._can_summarize_with_real_guard(messages, 0, 0)
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[70000, 64001]):
                allowed_above, _ = self._can_summarize_with_real_guard(messages, 0, 0)

        self.assertTrue(allowed_equal)
        self.assertFalse(allowed_above)

    def test_negative_and_invalid_reserve_fall_back_to_default(self):
        """Negative and invalid reserve values use the 4096 default."""
        for value in ("-1", "invalid"):
            with self.subTest(value=value):
                with patch.dict(os.environ, {
                    "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": value,
                }):
                    self.assertEqual(
                        self.runtime._get_user2agent_summary_token_reserve(),
                        4096,
                    )

    def test_no_compressible_messages_skip_without_calling_llm(self):
        """A fully preserved message list must not invoke the summary LLM."""
        self._use_real_summary_guard()
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = [{"role": "user", "content": "only message"}]
        self.runtime.messages = list(messages)
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[10000, 5000]):
                with patch.object(self.runtime, '_summarize_messages') as mock_summary:
                    result = self.runtime.summarize_messages_for_processed(messages=messages)

        self.assertIsNone(result)
        mock_summary.assert_not_called()
        self.assertEqual(self.runtime.messages, messages)

    def test_force_summarize_bypasses_conservative_budget_guard(self):
        """Forced summarization may bypass ordinary profitability estimates."""
        self._use_real_summary_guard()
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        self.runtime.messages = list(messages)
        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Forced summary"}
        ]
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(
                self.runtime,
                '_get_current_tokens',
                side_effect=[70000, 63000, 5000],
            ):
                with patch.object(
                    self.runtime,
                    '_summarize_messages',
                    return_value=(mock_llm_chat, "Forced summary"),
                ) as mock_summary:
                    with patch.object(self.runtime, 'set_messages'):
                        result = self.runtime.summarize_messages_for_processed(
                            messages=messages,
                            head_offset_to_keep=0,
                            force=True,
                        )

        self.assertEqual(result, "Forced summary")
        mock_summary.assert_called_once()

    def test_force_summarize_rejects_no_compressible_messages(self):
        """Forced summarization must preserve the no-compressible hard guard."""
        self._use_real_summary_guard()
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        self.runtime.messages = list(messages)
        with patch.object(
            self.runtime,
            '_get_tail_offset_to_keep_in_summary',
            return_value=len(messages),
        ):
            with patch.object(self.runtime, '_summarize_messages') as mock_summary:
                result = self.runtime.summarize_messages_for_processed(
                    messages=messages,
                    head_offset_to_keep=0,
                    force=True,
                )

        self.assertIsNone(result)
        mock_summary.assert_not_called()
        self.assertEqual(self.runtime.messages, messages)

    def test_force_summarize_rejects_dynamic_capacity_failure(self):
        """Forced User2Agent summary must obey dynamic capacity constraints."""
        self._use_real_summary_guard()
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        self.runtime.messages = list(messages)

        with patch.object(
            self.runtime,
            "_check_dynamic_summary_feasibility",
            return_value=(
                False,
                "preserved_budget_exceeds_safe_limit",
                700,
                600,
            ),
        ):
            with patch.object(self.runtime, "_summarize_messages") as mock_summary:
                result = self.runtime.summarize_messages_for_processed(
                    messages=messages,
                    head_offset_to_keep=0,
                    force=True,
                )

        self.assertIsNone(result)
        mock_summary.assert_not_called()
        self.assertEqual(self.runtime.messages, messages)

    def test_force_summarize_bypasses_session_threshold_recheck(self):
        """Forced session summarization must not depend on legacy thresholds."""
        self.runtime.session_id = "force-session"
        self.runtime.messages = self._budget_messages()
        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Forced summary"}
        ]
        with patch.object(self.runtime, 'reset_messages'):
            with patch.object(
                self.runtime,
                'is_need_summarize_for_processed',
                return_value=False,
            ) as mock_need:
                with patch.object(
                    self.runtime,
                    '_summarize_messages',
                    return_value=(mock_llm_chat, "Forced summary"),
                ):
                    self.mock_ctx_manager.get_messages_by_session.return_value = []
                    result = self.runtime.summarize_messages_for_processed(
                        force=True,
                    )

        self.assertEqual(result, "Forced summary")
        mock_need.assert_not_called()

    def test_budget_skip_does_not_mutate_persistent_or_memory_state(self):
        """Repeated guarded calls leave persistent and in-memory messages intact."""
        self._use_real_summary_guard()
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        self.runtime.session_id = "budget-session"
        self.runtime.messages = list(messages)
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(self.runtime, '_get_current_tokens', side_effect=[70000, 63000] * 2):
                with patch.object(self.runtime, '_summarize_messages') as mock_summary:
                    first = self.runtime.summarize_messages_for_processed(messages=messages)
                    second = self.runtime.summarize_messages_for_processed(messages=messages)

        self.assertIsNone(first)
        self.assertIsNone(second)
        mock_summary.assert_not_called()
        self.mock_ctx_manager.add_session_message.assert_not_called()
        self.mock_ctx_manager.del_session_messages.assert_not_called()
        self.assertEqual(self.runtime.messages, messages)

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

        with patch.object(self.runtime, 'is_need_summarize_for_processed', return_value=True):
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

        with patch.object(self.runtime, 'is_need_summarize_for_processed', return_value=True):
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

        with patch.object(self.runtime, 'is_need_summarize_for_processed', return_value=True):
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
        # DONOT USE NOW
        return
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



    def test_summarize_tail_offset_preserved_without_session(self):
        """Test that tail offset preserves the most recent messages without session."""
        self.runtime.session_id = None
        self.mock_json_tool.json_load.side_effect = lambda x: x
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail"}}
        self.runtime.messages = [
            task_msg,
            {"role": "assistant", "content": "msg0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
            {"role": "user", "content": "msg3"},
            {"role": "assistant", "content": "msg4"},
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary with tail"}
        ]

        with patch.object(self.runtime, 'is_need_summarize_for_processed', return_value=True):
            with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary with tail")):
                with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.runtime, '_get_tail_offset_to_keep_in_summary', return_value=2):
                        with patch.object(self.runtime, 'set_messages') as mock_set:
                            self.runtime.summarize_messages_for_processed()

        call_args = mock_set.call_args[0][0]
        contents = [m.get("content") for m in call_args]
        # The head-portion task message and the two tail messages survive.
        self.assertIn({"step_name": "task", "raw_text": "Task tail"}, contents)
        self.assertIn("Summary with tail", contents)
        self.assertIn("msg3", contents)
        self.assertIn("msg4", contents)
        # msg0, msg1 and msg2 are in the summarized range.
        self.assertNotIn("msg0", contents)
        self.assertNotIn("msg1", contents)
        self.assertNotIn("msg2", contents)

        # Verify required order: head_portion + tail_portion + summary + last_user_message.
        idx_task = contents.index({"step_name": "task", "raw_text": "Task tail"})
        idx_msg3 = contents.index("msg3")
        idx_msg4 = contents.index("msg4")
        idx_summary = contents.index("Summary with tail")
        self.assertLess(idx_task, idx_msg3)
        self.assertLess(idx_task, idx_msg4)
        self.assertLess(idx_msg3, idx_summary)
        self.assertLess(idx_msg4, idx_summary)

    def test_summarize_tail_offset_preserved_with_session(self):
        """Test that tail offset prevents deletion of recent raw session messages."""
        self.runtime.session_id = "tail_session"
        self.mock_json_tool.json_load.side_effect = lambda x: x
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail session"}}
        self.runtime.messages = [
            task_msg,
        ] + [
            {"role": "assistant" if i % 2 else "user", "content": f"msg{i}"}
            for i in range(9)
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        mock_raw_msgs = []
        raw_task = MagicMock()
        raw_task.msg_id = "task_id"
        raw_task.message = task_msg
        mock_raw_msgs.append(raw_task)
        for i in range(9):
            raw = MagicMock()
            raw.msg_id = f"id{i}"
            raw.message = {"role": "assistant" if i % 2 else "user", "content": f"msg{i}"}
            mock_raw_msgs.append(raw)

        self.mock_ctx_manager.get_messages_by_session.return_value = mock_raw_msgs

        with patch.object(self.runtime, 'is_need_summarize_for_processed', return_value=True):
            with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary with tail")):
                with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.runtime, '_get_tail_offset_to_keep_in_summary', return_value=2):
                        with patch.object(self.runtime, 'reset_messages'):
                            self.runtime.summarize_messages_for_processed()

        deleted_calls = self.mock_ctx_manager.del_session_messages.call_args_list
        deleted_ids = []
        for call_args in deleted_calls:
            deleted_ids.extend(call_args[0][1])

        # The head-portion task message and the two tail raw messages survive.
        self.assertNotIn("task_id", deleted_ids)
        self.assertNotIn("id7", deleted_ids)
        self.assertNotIn("id8", deleted_ids)
        # id0-id6 are in the summarized range and should be deleted.
        for i in range(7):
            self.assertIn(f"id{i}", deleted_ids)

    def test_summarize_tail_offset_zero_preserves_only_last_user_message(self):
        """Test that tail offset 0 preserves only head-portion and last user message."""
        self.runtime.session_id = None
        self.mock_json_tool.json_load.side_effect = lambda x: x
        task_msg = {"role": "user", "content": {"step_name": "task", "raw_text": "Task tail zero"}}
        self.runtime.messages = [
            task_msg,
            {"role": "assistant", "content": "msg0"},
            {"role": "user", "content": "msg1"},
            {"role": "assistant", "content": "msg2"},
        ]

        mock_llm_chat = MagicMock()
        mock_llm_chat.prompt_ctl.messages = [
            {"role": "assistant", "content": "Summary"}
        ]

        with patch.object(self.runtime, '_summarize_messages', return_value=(mock_llm_chat, "Summary")):
            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=0):
                with patch.object(self.runtime, '_get_tail_offset_to_keep_in_summary', return_value=0):
                    with patch.object(self.runtime, 'set_messages') as mock_set:
                        self.runtime.summarize_messages_for_processed()

        call_args = mock_set.call_args[0][0]
        contents = [m.get("content") for m in call_args]
        # The head-portion task message and the real last user message survive.
        self.assertIn({"step_name": "task", "raw_text": "Task tail zero"}, contents)
        self.assertIn("Summary", contents)
        self.assertIn("msg1", contents)
        self.assertNotIn("msg0", contents)
        self.assertNotIn("msg2", contents)

        # Verify required order: head_portion + summary + last_user_message.
        idx_task = contents.index({"step_name": "task", "raw_text": "Task tail zero"})
        idx_summary = contents.index("Summary")
        idx_msg1 = contents.index("msg1")
        self.assertLess(idx_task, idx_summary)
        self.assertLess(idx_summary, idx_msg1)


    def test_force_flag_differentiates_preserved_budget_soft_guard(self):
        """Force bypasses the fixed-threshold budget guard, but not by default."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "64000",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(
                self.runtime,
                "_get_current_tokens",
                side_effect=[70000, 63000, 70000, 63000],
            ):
                ordinary, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=False
                )
                forced, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=True
                )

        self.assertFalse(ordinary)
        self.assertTrue(forced)

    def test_force_flag_differentiates_no_reduction_soft_guard(self):
        """Force bypasses an unprofitable size estimate while ordinary mode rejects."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "0",
            "TOPSAILAI_USER2AGENT_SUMMARY_TOKEN_RESERVE": "4096",
        }):
            with patch.object(
                self.runtime,
                "_get_current_tokens",
                side_effect=[5000, 1000, 5000, 1000],
            ):
                ordinary, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=False
                )
                forced, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=True
                )

        self.assertFalse(ordinary)
        self.assertTrue(forced)

    def test_force_rejects_unavailable_summary_input_tokens(self):
        """Force cannot bypass unavailable dynamic summary-input accounting."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()
        with patch.object(
            self.runtime,
            "_get_current_tokens",
            side_effect=[70000, 1000],
        ):
            with patch.object(
                self.runtime,
                "_check_dynamic_summary_feasibility",
                return_value=(
                    False,
                    "summary_input_tokens_unavailable",
                    None,
                    50000,
                ),
            ):
                allowed, current_tokens = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=True
                )

        self.assertFalse(allowed)
        self.assertEqual(current_tokens, 70000)

    def test_disabled_threshold_still_rejects_no_compressible_messages(self):
        """A disabled fixed threshold does not disable the hard partition guard."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = [{"role": "user", "content": "only preserved user"}]
        with patch.dict(os.environ, {
            "TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD": "0",
        }):
            with patch.object(
                self.runtime,
                "_get_current_tokens",
                side_effect=[100, 100, 100, 100],
            ):
                ordinary, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=False
                )
                forced, _ = self._can_summarize_with_real_guard(
                    messages, 0, 0, force=True
                )

        self.assertFalse(ordinary)
        self.assertFalse(forced)

    def test_summary_partitions_without_user_message_preserve_head_portion(self):
        """Assistant-only history preserves the capped head but not an implicit tail."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = [
            {"role": "assistant", "content": f"message-{index}"}
            for index in range(12)
        ]

        preserved, compressible = self.runtime._build_user2agent_summary_partitions(
            messages,
            head_offset_to_keep=1,
            tail_offset_to_keep=0,
        )

        self.assertEqual(preserved, messages[:9])
        self.assertEqual(compressible, messages[9:])
        self.assertNotIn(messages[-1], preserved)

    def test_summary_partitions_deduplicate_fully_overlapping_offsets(self):
        """Overlapping head, tail, and last-user ranges preserve each item once."""
        self.mock_json_tool.json_load.side_effect = lambda value: value
        messages = self._budget_messages()

        preserved, compressible = self.runtime._build_user2agent_summary_partitions(
            messages,
            head_offset_to_keep=len(messages),
            tail_offset_to_keep=len(messages),
        )

        self.assertEqual(preserved, messages)
        self.assertEqual(len(preserved), len(messages))
        self.assertEqual(compressible, [])

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

    @patch('topsailai.workspace.context.base.get_llm_chat')
    def test_ct4_branch_select_with_and_without_ai_agent(self, mock_get_llm_chat):
        """CT-4: User2Agent runtime summary selects agent store when present,
        else falls back to the session store.

        The runtime summarizer consumes the complete pre-summary Agent2LLM
        runtime context when available, allowing the summary request to reuse
        the prompt prefix from the immediately preceding Agent2LLM inference.
        When no agent exists, it falls back to the session store.
        """
        with patch.dict(os.environ, {"TOPSAILAI_CONTEXT_SUMMARY_MODE": "runtime"}):
            self.runtime.session_id = None

            # --- Branch A: ai_agent present -> forwards ai_agent.messages ---
            self.runtime.messages = self._make_messages(10, "session")
            self.runtime.ai_agent = MagicMock()
            self.runtime.ai_agent.messages = self._make_messages(15, "agent")

            mock_a = MagicMock()
            mock_a.prompt_ctl.messages = [{"role": "assistant", "content": "Summary"}]
            mock_get_llm_chat.return_value = mock_a

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "agent-msg-14"},
                    ):
                        self.runtime.summarize_messages_for_processed()

            self.assertEqual(len(mock_a.prompt_ctl.messages), 15)
            self.assertEqual(mock_a.prompt_ctl.messages[0]["content"], "agent-msg-0")

            # --- Branch B: ai_agent absent -> forwards self.messages ---
            self.runtime.ai_agent = None
            self.runtime.messages = self._make_messages(12, "session")

            mock_b = MagicMock()
            mock_b.prompt_ctl.messages = [{"role": "assistant", "content": "Summary"}]
            mock_get_llm_chat.return_value = mock_b

            with patch.object(self.runtime, '_get_head_offset_to_keep_in_summary', return_value=1):
                with patch.object(self.runtime, 'set_messages'):
                    with patch.object(
                        type(self.runtime),
                        'last_user_message',
                        new_callable=PropertyMock,
                        return_value={"role": "user", "content": "session-msg-11"},
                    ):
                        self.runtime.summarize_messages_for_processed()

            self.assertEqual(len(mock_b.prompt_ctl.messages), 12)
            self.assertEqual(mock_b.prompt_ctl.messages[0]["content"], "session-msg-0")


if __name__ == '__main__':
    unittest.main()
