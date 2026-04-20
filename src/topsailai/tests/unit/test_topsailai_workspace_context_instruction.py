"""
Unit tests for workspace/context/instruction.py module.

Tests for ContextRuntimeInstructions class which provides instruction
handlers for managing context messages in the TopsailAI workspace.

Author: DawsonLin
Created: 2026-04-19
"""

import unittest
from unittest.mock import MagicMock, patch, PropertyMock


class TestContextRuntimeInstructions(unittest.TestCase):
    """Test suite for ContextRuntimeInstructions class."""

    def setUp(self):
        """Set up test fixtures."""
        # Create mock ctx_runtime_data
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = None
        self.mock_ctx_runtime_data.messages = []

        # Mock all external dependencies before import
        self.ctx_manager_patcher = patch('topsailai.workspace.context.instruction.ctx_manager')
        self.mock_ctx_manager = self.ctx_manager_patcher.start()

        self.subprocess_patcher = patch(
            'topsailai.workspace.context.instruction.subprocess_agent_memory_as_story'
        )
        self.mock_subprocess = self.subprocess_patcher.start()

        self.print_ctx_patcher = patch(
            'topsailai.workspace.context.instruction.print_context_messages'
        )
        self.mock_print_ctx = self.print_ctx_patcher.start()

        self.print_raw_patcher = patch(
            'topsailai.workspace.context.instruction.print_raw_messages'
        )
        self.mock_print_raw = self.print_raw_patcher.start()

        # Patch ContextRuntimeUtils to avoid calling its __init__
        self.utils_patcher = patch(
            'topsailai.workspace.context.instruction.ContextRuntimeUtils.__init__',
            return_value=None
        )
        self.mock_utils = self.utils_patcher.start()

        # Import after patching
        from topsailai.workspace.context.instruction import ContextRuntimeInstructions
        self.instruction = ContextRuntimeInstructions.__new__(ContextRuntimeInstructions)
        self.instruction.ctx_runtime_data = self.mock_ctx_runtime_data

    def tearDown(self):
        """Clean up test fixtures."""
        self.ctx_manager_patcher.stop()
        self.subprocess_patcher.stop()
        self.print_ctx_patcher.stop()
        self.print_raw_patcher.stop()
        self.utils_patcher.stop()

    ##############################################################################
    # TestInstructionsProperty
    ##############################################################################
    def test_instructions_returns_dict(self):
        """Test that instructions property returns a dictionary."""
        result = self.instruction.instructions
        self.assertIsInstance(result, dict)

    def test_instructions_contains_expected_keys(self):
        """Test that all expected instruction keys are present."""
        expected_keys = [
            "ctx.clear",
            "ctx.story",
            "ctx.history",
            "ctx.history2",
            "ctx.del_msg",
            "ctx.del_msgs",
            "ctx.summarize",
        ]
        result = self.instruction.instructions
        for key in expected_keys:
            self.assertIn(key, result)

    ##############################################################################
    # TestCtxRefresh
    ##############################################################################
    def test_ctx_refresh_with_session(self):
        """Test ctx_refresh when session_id exists."""
        self.mock_ctx_runtime_data.session_id = "test_session_123"
        self.instruction.ctx_refresh()
        self.mock_ctx_runtime_data.reset_messages.assert_called_once()

    def test_ctx_refresh_without_session(self):
        """Test ctx_refresh when session_id is None."""
        self.mock_ctx_runtime_data.session_id = None
        self.instruction.ctx_refresh()
        self.mock_ctx_runtime_data.reset_messages.assert_not_called()

    ##############################################################################
    # TestCtxClear
    ##############################################################################
    def test_ctx_clear_without_session(self):
        """Test ctx_clear when no session exists - should clear messages."""
        self.mock_ctx_runtime_data.session_id = None
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2", "msg3"]

        self.instruction.ctx_clear()

        self.assertEqual(len(self.mock_ctx_runtime_data.messages), 0)

    def test_ctx_clear_with_session(self):
        """Test ctx_clear when session exists - should not clear."""
        self.mock_ctx_runtime_data.session_id = "active_session"
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2"]

        self.instruction.ctx_clear()

        # Messages should remain unchanged
        self.assertEqual(len(self.mock_ctx_runtime_data.messages), 2)

    ##############################################################################
    # TestCtxStory
    ##############################################################################
    def test_ctx_story_with_messages(self):
        """Test ctx_story when messages exist - should save to story."""
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2"]
        self.mock_subprocess.return_value = "pid_123"

        self.instruction.ctx_story()

        self.mock_subprocess.assert_called_once_with(self.mock_ctx_runtime_data.messages)

    def test_ctx_story_without_messages(self):
        """Test ctx_story when no messages - should skip."""
        self.mock_ctx_runtime_data.messages = []

        self.instruction.ctx_story()

        self.mock_subprocess.assert_not_called()

    ##############################################################################
    # TestCtxHistory
    ##############################################################################
    def test_ctx_history_all_messages(self):
        """Test ctx_history displays all messages when no offset."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2", "msg3"]

        self.instruction.ctx_history()

        self.mock_ctx_runtime_data.reset_messages.assert_called_once()
        self.mock_print_ctx.assert_called_once_with(self.mock_ctx_runtime_data.messages)

    def test_ctx_history_with_offset_single(self):
        """Test ctx_history with single offset value."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg0", "msg1", "msg2", "msg3", "msg4"]

        self.instruction.ctx_history(offset="2")

        # Single offset "2" should become [2:-2]
        expected_msgs = self.mock_ctx_runtime_data.messages[2:-2]
        self.mock_print_ctx.assert_called_with(expected_msgs)

    def test_ctx_history_with_offset_range(self):
        """Test ctx_history with range offset like '1:3'."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg0", "msg1", "msg2", "msg3", "msg4"]

        self.instruction.ctx_history(offset="1:3")

        # Range "1:3" should slice [1:3]
        expected_msgs = self.mock_ctx_runtime_data.messages[1:3]
        self.mock_print_ctx.assert_called_with(expected_msgs)

    ##############################################################################
    # TestCtxHistory2
    ##############################################################################
    def test_ctx_history2_raw_messages(self):
        """Test ctx_history2 displays raw messages."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        raw_msgs = ["raw1", "raw2"]
        self.mock_ctx_manager.get_messages_by_session.return_value = raw_msgs

        self.instruction.ctx_history2()

        self.mock_ctx_manager.get_messages_by_session.assert_called_once_with(
            "test_session", for_raw=True
        )
        self.mock_print_raw.assert_called_once_with(raw_msgs)

    ##############################################################################
    # TestCtxDeleteMessage
    ##############################################################################
    def test_ctx_delete_message_success(self):
        """Test deleting a valid message by index."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2", "msg3"]

        self.instruction.ctx_delete_message(2)

        self.mock_ctx_runtime_data.del_session_message.assert_called_once_with(1)

    def test_ctx_delete_message_invalid_index(self):
        """Test deleting with invalid index raises AssertionError."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2"]

        with self.assertRaises(AssertionError):
            self.instruction.ctx_delete_message(5)

    def test_ctx_delete_message_zero_index(self):
        """Test deleting with zero index raises AssertionError."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.messages = ["msg1", "msg2"]

        with self.assertRaises(AssertionError):
            self.instruction.ctx_delete_message(0)

    ##############################################################################
    # TestCtxDeleteMessages
    ##############################################################################
    def test_ctx_delete_messages_multiple(self):
        """Test deleting multiple messages by indexes."""
        self.mock_ctx_runtime_data.session_id = "test_session"
        self.mock_ctx_runtime_data.del_session_messages.return_value = [0, 2]

        self.instruction.ctx_delete_messages(1, 3)

        self.mock_ctx_runtime_data.del_session_messages.assert_called_once_with([0, 2])

    ##############################################################################
    # TestCtxSummarize
    ##############################################################################
    def test_ctx_summarize_success(self):
        """Test ctx_summarize calls summarize_messages_for_processed."""
        self.mock_ctx_runtime_data.session_id = "test_session"

        self.instruction.ctx_summarize(head_offset_to_keep=2, need_interactive=0)

        self.mock_ctx_runtime_data.summarize_messages_for_processed.assert_called_once_with(
            head_offset_to_keep=2,
            need_interactive=False,
        )

    def test_ctx_summarize_default_params(self):
        """Test ctx_summarize with default parameters."""
        self.mock_ctx_runtime_data.session_id = "test_session"

        self.instruction.ctx_summarize()

        self.mock_ctx_runtime_data.summarize_messages_for_processed.assert_called_once_with(
            head_offset_to_keep=1,
            need_interactive=True,
        )

    def test_ctx_summarize_interactive_mode(self):
        """Test ctx_summarize with interactive mode enabled."""
        self.mock_ctx_runtime_data.session_id = "test_session"

        self.instruction.ctx_summarize(head_offset_to_keep=3, need_interactive=1)

        self.mock_ctx_runtime_data.summarize_messages_for_processed.assert_called_once_with(
            head_offset_to_keep=3,
            need_interactive=True,
        )


if __name__ == '__main__':
    unittest.main()
