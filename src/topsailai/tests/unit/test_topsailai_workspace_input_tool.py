"""
Unit tests for workspace/input_tool module.

Test coverage:
- hook_message: Hook processing, exit command handling, TRIGGER_CHARS logic
- input_one_line: Single-line input with hook processing
- input_multi_line: Multi-line input with EOF handling
- input_message: Env-based input mode selection
- call_hook_get_message_for_task_from_file: Env var setting for file-based messages
- get_message: Message from argv, stdin, or interactive input
- input_yes: Yes/no confirmation
"""

import os
import sys
import unittest
from unittest.mock import patch, MagicMock, mock_open


class TestHookMessage(unittest.TestCase):
    """Test cases for hook_message function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hook = MagicMock()

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    def test_empty_message_returns_false(self):
        """Test that empty message returns False."""
        from topsailai.workspace.input_tool import hook_message
        result = hook_message("", self.mock_hook)
        self.assertFalse(result)

    def test_whitespace_only_message_returns_false(self):
        """Test that whitespace-only message returns False."""
        from topsailai.workspace.input_tool import hook_message
        result = hook_message("   ", self.mock_hook)
        self.assertFalse(result)

    def test_exit_command_calls_sys_exit(self):
        """Test that 'exit' command triggers sys.exit."""
        from topsailai.workspace.input_tool import hook_message
        with self.assertRaises(SystemExit):
            hook_message("exit", self.mock_hook)

    def test_quit_command_calls_sys_exit(self):
        """Test that 'quit' command triggers sys.exit."""
        from topsailai.workspace.input_tool import hook_message
        with self.assertRaises(SystemExit):
            hook_message("quit", self.mock_hook)

    def test_slash_exit_command_calls_sys_exit(self):
        """Test that '/exit' command triggers sys.exit."""
        from topsailai.workspace.input_tool import hook_message
        with self.assertRaises(SystemExit):
            hook_message("/exit", self.mock_hook)

    def test_slash_quit_command_calls_sys_exit(self):
        """Test that '/quit' command triggers sys.exit."""
        from topsailai.workspace.input_tool import hook_message
        with self.assertRaises(SystemExit):
            hook_message("/quit", self.mock_hook)

    def test_none_hook_returns_false(self):
        """Test that None hook returns False without calling anything."""
        from topsailai.workspace.input_tool import hook_message
        result = hook_message("hello", None)
        self.assertFalse(result)

    def test_existing_hook_is_called(self):
        """Test that existing hook is called and returns True."""
        from topsailai.workspace.input_tool import hook_message
        self.mock_hook.exist_hook.return_value = True
        result = hook_message("/custom", self.mock_hook)
        self.assertTrue(result)
        self.mock_hook.call_hook.assert_called_once_with("/custom")

    def test_trigger_char_calls_help_hook(self):
        """Test that trigger char messages call /help hook."""
        from topsailai.workspace.input_tool import hook_message
        self.mock_hook.exist_hook.return_value = False
        result = hook_message("/test", self.mock_hook)
        self.assertTrue(result)
        self.mock_hook.call_hook.assert_called_once_with("/help /test")

    def test_noop_command_returns_false(self):
        """Test that /noop command returns False without calling help."""
        from topsailai.workspace.input_tool import hook_message
        self.mock_hook.exist_hook.return_value = False
        result = hook_message("/noop", self.mock_hook)
        self.assertFalse(result)
        self.mock_hook.call_hook.assert_not_called()

    def test_regular_message_returns_false(self):
        """Test that regular message without hook returns False."""
        from topsailai.workspace.input_tool import hook_message
        self.mock_hook.exist_hook.return_value = False
        result = hook_message("hello world", self.mock_hook)
        self.assertFalse(result)


class TestInputOneLine(unittest.TestCase):
    """Test cases for input_one_line function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hook = MagicMock()

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_returns_user_input(self, mock_hook_message, mock_input):
        """Test that valid user input is returned."""
        from topsailai.workspace.input_tool import input_one_line
        mock_input.return_value = "hello"
        mock_hook_message.return_value = False
        result = input_one_line(">>> ", self.mock_hook)
        self.assertEqual(result, "hello")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_empty_input_continues_loop(self, mock_hook_message, mock_input):
        """Test that empty input continues the loop."""
        from topsailai.workspace.input_tool import input_one_line
        mock_input.side_effect = ["", "valid input"]
        mock_hook_message.return_value = False
        result = input_one_line(">>> ", self.mock_hook)
        self.assertEqual(result, "valid input")
        self.assertEqual(mock_input.call_count, 2)

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_whitespace_input_continues_loop(self, mock_hook_message, mock_input):
        """Test that whitespace-only input continues the loop."""
        from topsailai.workspace.input_tool import input_one_line
        mock_input.side_effect = ["  ", "\t", "valid input"]
        mock_hook_message.return_value = False
        result = input_one_line(">>> ", self.mock_hook)
        self.assertEqual(result, "valid input")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_hook_triggered_input_continues_loop(self, mock_hook_message, mock_input):
        """Test that hook-triggered input continues the loop."""
        from topsailai.workspace.input_tool import input_one_line
        mock_input.side_effect = ["/help", "valid input"]
        mock_hook_message.side_effect = [True, False]
        result = input_one_line(">>> ", self.mock_hook)
        self.assertEqual(result, "valid input")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_noop_returns_empty_string(self, mock_hook_message, mock_input):
        """Test that /noop returns empty string."""
        from topsailai.workspace.input_tool import input_one_line
        mock_input.return_value = "/noop"
        mock_hook_message.return_value = False
        result = input_one_line(">>> ", self.mock_hook)
        self.assertEqual(result, "")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_default_tips_used(self, mock_hook_message, mock_input):
        """Test that default INPUT_TIPS is used when tips is empty."""
        from topsailai.workspace.input_tool import input_one_line, INPUT_TIPS
        mock_input.return_value = "test"
        mock_hook_message.return_value = False
        result = input_one_line("", self.mock_hook)
        self.assertEqual(result, "test")
        mock_input.assert_called_once_with(INPUT_TIPS)


class TestInputMultiLine(unittest.TestCase):
    """Test cases for input_multi_line function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hook = MagicMock()

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_eof_terminates_input(self, mock_hook_message, mock_input):
        """Test that EOF terminates multi-line input."""
        from topsailai.workspace.input_tool import input_multi_line
        mock_input.side_effect = ["line1", "EOF"]
        mock_hook_message.return_value = False
        result = input_multi_line(">>> ", self.mock_hook)
        self.assertEqual(result, "line1")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_multiple_lines_combined(self, mock_hook_message, mock_input):
        """Test that multiple lines are combined with newlines."""
        from topsailai.workspace.input_tool import input_multi_line
        mock_input.side_effect = ["line1", "line2", "EOF"]
        mock_hook_message.return_value = False
        result = input_multi_line(">>> ", self.mock_hook)
        self.assertEqual(result, "line1\nline2")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_hook_on_first_line_clears_message(self, mock_hook_message, mock_input):
        """Test that hook triggered on first line clears message."""
        from topsailai.workspace.input_tool import input_multi_line
        mock_input.side_effect = ["line1", "EOF"]
        mock_hook_message.return_value = True
        with patch("topsailai.workspace.input_tool.input_multi_line", return_value=""):
            result = input_multi_line(">>> ", self.mock_hook)
        self.assertEqual(result, "")

    @patch("topsailai.workspace.input_tool.input")
    @patch("topsailai.workspace.input_tool.hook_message")
    def test_noop_returns_empty_string(self, mock_hook_message, mock_input):
        """Test that /noop returns empty string."""
        from topsailai.workspace.input_tool import input_multi_line
        mock_input.side_effect = ["  /noop", "EOF"]
        mock_hook_message.return_value = False
        result = input_multi_line(">>> ", self.mock_hook)
        self.assertEqual(result, "")


class TestInputMessage(unittest.TestCase):
    """Test cases for input_message function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hook = MagicMock()

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    @patch("topsailai.workspace.input_tool.input_one_line")
    @patch("topsailai.workspace.input_tool.env_tool")
    def test_single_line_mode(self, mock_env_tool, mock_input_one_line):
        """Test that single-line mode calls input_one_line."""
        from topsailai.workspace.input_tool import input_message
        mock_env_tool.is_chat_multi_line.return_value = False
        mock_input_one_line.return_value = "test message"
        result = input_message(">>> ", self.mock_hook)
        self.assertEqual(result, "test message")
        mock_input_one_line.assert_called_once()

    @patch("topsailai.workspace.input_tool.input_multi_line")
    @patch("topsailai.workspace.input_tool.env_tool")
    def test_multi_line_mode(self, mock_env_tool, mock_input_multi_line):
        """Test that multi-line mode calls input_multi_line."""
        from topsailai.workspace.input_tool import input_message
        mock_env_tool.is_chat_multi_line.return_value = True
        mock_input_multi_line.return_value = "multi\nline\nmessage"
        result = input_message(">>> ", self.mock_hook)
        self.assertEqual(result, "multi\nline\nmessage")
        mock_input_multi_line.assert_called_once()

    @patch("builtins.print")
    def test_prints_split_line(self, mock_print):
        """Test that split line is printed before input."""
        from topsailai.workspace.input_tool import input_message, SPLIT_LINE
        with patch("topsailai.workspace.input_tool.input_one_line", return_value=""):
            with patch("topsailai.workspace.input_tool.env_tool") as mock_env:
                mock_env.is_chat_multi_line.return_value = False
                input_message(">>> ", self.mock_hook)
                mock_print.assert_any_call(SPLIT_LINE)


class TestCallHookGetMessageForTaskFromFile(unittest.TestCase):
    """Test cases for call_hook_get_message_for_task_from_file function."""

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    def test_sets_env_var_when_not_set(self):
        """Test that env var is set when not already defined."""
        from topsailai.workspace.input_tool import call_hook_get_message_for_task_from_file
        if "TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP" in os.environ:
            del os.environ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]
        call_hook_get_message_for_task_from_file()
        self.assertEqual(os.environ.get("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"), "1")

    def test_does_not_override_existing_env_var(self):
        """Test that existing env var is not overridden."""
        from topsailai.workspace.input_tool import call_hook_get_message_for_task_from_file
        os.environ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"] = "5"
        call_hook_get_message_for_task_from_file()
        self.assertEqual(os.environ.get("TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"), "5")


class TestGetMessage(unittest.TestCase):
    """Test cases for get_message function."""

    def setUp(self):
        """Set up test fixtures."""
        self.mock_hook = MagicMock()

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    @patch("topsailai.workspace.input_tool.input_message")
    @patch("topsailai.workspace.input_tool.file_tool")
    def test_no_args_no_input_returns_empty(self, mock_file_tool, mock_input_message):
        """Test that no args and no input returns empty string."""
        from topsailai.workspace.input_tool import get_message
        mock_file_tool.get_all_files.return_value = (False, [])
        mock_input_message.return_value = ""
        with patch.object(sys, 'argv', ['script.py']):
            result = get_message(self.mock_hook, need_input=True)
        self.assertEqual(result, "")

    @patch("topsailai.workspace.input_tool.input_message")
    @patch("topsailai.workspace.input_tool.file_tool")
    def test_need_input_false_returns_empty(self, mock_file_tool, mock_input_message):
        """Test that need_input=False returns empty without prompting."""
        from topsailai.workspace.input_tool import get_message
        mock_file_tool.get_all_files.return_value = (False, [])
        with patch.object(sys, 'argv', ['script.py']):
            result = get_message(self.mock_hook, need_input=False)
        self.assertEqual(result, "")
        mock_input_message.assert_not_called()

    @patch("topsailai.workspace.input_tool.call_hook_get_message_for_task_from_file")
    @patch("topsailai.workspace.input_tool.file_tool")
    def test_all_files_reads_content(self, mock_file_tool, mock_call_hook):
        """Test that all files mode reads file contents."""
        from topsailai.workspace.input_tool import get_message
        mock_file_tool.get_all_files.return_value = (True, ["/path/to/file.txt"])
        with patch("builtins.open", mock_open(read_data="file content")):
            with patch.object(sys, 'argv', ['script.py', 'file.txt']):
                result = get_message(self.mock_hook, need_input=True)
        self.assertIn("file content", result)
        mock_call_hook.assert_called_once()

    @patch("topsailai.workspace.input_tool.call_hook_get_message_for_task_from_file")
    @patch("topsailai.workspace.input_tool.file_tool")
    def test_stdin_file_reads_content(self, mock_file_tool, mock_call_hook):
        """Test that stdin file path reads from /dev/stdin."""
        from topsailai.workspace.input_tool import get_message
        mock_file_tool.get_all_files.return_value = (False, [])
        with patch("builtins.open", mock_open(read_data="stdin content")):
            with patch.object(sys, 'argv', ['script.py', '-']):
                result = get_message(self.mock_hook, need_input=True)
        self.assertIn("stdin content", result)
        mock_call_hook.assert_called_once()


class TestInputYes(unittest.TestCase):
    """Test cases for input_yes function."""

    def tearDown(self):
        """Clean up environment variables."""
        for key in ["TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP"]:
            if key in os.environ:
                del os.environ[key]

    @patch("topsailai.workspace.input_tool.input")
    def test_yes_returns_true(self, mock_input):
        """Test that 'yes' returns True."""
        from topsailai.workspace.input_tool import input_yes
        mock_input.return_value = "yes"
        result = input_yes("Continue? ")
        self.assertTrue(result)

    @patch("topsailai.workspace.input_tool.input")
    def test_yes_uppercase_returns_true(self, mock_input):
        """Test that 'YES' returns True (case-insensitive)."""
        from topsailai.workspace.input_tool import input_yes
        mock_input.return_value = "YES"
        result = input_yes("Continue? ")
        self.assertTrue(result)

    @patch("topsailai.workspace.input_tool.input")
    def test_yes_with_whitespace_returns_true(self, mock_input):
        """Test that ' yes ' returns True (whitespace stripped)."""
        from topsailai.workspace.input_tool import input_yes
        mock_input.return_value = "  yes  "
        result = input_yes("Continue? ")
        self.assertTrue(result)

    @patch("topsailai.workspace.input_tool.input")
    def test_no_returns_false(self, mock_input):
        """Test that 'no' returns False."""
        from topsailai.workspace.input_tool import input_yes
        mock_input.return_value = "no"
        result = input_yes("Continue? ")
        self.assertFalse(result)

    @patch("topsailai.workspace.input_tool.input")
    def test_other_input_returns_false(self, mock_input):
        """Test that other input returns False."""
        from topsailai.workspace.input_tool import input_yes
        mock_input.return_value = "maybe"
        result = input_yes("Continue? ")
        self.assertFalse(result)

    @patch("topsailai.workspace.input_tool.input")
    def test_default_tips(self, mock_input):
        """Test that default tips is used."""
        from topsailai.workspace.input_tool import input_yes, INPUT_TIPS
        mock_input.return_value = "yes"
        result = input_yes()
        self.assertTrue(result)
        mock_input.assert_called_once_with("Continue [yes/no] ")


if __name__ == "__main__":
    unittest.main()
