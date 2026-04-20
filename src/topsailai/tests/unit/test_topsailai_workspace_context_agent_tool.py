"""
Unit tests for workspace/context/agent_tool.py

Author: mm-m25
Purpose: Test ContextRuntimeAgentTools class for tool registration and execution

Test Coverage:
- ContextRuntimeAgentTools class initialization
- Tool registration with add_tool
- tool_delete_messages_for_processed method
- tool_delete_messages_for_processing method
- Edge cases for message deletion
"""

import unittest
from unittest.mock import MagicMock, patch


class TestContextRuntimeAgentTools(unittest.TestCase):
    """Test suite for ContextRuntimeAgentTools class."""

    def setUp(self):
        """Set up test fixtures."""
        # Mock ctx_runtime_data
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-123"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = MagicMock()

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    def test_init_registers_tools(self, mock_add_tool, mock_parent_class):
        """Test that __init__ registers tools with add_tool."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)

        # Verify add_tool was called for the registered tool
        self.assertTrue(mock_add_tool.called)
        call_args_list = mock_add_tool.call_args_list
        tool_names = [call[0][0] for call in call_args_list]
        self.assertIn("context-cut_messages", tool_names)

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    def test_init_stores_ctx_runtime_data(self, mock_add_tool, mock_parent_class):
        """Test that __init__ stores ctx_runtime_data reference."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)

        # Verify ctx_runtime_data is stored in the instance
        self.assertEqual(instance.ctx_runtime_data, self.mock_ctx_runtime_data)

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    def test_tools_dictionary_contains_expected_tools(self, mock_add_tool, mock_parent_class):
        """Test that TOOLS dictionary contains expected tool names."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)

        self.assertIn("context-cut_messages", instance.TOOLS)

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    def test_tool_handler_is_callable(self, mock_add_tool, mock_parent_class):
        """Test that registered tool handlers are callable."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)

        tool_handler = instance.TOOLS.get("context-cut_messages")
        self.assertIsNotNone(tool_handler)
        self.assertTrue(callable(tool_handler))


class TestToolDeleteMessagesForProcessed(unittest.TestCase):
    """Test suite for tool_delete_messages_for_processed method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-123"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = MagicMock()
        self.mock_ctx_runtime_data.del_session_messages = MagicMock(return_value=2)

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_valid_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting messages with valid indexes."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [1, 2, 3]

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processed([1, 2, 3])

        mock_format_tool.to_list_int.assert_called_once_with([1, 2, 3])
        self.mock_ctx_runtime_data.del_session_messages.assert_called_once_with([1, 2, 3])
        self.assertEqual(result, "deleted ok: 2")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_empty_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting messages with empty indexes returns 'do nothing'."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = []

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processed([])

        self.assertEqual(result, "do nothing")
        self.mock_ctx_runtime_data.del_session_messages.assert_not_called()

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_none_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting messages with None indexes returns 'do nothing'."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = []

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processed(None)

        self.assertEqual(result, "do nothing")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_calls_del_session_messages(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that delete_messages_for_processed calls del_session_messages."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [0, 5, 10]

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        instance.tool_delete_messages_for_processed([0, 5, 10])

        self.mock_ctx_runtime_data.del_session_messages.assert_called_once_with([0, 5, 10])


class TestToolDeleteMessagesForProcessing(unittest.TestCase):
    """Test suite for tool_delete_messages_for_processing method."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-123"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = MagicMock()
        self.mock_ctx_runtime_data.del_agent_messages = MagicMock(return_value=3)

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_valid_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting agent messages with valid indexes."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [11, 12, 13]

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing([11, 12, 13])

        mock_format_tool.to_list_int.assert_called_once_with([11, 12, 13])
        self.mock_ctx_runtime_data.del_agent_messages.assert_called_once_with([11, 12, 13])
        self.assertEqual(result, "deleted ok: 3")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_empty_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting agent messages with empty indexes returns 'do nothing'."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = []

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing([])

        self.assertEqual(result, "do nothing")
        self.mock_ctx_runtime_data.del_agent_messages.assert_not_called()

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_with_none_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test deleting agent messages with None indexes returns 'do nothing'."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = []

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing(None)

        self.assertEqual(result, "do nothing")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_calls_del_agent_messages(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that delete_messages_for_processing calls del_agent_messages."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [0, 1, 2]

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        instance.tool_delete_messages_for_processing([0, 1, 2])

        self.mock_ctx_runtime_data.del_agent_messages.assert_called_once_with([0, 1, 2])

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_delete_messages_returns_correct_format(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that delete_messages returns correct format string."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [1]
        self.mock_ctx_runtime_data.del_agent_messages.return_value = 5

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing([1])

        self.assertEqual(result, "deleted ok: 5")


class TestEdgeCases(unittest.TestCase):
    """Test suite for edge cases in ContextRuntimeAgentTools."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_ctx_runtime_data = MagicMock()
        self.mock_ctx_runtime_data.session_id = "test-session-123"
        self.mock_ctx_runtime_data.messages = []
        self.mock_ctx_runtime_data.ai_agent = MagicMock()

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_format_tool_converts_string_indexes(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that format_tool.to_list_int handles string conversion."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = [1, 2, 3]
        self.mock_ctx_runtime_data.del_agent_messages = MagicMock(return_value=2)

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing("1,2,3")

        mock_format_tool.to_list_int.assert_called_once_with("1,2,3")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_format_tool_handles_invalid_input(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that format_tool.to_list_int handles invalid input."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        mock_format_tool.to_list_int.return_value = []

        instance = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        result = instance.tool_delete_messages_for_processing("invalid")

        self.assertEqual(result, "do nothing")

    @patch("topsailai.workspace.context.agent_tool.ContextRuntimeAIAgent")
    @patch("topsailai.workspace.context.agent_tool.add_tool")
    @patch("topsailai.workspace.context.agent_tool.format_tool")
    def test_multiple_tool_registrations(self, mock_format_tool, mock_add_tool, mock_parent_class):
        """Test that multiple instances register tools correctly."""
        from topsailai.workspace.context.agent_tool import ContextRuntimeAgentTools

        instance1 = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)
        instance2 = ContextRuntimeAgentTools(self.mock_ctx_runtime_data)

        # Both instances should have called add_tool
        self.assertEqual(mock_add_tool.call_count, 2)  # 1 tool x 2 instances


if __name__ == "__main__":
    unittest.main()
