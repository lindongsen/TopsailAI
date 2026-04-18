"""
Unit tests for topsailai.prompt_hub.prompt_tool module.

Author: AI
"""

import os
import tempfile
import unittest
from unittest.mock import patch, mock_open


class TestDisableTools(unittest.TestCase):
    """Test cases for disable_tools function."""

    def test_disable_tools_empty_raw(self):
        """Empty raw_tools returns empty list."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools([], ["tool1"])
        self.assertEqual(result, [])

    def test_disable_tools_no_match(self):
        """Target tools don't match any raw_tools returns original list."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c"]
        target_tools = ["disabled_x", "disabled_y"]
        result = disable_tools(raw_tools, target_tools)
        self.assertEqual(result, raw_tools)

    def test_disable_tools_exact_match(self):
        """Exact name match removes the tool."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c"]
        target_tools = ["tool_b"]
        result = disable_tools(raw_tools, target_tools)
        self.assertEqual(result, ["tool_a", "tool_c"])

    def test_disable_tools_prefix_match(self):
        """startswith matching removes matching tools."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        raw_tools = ["agent_tool.WritingAssistant", "agent_tool.OtherTool", "cmd_tool.Execute"]
        target_tools = ["agent_tool"]
        result = disable_tools(raw_tools, target_tools)
        self.assertEqual(result, ["cmd_tool.Execute"])

    def test_disable_tools_multiple_targets(self):
        """Multiple target tools removes all matching."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c", "tool_d"]
        target_tools = ["tool_a", "tool_c"]
        result = disable_tools(raw_tools, target_tools)
        self.assertEqual(result, ["tool_b", "tool_d"])

    def test_disable_tools_empty_target(self):
        """Empty target_tools returns original list."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        raw_tools = ["tool_a", "tool_b"]
        target_tools = []
        result = disable_tools(raw_tools, target_tools)
        self.assertEqual(result, raw_tools)


class TestEnableTools(unittest.TestCase):
    """Test cases for enable_tools function."""

    def test_enable_tools_empty_raw(self):
        """Empty raw_tools returns empty list."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools([], ["tool1"])
        self.assertEqual(result, [])

    def test_enable_tools_wildcard_star(self):
        """Asterisk in target_tools returns all raw_tools."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c"]
        target_tools = ["*"]
        result = enable_tools(raw_tools, target_tools)
        self.assertEqual(result, raw_tools)

    def test_enable_tools_wildcard_plus(self):
        """Plus in target_tools returns all raw_tools."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c"]
        target_tools = ["+"]
        result = enable_tools(raw_tools, target_tools)
        self.assertEqual(result, raw_tools)

    def test_enable_tools_prefix_match(self):
        """startswith matching keeps matching tools."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        raw_tools = ["agent_tool.WritingAssistant", "agent_tool.OtherTool", "cmd_tool.Execute"]
        target_tools = ["agent_tool"]
        result = enable_tools(raw_tools, target_tools)
        # Note: returns set->list, order not preserved
        self.assertEqual(set(result), {"agent_tool.WritingAssistant", "agent_tool.OtherTool"})

    def test_enable_tools_no_match(self):
        """No matching tools returns empty list."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        raw_tools = ["tool_a", "tool_b"]
        target_tools = ["disabled_x"]
        result = enable_tools(raw_tools, target_tools)
        self.assertEqual(result, [])

    def test_enable_tools_exact_match(self):
        """Exact name match keeps the tool."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        raw_tools = ["tool_a", "tool_b", "tool_c"]
        target_tools = ["tool_b"]
        result = enable_tools(raw_tools, target_tools)
        self.assertEqual(set(result), {"tool_b"})


class TestIsOnlyPureSystemPrompt(unittest.TestCase):
    """Test cases for is_only_pure_system_prompt function."""

    @patch.dict(os.environ, {"PURE_SYSTEM_PROMPT": "1"})
    def test_is_only_pure_system_prompt_true(self):
        """Env var '1' returns True."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        result = is_only_pure_system_prompt()
        self.assertTrue(result)

    @patch.dict(os.environ, {"PURE_SYSTEM_PROMPT": "0"})
    def test_is_only_pure_system_prompt_false_zero(self):
        """Env var '0' returns False."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        result = is_only_pure_system_prompt()
        self.assertFalse(result)

    @patch.dict(os.environ, {}, clear=True)
    def test_is_only_pure_system_prompt_unset(self):
        """Unset env var returns False."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        result = is_only_pure_system_prompt()
        self.assertFalse(result)


class TestGetPromptFilePath(unittest.TestCase):
    """Test cases for get_prompt_file_path function."""

    def test_get_prompt_file_path_existing(self):
        """Path exists returns relative_path directly."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        with patch("os.path.exists", return_value=True):
            result = get_prompt_file_path("existing/path.md")
            self.assertEqual(result, "existing/path.md")

    def test_get_prompt_file_path_non_existing(self):
        """Path doesn't exist joins with dirname."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        with patch("os.path.exists", return_value=False):
            with patch("os.path.dirname", return_value="/base/dir"):
                with patch("os.path.join", return_value="/base/dir/new/path.md"):
                    result = get_prompt_file_path("new/path.md")
                    self.assertEqual(result, "/base/dir/new/path.md")


class TestExistsPromptFile(unittest.TestCase):
    """Test cases for exists_prompt_file function."""

    def test_exists_prompt_file_true(self):
        """File exists returns True."""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("os.path.exists", return_value=True):
                result = exists_prompt_file("file.md")
                self.assertTrue(result)

    def test_exists_prompt_file_false(self):
        """File doesn't exist returns False."""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("os.path.exists", return_value=False):
                result = exists_prompt_file("file.md")
                self.assertFalse(result)


class TestReadPrompt(unittest.TestCase):
    """Test cases for read_prompt function."""

    def test_read_prompt_with_content(self):
        """Reads file, strips, adds suffix."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_content = "Some prompt content"
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("builtins.open", mock_open(read_data=mock_content)):
                result = read_prompt("file.md")
                self.assertEqual(result, "Some prompt content\n---\n\n")

    def test_read_prompt_ends_with_dash(self):
        """File ending with --- adds only newline."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_content = "Some content\n---"
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("builtins.open", mock_open(read_data=mock_content)):
                result = read_prompt("file.md")
                self.assertEqual(result, "Some content\n---\n")

    def test_read_prompt_ends_with_equal(self):
        """File ending with === adds only newline."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_content = "Some content\n==="
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("builtins.open", mock_open(read_data=mock_content)):
                result = read_prompt("file.md")
                self.assertEqual(result, "Some content\n===\n")

    def test_read_prompt_empty_content(self):
        """Empty file returns empty string."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_content = ""
        with patch("topsailai.prompt_hub.prompt_tool.get_prompt_file_path", return_value="/path/to/file.md"):
            with patch("builtins.open", mock_open(read_data=mock_content)):
                result = read_prompt("file.md")
                self.assertEqual(result, "")


class TestGetPromptFromModule(unittest.TestCase):
    """Test cases for get_prompt_from_module function."""

    def test_get_prompt_from_module_success(self):
        """Module and key exist returns prompt."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        with patch("topsailai.prompt_hub.prompt_tool.__import__") as mock_import:
            mock_module = type("MockModule", (), {"PROMPT": "Test prompt content"})()
            mock_import.return_value = mock_module
            result = get_prompt_from_module("test_module", "PROMPT")
            self.assertEqual(result, "Test prompt content")

    def test_get_prompt_from_module_module_not_found(self):
        """Module not found returns empty string."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        with patch("topsailai.prompt_hub.prompt_tool.__import__", side_effect=ModuleNotFoundError):
            result = get_prompt_from_module("nonexistent_module", "PROMPT")
            self.assertEqual(result, "")

    def test_get_prompt_from_module_attribute_not_found(self):
        """Attribute not found returns empty string."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        with patch("topsailai.prompt_hub.prompt_tool.__import__") as mock_import:
            mock_module = type("MockModule", (), {})()
            mock_import.return_value = mock_module
            result = get_prompt_from_module("test_module", "NONEXISTENT_KEY")
            self.assertEqual(result, "")


if __name__ == "__main__":
    unittest.main()
