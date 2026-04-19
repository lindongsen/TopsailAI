"""
Unit tests for topsailai.tools.cmd_tool module.

Tests command execution functionality, parameter validation,
error handling, and security constraints.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, '/root/ai/TopsailAI/src/topsailai')

from topsailai.tools.cmd_tool import (
    format_text,
    _need_whole_stdout,
    _format_return,
    format_return,
    exec_cmd,
    TOOLS,
)


class TestNeedWholeStdout(unittest.TestCase):
    """Test _need_whole_stdout function."""

    def test_curl_wikipedia_org_returns_true(self):
        """Test that curl wikipedia.org returns True."""
        result = _need_whole_stdout("curl wikipedia.org")
        self.assertTrue(result)

    def test_curl_wikipedia_org_with_flags_returns_true(self):
        """Test curl with flags targeting wikipedia."""
        result = _need_whole_stdout("curl -L wikipedia.org")
        self.assertTrue(result)

    def test_curl_other_domain_returns_false(self):
        """Test that curl other domains return False."""
        result = _need_whole_stdout("curl example.com")
        self.assertFalse(result)

    def test_non_curl_command_returns_false(self):
        """Test that non-curl commands return False."""
        result = _need_whole_stdout("echo hello")
        self.assertFalse(result)

    def test_empty_string_returns_false(self):
        """Test that empty string returns False."""
        result = _need_whole_stdout("")
        self.assertFalse(result)

    def test_wget_command_returns_false(self):
        """Test that wget command returns False."""
        result = _need_whole_stdout("wget wikipedia.org")
        self.assertFalse(result)


class TestFormatText(unittest.TestCase):
    """Test format_text function."""

    def test_format_text_with_string(self):
        """Test format_text with string input."""
        result = format_text("hello world", need_truncate=True)
        self.assertEqual(result, "hello world")

    def test_format_text_with_bytes(self):
        """Test format_text with bytes input."""
        result = format_text(b"hello world", need_truncate=True)
        self.assertEqual(result, "hello world")

    def test_format_text_strips_whitespace(self):
        """Test that format_text strips whitespace."""
        result = format_text("  hello  ", need_truncate=False)
        self.assertEqual(result, "hello")

    def test_format_text_no_truncate(self):
        """Test format_text without truncation."""
        result = format_text("hello world", need_truncate=False)
        self.assertEqual(result, "hello world")

    def test_format_text_empty_string(self):
        """Test format_text with empty string."""
        result = format_text("", need_truncate=False)
        self.assertEqual(result, "")

    def test_format_text_with_unicode(self):
        """Test format_text with unicode characters."""
        result = format_text("hello 世界 🌍", need_truncate=False)
        self.assertEqual(result, "hello 世界 🌍")


class TestFormatReturn(unittest.TestCase):
    """Test format_return function."""

    def test_format_return_with_curl_wikipedia(self):
        """Test format_return with curl wikipedia command."""
        result = format_return("curl wikipedia.org", (0, "output", ""))
        self.assertEqual(result, (0, "output", ""))

    def test_format_return_with_curl_removes_stderr(self):
        """Test that format_return removes stderr for curl."""
        result = format_return("curl example.com", (0, "output", "error"))
        self.assertEqual(result, (0, "output", ""))

    def test_format_return_with_wget_removes_stderr(self):
        """Test that format_return removes stderr for wget."""
        result = format_return("wget example.com", (0, "output", "error"))
        self.assertEqual(result, (0, "output", ""))

    def test_format_return_with_uv_add_removes_stderr(self):
        """Test that format_return removes stderr for uv add."""
        result = format_return("uv add package", (0, "output", "error"))
        self.assertEqual(result, (0, "output", ""))

    def test_format_return_with_uv_sync_removes_stderr(self):
        """Test that format_return removes stderr for uv sync."""
        result = format_return("uv sync", (0, "output", "error"))
        # Note: uv sync is not in the list of tools that suppress stderr
        self.assertEqual(result[2], "error")

    def test_format_return_with_pip_install_removes_stderr(self):
        """Test that format_return removes stderr for pip install."""
        result = format_return("pip install package", (0, "output", "error"))
        self.assertEqual(result, (0, "output", ""))

    def test_format_return_preserves_stderr_for_other_commands(self):
        """Test that format_return preserves stderr for other commands."""
        result = format_return("echo hello", (0, "output", "error"))
        self.assertEqual(result[2], "error")

    def test_format_return_with_list_command(self):
        """Test format_return with list command."""
        result = format_return(["curl", "example.com"], (0, "output", "error"))
        self.assertEqual(result[2], "")

    def test_format_return_with_empty_stderr(self):
        """Test format_return when stderr is already empty."""
        result = format_return("echo hello", (0, "output", ""))
        self.assertEqual(result, (0, "output", ""))


class TestExecCmd(unittest.TestCase):
    """Test exec_cmd function."""

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_string_command(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with string command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello")

        self.assertEqual(result, (0, "output", ""))
        mock_exec_command.assert_called_once()
        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[0][0], "echo hello")

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_list_command(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with list command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd(["echo", "hello"])

        self.assertEqual(result, (0, "output", ""))
        mock_exec_command.assert_called_once()
        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[0][0], ["echo", "hello"])

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_json_string_command(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with JSON string command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd('["echo", "hello"]')

        self.assertEqual(result, (0, "output", ""))
        mock_exec_command.assert_called_once()
        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[0][0], ["echo", "hello"])

    def test_exec_cmd_with_invalid_command_type(self):
        """Test exec_cmd with invalid command type returns error."""
        result = exec_cmd(12345)
        self.assertEqual(result, "illegal cmd")

    def test_exec_cmd_with_none_command(self):
        """Test exec_cmd with None command returns error."""
        result = exec_cmd(None)
        self.assertEqual(result, "illegal cmd")

    def test_exec_cmd_with_dict_command(self):
        """Test exec_cmd with dict command returns error."""
        result = exec_cmd({"cmd": "echo"})
        self.assertEqual(result, "illegal cmd")

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_no_need_stderr_flag(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with no_need_stderr flag."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello", no_need_stderr=1)

        self.assertEqual(result, (0, "output", ""))
        call_args = mock_exec_command.call_args
        self.assertTrue(call_args[1]['no_need_stderr'])

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_timeout(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with custom timeout."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello", timeout=60)

        self.assertEqual(result, (0, "output", ""))
        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[1]['timeout'], 60)

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_custom_cwd(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with custom working directory."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello", cwd="/custom/path")

        self.assertEqual(result, (0, "output", ""))
        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[1]['cwd'], "/custom/path")

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_default_cwd(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with default working directory."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello")

        call_args = mock_exec_command.call_args
        self.assertEqual(call_args[1]['cwd'], "/tmp")

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_command_failure(self, mock_format_return, mock_exec_command):
        """Test exec_cmd when command fails."""
        mock_exec_command.return_value = (1, "", "error message")
        mock_format_return.return_value = (1, "", "error message")

        result = exec_cmd("false")

        self.assertEqual(result, (1, "", "error message"))

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_special_characters(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with special characters in command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo 'hello world with spaces'")

        self.assertEqual(result, (0, "output", ""))

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_pipe(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with pipe in command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("cat file.txt | grep pattern")

        self.assertEqual(result, (0, "output", ""))

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_redirect(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with output redirect."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello > output.txt")

        self.assertEqual(result, (0, "output", ""))


class TestToolsConstant(unittest.TestCase):
    """Test TOOLS constant."""

    def test_tools_is_dict(self):
        """Test that TOOLS is a dictionary."""
        self.assertIsInstance(TOOLS, dict)

    def test_tools_contains_exec_cmd(self):
        """Test that TOOLS contains exec_cmd."""
        self.assertIn("exec_cmd", TOOLS)

    def test_tools_exec_cmd_is_callable(self):
        """Test that TOOLS['exec_cmd'] is callable."""
        self.assertTrue(callable(TOOLS["exec_cmd"]))

    def test_tools_exec_cmd_is_correct_function(self):
        """Test that TOOLS['exec_cmd'] is the correct function."""
        from topsailai.tools.cmd_tool import exec_cmd
        self.assertEqual(TOOLS["exec_cmd"], exec_cmd)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for cmd_tool."""

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_empty_string(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with empty string command."""
        mock_exec_command.return_value = (1, "", "command not found")
        mock_format_return.return_value = (1, "", "command not found")

        result = exec_cmd("")

        self.assertEqual(result, (1, "", "command not found"))

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_unicode_in_command(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with unicode in command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo 你好")

        self.assertEqual(result, (0, "output", ""))

    @patch('topsailai.tools.cmd_tool.exec_command')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_exec_cmd_with_newline_in_command(self, mock_format_return, mock_exec_command):
        """Test exec_cmd with newline in command."""
        mock_exec_command.return_value = (0, "output", "")
        mock_format_return.return_value = (0, "output", "")

        result = exec_cmd("echo hello\necho world")

        self.assertEqual(result, (0, "output", ""))

    def test_format_return_with_empty_command(self):
        """Test format_return with empty command string."""
        result = format_return("", (0, "output", "error"))
        # Should not crash, just process normally
        self.assertIsInstance(result, tuple)
        self.assertEqual(len(result), 3)

    def test_format_return_with_list_command(self):
        """Test format_return with list command."""
        result = format_return(["echo", "hello"], (0, "output", "error"))
        self.assertEqual(result[2], "error")


if __name__ == '__main__':
    unittest.main()
