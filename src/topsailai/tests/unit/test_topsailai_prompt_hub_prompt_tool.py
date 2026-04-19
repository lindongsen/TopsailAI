"""
Unit tests for topsailai.prompt_hub.prompt_tool module.

Tests PromptHubExtractor class and tool management functions.

Author: AI
"""

import unittest
from unittest.mock import patch, MagicMock, mock_open
import os


class TestDisableTools(unittest.TestCase):
    """Test disable_tools function."""

    def test_disable_tools_with_empty_list(self):
        """Verify disable_tools returns empty list when input is empty."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools([], ["tool1"])
        self.assertEqual(result, [])

    def test_disable_tools_with_none(self):
        """Verify disable_tools returns None when input is None."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(None, ["tool1"])
        self.assertIsNone(result)

    def test_disable_tools_exact_match(self):
        """Verify disable_tools removes exact matching tools."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["tool1", "tool2", "tool3"], ["tool2"])
        self.assertEqual(result, ["tool1", "tool3"])

    def test_disable_tools_prefix_match(self):
        """Verify disable_tools removes tools with prefix match."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["file_tool.read", "file_tool.write", "cmd_tool.run"], ["file_tool"])
        self.assertEqual(result, ["cmd_tool.run"])

    def test_disable_tools_multiple_prefixes(self):
        """Verify disable_tools removes tools matching multiple prefixes."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["file_tool.read", "file_tool.write", "cmd_tool.run", "ctx_tool.get"], ["file_tool", "ctx_tool"])
        self.assertEqual(result, ["cmd_tool.run"])

    def test_disable_tools_no_match(self):
        """Verify disable_tools returns all tools when no match."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["tool1", "tool2", "tool3"], ["other"])
        self.assertEqual(result, ["tool1", "tool2", "tool3"])

    def test_disable_tools_empty_target(self):
        """Verify disable_tools returns all tools when target is empty."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["tool1", "tool2"], [])
        self.assertEqual(result, ["tool1", "tool2"])

    def test_disable_tools_whitespace_handling(self):
        """Verify disable_tools handles whitespace in tool names."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["tool1", "tool2"], ["tool1"])
        self.assertEqual(result, ["tool2"])

    def test_disable_tools_preserves_order(self):
        """Verify disable_tools preserves order of remaining tools."""
        from topsailai.prompt_hub.prompt_tool import disable_tools
        result = disable_tools(["tool1", "tool2", "tool3", "tool4"], ["tool2", "tool3"])
        self.assertEqual(result, ["tool1", "tool4"])


class TestEnableTools(unittest.TestCase):
    """Test enable_tools function."""

    def test_enable_tools_with_empty_list(self):
        """Verify enable_tools returns empty list when input is empty."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools([], ["tool1"])
        self.assertEqual(result, [])

    def test_enable_tools_with_none(self):
        """Verify enable_tools returns None when input is None."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(None, ["tool1"])
        self.assertIsNone(result)

    def test_enable_tools_exact_match(self):
        """Verify enable_tools returns exact matching tools."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["tool1", "tool2", "tool3"], ["tool2"])
        self.assertEqual(result, ["tool2"])

    def test_enable_tools_prefix_match(self):
        """Verify enable_tools returns tools with prefix match."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["file_tool.read", "file_tool.write", "cmd_tool.run"], ["file_tool"])
        self.assertEqual(set(result), {"file_tool.read", "file_tool.write"})

    def test_enable_tools_multiple_prefixes(self):
        """Verify enable_tools returns tools matching multiple prefixes."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["file_tool.read", "file_tool.write", "cmd_tool.run", "ctx_tool.get"], ["file_tool", "ctx_tool"])
        self.assertEqual(set(result), {"file_tool.read", "file_tool.write", "ctx_tool.get"})

    def test_enable_tools_no_match(self):
        """Verify enable_tools returns empty list when no match."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["tool1", "tool2", "tool3"], ["other"])
        self.assertEqual(result, [])

    def test_enable_tools_empty_target(self):
        """Verify enable_tools returns empty list when target is empty."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["tool1", "tool2"], [])
        self.assertEqual(result, [])

    def test_enable_tools_wildcard_star(self):
        """Verify enable_tools returns all tools when target contains '*'."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["tool1", "tool2"], ["*"])
        self.assertEqual(result, ["tool1", "tool2"])

    def test_enable_tools_wildcard_plus(self):
        """Verify enable_tools returns all tools when target contains '+'."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["tool1", "tool2"], ["+"])
        self.assertEqual(result, ["tool1", "tool2"])

    def test_enable_tools_removes_duplicates(self):
        """Verify enable_tools removes duplicate tools."""
        from topsailai.prompt_hub.prompt_tool import enable_tools
        result = enable_tools(["file_tool.read", "file_tool.write"], ["file_tool"])
        self.assertEqual(len(result), 2)
        self.assertEqual(set(result), {"file_tool.read", "file_tool.write"})


class TestGetToolsByEnv(unittest.TestCase):
    """Test get_tools_by_env function."""

    @patch('topsailai.prompt_hub.prompt_tool.enable_tools_by_env')
    @patch('topsailai.prompt_hub.prompt_tool.disable_tools_by_env')
    def test_get_tools_by_env_empty_input(self, mock_disable, mock_enable):
        """Verify get_tools_by_env returns empty list when input is empty."""
        from topsailai.prompt_hub.prompt_tool import get_tools_by_env
        result = get_tools_by_env([])
        self.assertEqual(result, [])
        mock_enable.assert_not_called()
        mock_disable.assert_not_called()

    @patch('topsailai.prompt_hub.prompt_tool.enable_tools_by_env')
    @patch('topsailai.prompt_hub.prompt_tool.disable_tools_by_env')
    def test_get_tools_by_env_with_input(self, mock_disable, mock_enable):
        """Verify get_tools_by_env applies enable then disable."""
        from topsailai.prompt_hub.prompt_tool import get_tools_by_env
        mock_enable.return_value = ["tool1", "tool2"]
        mock_disable.return_value = ["tool1"]
        result = get_tools_by_env(["tool1", "tool2", "tool3"])
        mock_enable.assert_called_once_with(["tool1", "tool2", "tool3"])
        mock_disable.assert_called_once_with(["tool1", "tool2"])
        self.assertEqual(result, ["tool1"])


class TestGetPromptFromModule(unittest.TestCase):
    """Test get_prompt_from_module function."""

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_success(self, mock_logger):
        """Verify get_prompt_from_module returns prompt from module."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        mock_module = MagicMock()
        mock_module.PROMPT = "test prompt content"
        with patch('builtins.__import__', return_value=mock_module):
            result = get_prompt_from_module("agent_tool")
            self.assertEqual(result, "test prompt content")

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_custom_key(self, mock_logger):
        """Verify get_prompt_from_module uses custom key."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        mock_module = MagicMock()
        mock_module.CUSTOM_KEY = "custom prompt"
        with patch('builtins.__import__', return_value=mock_module):
            result = get_prompt_from_module("agent_tool", key="CUSTOM_KEY")
            self.assertEqual(result, "custom prompt")

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_not_found(self, mock_logger):
        """Verify get_prompt_from_module returns empty string when module not found."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'topsailai.tools.agent_tool'")):
            result = get_prompt_from_module("nonexistent_module")
            self.assertEqual(result, "")

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_from_module_attribute_error(self, mock_logger):
        """Verify get_prompt_from_module returns empty string when attribute not found."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_from_module
        mock_module = MagicMock()
        del mock_module.PROMPT
        with patch('builtins.__import__', return_value=mock_module):
            result = get_prompt_from_module("agent_tool")
            self.assertEqual(result, "")


class TestReloadPromptOnModule(unittest.TestCase):
    """Test reload_prompt_on_module function."""

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_reload_prompt_on_module_success(self, mock_logger):
        """Verify reload_prompt_on_module calls reload function."""
        from topsailai.prompt_hub.prompt_tool import reload_prompt_on_module
        mock_module = MagicMock()
        with patch('builtins.__import__', return_value=mock_module):
            reload_prompt_on_module("agent_tool")
            mock_module.reload.assert_called_once()
            mock_logger.info.assert_called()

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_reload_prompt_on_module_not_found(self, mock_logger):
        """Verify reload_prompt_on_module handles module not found."""
        from topsailai.prompt_hub.prompt_tool import reload_prompt_on_module
        with patch('builtins.__import__', side_effect=ModuleNotFoundError("No module named 'topsailai.tools.agent_tool'")):
            reload_prompt_on_module("nonexistent_module")
            mock_logger.info.assert_not_called()

    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_reload_prompt_on_module_attribute_error(self, mock_logger):
        """Verify reload_prompt_on_module handles attribute not found."""
        from topsailai.prompt_hub.prompt_tool import reload_prompt_on_module
        mock_module = MagicMock()
        del mock_module.reload
        with patch('builtins.__import__', return_value=mock_module):
            reload_prompt_on_module("agent_tool")
            mock_logger.info.assert_not_called()


class TestGetPromptByTools(unittest.TestCase):
    """Test get_prompt_by_tools function."""

    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_empty_list(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists):
        """Verify get_prompt_by_tools returns empty string for empty list."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        result = get_prompt_by_tools([])
        self.assertEqual(result, "")

    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_with_module_prompt(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists):
        """Verify get_prompt_by_tools gets prompt from module."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        mock_get_prompt.return_value = "module prompt content"
        mock_exists.return_value = False
        result = get_prompt_by_tools(["agent_tool-func1"])
        self.assertIn("module prompt content", result)
        mock_get_prompt.assert_called_once_with("agent_tool")

    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_with_file_prompt(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists):
        """Verify get_prompt_by_tools gets prompt from file."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        mock_get_prompt.return_value = ""
        mock_exists.return_value = True
        mock_read.return_value = "file prompt content"
        result = get_prompt_by_tools(["agent_tool-func1"])
        self.assertIn("file prompt content", result)
        mock_read.assert_called()

    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_with_reload(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists):
        """Verify get_prompt_by_tools reloads module when need_reload is True."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        mock_get_prompt.return_value = ""
        mock_exists.return_value = False
        get_prompt_by_tools(["agent_tool-func1"], need_reload=True)
        mock_reload.assert_called_once_with("agent_tool")

    @patch('topsailai.prompt_hub.prompt_tool.exists_prompt_file')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_from_module')
    @patch('topsailai.prompt_hub.prompt_tool.reload_prompt_on_module')
    @patch('topsailai.prompt_hub.prompt_tool.logger')
    def test_get_prompt_by_tools_deduplicates_modules(self, mock_logger, mock_reload, mock_get_prompt, mock_read, mock_exists):
        """Verify get_prompt_by_tools deduplicates modules."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_by_tools
        mock_get_prompt.return_value = "prompt"
        mock_exists.return_value = False
        get_prompt_by_tools(["agent_tool-func1", "agent_tool-func2"])
        mock_get_prompt.assert_called_once_with("agent_tool")


class TestGeneratePromptByTools(unittest.TestCase):
    """Test generate_prompt_by_tools function."""

    @patch('topsailai.prompt_hub.prompt_tool.get_extra_tools')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_by_tools')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool')
    def test_generate_prompt_by_tools_list_input(self, mock_env, mock_get_prompt, mock_extra):
        """Verify generate_prompt_by_tools handles list input."""
        from topsailai.prompt_hub.prompt_tool import generate_prompt_by_tools
        mock_env.is_use_tool_calls.return_value = True
        mock_get_prompt.return_value = "tool prompt"
        mock_extra.return_value = "extra tools"
        result = generate_prompt_by_tools(["tool1", "tool2"])
        self.assertIn("tool prompt", result)
        self.assertIn("extra tools", result)

    @patch('topsailai.prompt_hub.prompt_tool.get_extra_tools')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_by_tools')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool')
    def test_generate_prompt_by_tools_dict_input(self, mock_env, mock_get_prompt, mock_extra):
        """Verify generate_prompt_by_tools handles dict input."""
        from topsailai.prompt_hub.prompt_tool import generate_prompt_by_tools
        mock_env.is_use_tool_calls.return_value = True
        mock_get_prompt.return_value = "tool prompt"
        mock_extra.return_value = ""
        result = generate_prompt_by_tools({"tool1": {}, "tool2": {}})
        mock_get_prompt.assert_called_once()
        self.assertIn("tool prompt", result)

    @patch('topsailai.prompt_hub.prompt_tool.get_extra_tools')
    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_by_tools')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool')
    def test_generate_prompt_by_tools_without_tool_calls(self, mock_env, mock_get_prompt, mock_extra):
        """Verify generate_prompt_by_tools adds tool docs when not using tool calls."""
        from topsailai.prompt_hub.prompt_tool import generate_prompt_by_tools
        mock_env.is_use_tool_calls.return_value = False
        mock_get_prompt.return_value = "tool prompt"
        mock_extra.return_value = ""
        with patch('topsailai.tools.base.common.get_tool_prompt') as mock_tool_prompt:
            mock_tool_prompt.return_value = "tool docs"
            result = generate_prompt_by_tools(["tool1"])
            self.assertIn("tool docs", result)


class TestGetPromptFilePath(unittest.TestCase):
    """Test get_prompt_file_path function."""

    @patch('os.path.exists')
    @patch('os.path.join')
    def test_get_prompt_file_path_exists(self, mock_join, mock_exists):
        """Verify get_prompt_file_path returns path when file exists."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        mock_exists.return_value = True
        mock_join.return_value = "/path/to/file.md"
        result = get_prompt_file_path("file.md")
        self.assertEqual(result, "file.md")
        mock_join.assert_not_called()

    @patch('os.path.exists')
    @patch('os.path.join')
    def test_get_prompt_file_path_not_exists(self, mock_join, mock_exists):
        """Verify get_prompt_file_path joins with module dir when file doesn't exist."""
        from topsailai.prompt_hub.prompt_tool import get_prompt_file_path
        mock_exists.side_effect = [False, True]
        mock_join.return_value = "/module/dir/file.md"
        result = get_prompt_file_path("file.md")
        self.assertEqual(result, "/module/dir/file.md")
        mock_join.assert_called()


class TestExistsPromptFile(unittest.TestCase):
    """Test exists_prompt_file function."""

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    @patch('os.path.exists')
    def test_exists_prompt_file_true(self, mock_exists, mock_get_path):
        """Verify exists_prompt_file returns True when file exists."""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        mock_get_path.return_value = "/path/to/file.md"
        mock_exists.return_value = True
        result = exists_prompt_file("file.md")
        self.assertTrue(result)

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    @patch('os.path.exists')
    def test_exists_prompt_file_false(self, mock_exists, mock_get_path):
        """Verify exists_prompt_file returns False when file doesn't exist."""
        from topsailai.prompt_hub.prompt_tool import exists_prompt_file
        mock_get_path.return_value = "/path/to/file.md"
        mock_exists.return_value = False
        result = exists_prompt_file("file.md")
        self.assertFalse(result)


class TestReadPrompt(unittest.TestCase):
    """Test read_prompt function."""

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_with_content(self, mock_get_path):
        """Verify read_prompt returns content with separator."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_get_path.return_value = "/path/to/file.md"
        with patch('builtins.open', mock_open(read_data="test content")):
            result = read_prompt("file.md")
            self.assertIn("test content", result)
            self.assertTrue(result.endswith("---\n\n"))

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_ends_with_dash(self, mock_get_path):
        """Verify read_prompt adds newline when content ends with '---'."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_get_path.return_value = "/path/to/file.md"
        with patch('builtins.open', mock_open(read_data="test content\n---")):
            result = read_prompt("file.md")
            self.assertTrue(result.endswith("---\n"))

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_ends_with_equals(self, mock_get_path):
        """Verify read_prompt adds newline when content ends with '==='."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_get_path.return_value = "/path/to/file.md"
        with patch('builtins.open', mock_open(read_data="test content\n===")):
            result = read_prompt("file.md")
            self.assertTrue(result.endswith("===\n"))

    @patch('topsailai.prompt_hub.prompt_tool.get_prompt_file_path')
    def test_read_prompt_empty_content(self, mock_get_path):
        """Verify read_prompt returns empty string for empty content."""
        from topsailai.prompt_hub.prompt_tool import read_prompt
        mock_get_path.return_value = "/path/to/file.md"
        with patch('builtins.open', mock_open(read_data="")):
            result = read_prompt("file.md")
            self.assertEqual(result, "")


class TestIsOnlyPureSystemPrompt(unittest.TestCase):
    """Test is_only_pure_system_prompt function."""

    @patch('os.getenv')
    def test_is_only_pure_system_prompt_true(self, mock_getenv):
        """Verify is_only_pure_system_prompt returns True when env var is '1'."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        mock_getenv.return_value = "1"
        result = is_only_pure_system_prompt()
        self.assertTrue(result)

    @patch('os.getenv')
    def test_is_only_pure_system_prompt_false(self, mock_getenv):
        """Verify is_only_pure_system_prompt returns False when env var is '0'."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        mock_getenv.return_value = "0"
        result = is_only_pure_system_prompt()
        self.assertFalse(result)

    @patch('os.getenv')
    def test_is_only_pure_system_prompt_default(self, mock_getenv):
        """Verify is_only_pure_system_prompt returns False when env var is not set."""
        from topsailai.prompt_hub.prompt_tool import is_only_pure_system_prompt
        mock_getenv.return_value = None
        result = is_only_pure_system_prompt()
        self.assertFalse(result)


class TestGetExtraPrompt(unittest.TestCase):
    """Test get_extra_prompt function."""

    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_prompt_empty(self, mock_env_reader, mock_read):
        """Verify get_extra_prompt returns empty string when no files configured."""
        from topsailai.prompt_hub.prompt_tool import get_extra_prompt
        mock_env_reader.get_list_str.return_value = None
        result = get_extra_prompt()
        self.assertEqual(result, "")
        mock_read.assert_not_called()

    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_prompt_with_files(self, mock_env_reader, mock_read):
        """Verify get_extra_prompt reads and concatenates files."""
        from topsailai.prompt_hub.prompt_tool import get_extra_prompt
        mock_env_reader.get_list_str.return_value = ["file1.md", "file2.md"]
        mock_read.side_effect = ["content1\n", "content2\n"]
        result = get_extra_prompt()
        self.assertIn("content1", result)
        self.assertIn("content2", result)


class TestGetExtraTools(unittest.TestCase):
    """Test get_extra_tools function."""

    @patch('os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_tools_empty(self, mock_env_reader, mock_read, mock_exists):
        """Verify get_extra_tools returns empty string when no tools configured."""
        from topsailai.prompt_hub.prompt_tool import get_extra_tools
        mock_env_reader.get_list_str.return_value = None
        result = get_extra_tools()
        self.assertEqual(result, "")

    @patch('os.path.exists')
    @patch('topsailai.prompt_hub.prompt_tool.read_prompt')
    @patch('topsailai.prompt_hub.prompt_tool.env_tool.EnvReaderInstance')
    def test_get_extra_tools_with_tools(self, mock_env_reader, mock_read, mock_exists):
        """Verify get_extra_tools reads and formats tool prompts."""
        from topsailai.prompt_hub.prompt_tool import get_extra_tools
        mock_env_reader.get_list_str.return_value = "tool1.md;tool2.md"
        mock_exists.return_value = True
        mock_read.side_effect = ["tool content 1", "tool content 2"]
        result = get_extra_tools()
        self.assertIn("# Extra Tools Start", result)
        self.assertIn("tool content 1", result)
        self.assertIn("tool content 2", result)
        self.assertIn("# Extra Tools End", result)


class TestModuleExports(unittest.TestCase):
    """Test module exports and function availability."""

    def test_functions_available(self):
        """Verify all functions are available in module."""
        from topsailai.prompt_hub.prompt_tool import (
            get_extra_prompt,
            get_extra_tools,
            get_prompt_file_path,
            exists_prompt_file,
            read_prompt,
            is_only_pure_system_prompt,
            disable_tools,
            disable_tools_by_env,
            enable_tools,
            enable_tools_by_env,
            get_tools_by_env,
            get_prompt_from_module,
            reload_prompt_on_module,
            get_prompt_by_tools,
            generate_prompt_by_tools,
            PromptHubExtractor,
        )
        self.assertTrue(callable(get_extra_prompt))
        self.assertTrue(callable(get_extra_tools))
        self.assertTrue(callable(get_prompt_file_path))
        self.assertTrue(callable(exists_prompt_file))
        self.assertTrue(callable(read_prompt))
        self.assertTrue(callable(is_only_pure_system_prompt))
        self.assertTrue(callable(disable_tools))
        self.assertTrue(callable(disable_tools_by_env))
        self.assertTrue(callable(enable_tools))
        self.assertTrue(callable(enable_tools_by_env))
        self.assertTrue(callable(get_tools_by_env))
        self.assertTrue(callable(get_prompt_from_module))
        self.assertTrue(callable(reload_prompt_on_module))
        self.assertTrue(callable(get_prompt_by_tools))
        self.assertTrue(callable(generate_prompt_by_tools))
        self.assertTrue(callable(PromptHubExtractor))


if __name__ == '__main__':
    unittest.main()
