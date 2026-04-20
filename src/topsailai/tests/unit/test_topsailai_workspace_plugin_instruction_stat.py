"""
Unit tests for workspace/plugin_instruction/stat.py
Author: mm-m25
Purpose: Test instruction handlers for displaying tool call statistics and errors
"""

import unittest
from unittest.mock import patch, MagicMock


class TestShowToolCallStat(unittest.TestCase):
    """Test cases for show_tool_call_stat function"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_stat = MagicMock()
        self.mock_stat.stat = {
            "api_call": {"count": 10, "success": 8, "failed": 2},
            "file_read": {"count": 5, "success": 5, "failed": 0}
        }

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_stat_success(self, mock_print, mock_tool_stat):
        """Test show_tool_call_stat with valid statistics"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_stat()
        
        mock_print.assert_called_once()
        self.assertEqual(mock_tool_stat.get_default_stat.call_count, 1)

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_stat_with_tool_name(self, mock_print, mock_tool_stat):
        """Test show_tool_call_stat with specific tool name"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_stat("api_call")
        
        mock_print.assert_called_once()

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_stat_tool_not_found(self, mock_print, mock_tool_stat):
        """Test show_tool_call_stat when tool not in statistics"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_stat("nonexistent_tool")
        
        mock_print.assert_not_called()

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_stat_empty(self, mock_print, mock_tool_stat):
        """Test show_tool_call_stat with empty statistics"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_stat
        
        mock_stat_empty = MagicMock()
        mock_stat_empty.stat = {}
        mock_tool_stat.get_default_stat.return_value = mock_stat_empty
        
        show_tool_call_stat()
        
        mock_print.assert_not_called()


class TestShowToolCallErrors(unittest.TestCase):
    """Test cases for show_tool_call_errors function"""

    def setUp(self):
        """Set up test fixtures"""
        self.mock_stat = MagicMock()
        self.mock_stat.errors = {
            "api_call": [{"error": "timeout", "count": 2}],
            "file_read": []
        }

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_errors_success(self, mock_print, mock_tool_stat):
        """Test show_tool_call_errors with valid errors"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_errors()
        
        mock_print.assert_called_once()

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_errors_with_tool_name(self, mock_print, mock_tool_stat):
        """Test show_tool_call_errors with specific tool name"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_errors("api_call")
        
        mock_print.assert_called_once()

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_errors_tool_not_found(self, mock_print, mock_tool_stat):
        """Test show_tool_call_errors when tool not in errors"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors
        
        mock_tool_stat.get_default_stat.return_value = self.mock_stat
        
        show_tool_call_errors("nonexistent_tool")
        
        mock_print.assert_not_called()

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_show_tool_call_errors_empty(self, mock_print, mock_tool_stat):
        """Test show_tool_call_errors with empty errors"""
        from topsailai.workspace.plugin_instruction.stat import show_tool_call_errors
        
        mock_stat_empty = MagicMock()
        mock_stat_empty.errors = {}
        mock_tool_stat.get_default_stat.return_value = mock_stat_empty
        
        show_tool_call_errors()
        
        mock_print.assert_not_called()


class TestLogToolCall(unittest.TestCase):
    """Test cases for log_tool_call function"""

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_log_tool_call_success(self, mock_print, mock_tool_stat):
        """Test log_tool_call exports statistics successfully"""
        from topsailai.workspace.plugin_instruction.stat import log_tool_call
        
        mock_stat = MagicMock()
        mock_stat.export_json.return_value = '{"api_call": {"count": 10}}'
        mock_tool_stat.get_default_stat.return_value = mock_stat
        
        log_tool_call()
        
        mock_stat.export_json.assert_called_once()
        mock_print.assert_called_once_with("DONE")

    @patch("topsailai.workspace.plugin_instruction.stat.tool_stat")
    @patch("builtins.print")
    def test_log_tool_call_empty(self, mock_print, mock_tool_stat):
        """Test log_tool_call with empty statistics"""
        from topsailai.workspace.plugin_instruction.stat import log_tool_call
        
        mock_stat = MagicMock()
        mock_stat.export_json.return_value = "{}"
        mock_tool_stat.get_default_stat.return_value = mock_stat
        
        log_tool_call()
        
        mock_print.assert_called_once_with("DONE")


class TestInstructions(unittest.TestCase):
    """Test cases for INSTRUCTIONS dictionary"""

    def test_instructions_has_tool_call(self):
        """Test INSTRUCTIONS has 'tool_call' key"""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS
        
        self.assertIn("tool_call", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["tool_call"]))

    def test_instructions_has_tool_call_errors(self):
        """Test INSTRUCTIONS has 'tool_call_errors' key"""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS
        
        self.assertIn("tool_call_errors", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["tool_call_errors"]))

    def test_instructions_has_tool_call_reset(self):
        """Test INSTRUCTIONS has 'tool_call_reset' key"""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS
        
        self.assertIn("tool_call_reset", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["tool_call_reset"]))

    def test_instructions_has_tool_call_log(self):
        """Test INSTRUCTIONS has 'tool_call_log' key"""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS
        
        self.assertIn("tool_call_log", INSTRUCTIONS)
        self.assertTrue(callable(INSTRUCTIONS["tool_call_log"]))

    def test_instructions_count(self):
        """Test INSTRUCTIONS has correct number of entries"""
        from topsailai.workspace.plugin_instruction.stat import INSTRUCTIONS
        
        self.assertEqual(len(INSTRUCTIONS), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
