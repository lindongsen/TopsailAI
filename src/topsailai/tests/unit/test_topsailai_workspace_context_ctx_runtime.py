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


if __name__ == '__main__':
    unittest.main()
