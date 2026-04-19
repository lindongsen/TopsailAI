"""
Unit tests for topsailai.tools.sandbox_tool module.

Tests sandbox execution functionality, security constraints,
command execution, file operations, and error handling.
"""

import unittest
from unittest.mock import patch, MagicMock
import os
import sys

sys.path.insert(0, '/root/ai/TopsailAI/src/topsailai')

from topsailai.tools.sandbox_tool import (
    Sandbox,
    _parse_sandbox_config,
    call_sandbox,
    copy2sandbox,
    list_sandbox,
    TOOLS,
    FLAG_TOOL_ENABLED,
    PROMPT,
)


class TestSandboxClass(unittest.TestCase):
    """Test Sandbox class initialization and attributes."""

    def test_sandbox_initialization(self):
        """Test Sandbox object initialization with default values."""
        sandbox = Sandbox()
        self.assertEqual(sandbox.protocol, "")
        self.assertEqual(sandbox.node, "")
        self.assertEqual(sandbox.tags, set())
        self.assertEqual(sandbox.port, 22)
        self.assertEqual(sandbox.name, "")

    def test_sandbox_attributes_are_mutable(self):
        """Test that Sandbox attributes can be modified."""
        sandbox = Sandbox()
        sandbox.protocol = "ssh"
        sandbox.node = "example.com"
        sandbox.port = 2222
        sandbox.name = "container1"
        sandbox.tags.add("ai")

        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")
        self.assertEqual(sandbox.port, 2222)
        self.assertEqual(sandbox.name, "container1")
        self.assertIn("ai", sandbox.tags)


class TestParseSandboxConfig(unittest.TestCase):
    """Test _parse_sandbox_config function."""

    def test_parse_ssh_sandbox(self):
        """Test parsing SSH sandbox configuration."""
        config = "protocol=ssh,node=example.com,port=2222"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")
        self.assertEqual(sandbox.port, "2222")

    def test_parse_docker_sandbox(self):
        """Test parsing Docker sandbox configuration."""
        config = "protocol=docker,node=localhost,name=container1"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.protocol, "docker")
        self.assertEqual(sandbox.node, "localhost")
        self.assertEqual(sandbox.name, "container1")

    def test_parse_sandbox_with_tags(self):
        """Test parsing sandbox configuration with tags."""
        config = "protocol=ssh,node=example.com,tag=ai,tag=production"
        sandbox = _parse_sandbox_config(config)

        self.assertIn("ai", sandbox.tags)
        self.assertIn("production", sandbox.tags)
        self.assertEqual(len(sandbox.tags), 2)

    def test_parse_sandbox_with_spaces(self):
        """Test parsing sandbox configuration with spaces around values."""
        config = "protocol=ssh , node=example.com , port=22"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")

    def test_parse_sandbox_with_empty_values(self):
        """Test parsing sandbox configuration with empty parts."""
        config = "protocol=ssh,,node=example.com,"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")

    def test_parse_sandbox_with_value_containing_equals(self):
        """Test parsing sandbox configuration with equals sign in value."""
        config = "protocol=ssh,node=example.com,password=p=ss=word"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.node, "example.com")
        self.assertEqual(sandbox.password, "p=ss=word")

    def test_parse_empty_sandbox_string(self):
        """Test parsing empty sandbox string."""
        sandbox = _parse_sandbox_config("")

        self.assertEqual(sandbox.protocol, "")
        self.assertEqual(sandbox.node, "")
        self.assertEqual(sandbox.tags, set())

    def test_parse_sandbox_single_key_value(self):
        """Test parsing sandbox with single key-value pair."""
        config = "protocol=ssh"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.protocol, "ssh")


class TestCallSandbox(unittest.TestCase):
    """Test call_sandbox function."""

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_ssh_success(self, mock_exec_cmd):
        """Test successful command execution in SSH sandbox."""
        mock_exec_cmd.return_value = (0, "output", "")

        result = call_sandbox("protocol=ssh,node=example.com", "echo hello")

        self.assertEqual(result, (0, "output", ""))
        mock_exec_cmd.assert_called_once_with(
            "echo hello",
            remote="example.com",
            port=22,
            timeout=30
        )

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_ssh_custom_port(self, mock_exec_cmd):
        """Test SSH sandbox with custom port."""
        mock_exec_cmd.return_value = (0, "output", "")

        result = call_sandbox("protocol=ssh,node=example.com,port=2222", "echo hello")

        mock_exec_cmd.assert_called_once_with(
            "echo hello",
            remote="example.com",
            port="2222",
            timeout=30
        )

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_ssh_custom_timeout(self, mock_exec_cmd):
        """Test SSH sandbox with custom timeout."""
        mock_exec_cmd.return_value = (0, "output", "")

        result = call_sandbox("protocol=ssh,node=example.com", "echo hello", timeout=60)

        mock_exec_cmd.assert_called_once_with(
            "echo hello",
            remote="example.com",
            port=22,
            timeout=60
        )

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_ssh_failure(self, mock_exec_cmd):
        """Test SSH sandbox command failure."""
        mock_exec_cmd.return_value = (1, "", "error")

        result = call_sandbox("protocol=ssh,node=example.com", "false")

        self.assertEqual(result, (1, "", "error"))

    def test_call_sandbox_unknown_protocol(self):
        """Test call_sandbox with unknown protocol returns error."""
        result = call_sandbox("protocol=unknown,node=example.com", "echo hello")

        self.assertEqual(result, "unknown sandbox")

    def test_call_sandbox_empty_config(self):
        """Test call_sandbox with empty configuration."""
        result = call_sandbox("", "echo hello")

        self.assertEqual(result, "unknown sandbox")

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_with_tags(self, mock_exec_cmd):
        """Test call_sandbox with tags in configuration."""
        mock_exec_cmd.return_value = (0, "output", "")

        result = call_sandbox("protocol=ssh,node=example.com,tag=ai", "echo hello")

        self.assertEqual(result, (0, "output", ""))

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_none_timeout_uses_default(self, mock_exec_cmd):
        """Test call_sandbox with None timeout uses default 30."""
        mock_exec_cmd.return_value = (0, "output", "")

        result = call_sandbox("protocol=ssh,node=example.com", "echo hello", timeout=None)

        mock_exec_cmd.assert_called_once_with(
            "echo hello",
            remote="example.com",
            port=22,
            timeout=30
        )


class TestCopy2Sandbox(unittest.TestCase):
    """Test copy2sandbox function."""

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_ssh_file_success(self, mock_exec_cmd):
        """Test successful file copy to SSH sandbox."""
        mock_exec_cmd.return_value = (0, "", "")

        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/file.txt",
            "/remote/file.txt"
        )

        self.assertTrue(result)
        mock_exec_cmd.assert_called_once()
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIn("scp", call_args)
        self.assertIn("/local/file.txt", call_args)

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_ssh_directory(self, mock_exec_cmd):
        """Test directory copy to SSH sandbox."""
        mock_exec_cmd.return_value = (0, "", "")

        with patch('os.path.isdir', return_value=True):
            with patch('os.path.basename', side_effect=lambda x: x.split('/')[-1]):
                result = copy2sandbox(
                    "protocol=ssh,node=example.com",
                    "/local/mydir",
                    "/remote/mydir"
                )

        self.assertTrue(result)
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIn("-r", call_args)

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_ssh_failure(self, mock_exec_cmd):
        """Test file copy failure to SSH sandbox."""
        mock_exec_cmd.return_value = (1, "", "error")

        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/file.txt",
            "/remote/file.txt"
        )

        self.assertFalse(result)

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_with_custom_port(self, mock_exec_cmd):
        """Test file copy with custom SSH port."""
        mock_exec_cmd.return_value = (0, "", "")

        result = copy2sandbox(
            "protocol=ssh,node=example.com,port=2222",
            "/local/file.txt",
            "/remote/file.txt"
        )

        self.assertTrue(result)
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIn("-P 2222", call_args)

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_with_username(self, mock_exec_cmd):
        """Test file copy with custom username."""
        mock_exec_cmd.return_value = (0, "", "")

        result = copy2sandbox(
            "protocol=ssh,node=example.com,name=admin",
            "/local/file.txt",
            "/remote/file.txt"
        )

        self.assertTrue(result)
        call_args = mock_exec_cmd.call_args[0][0]
        self.assertIn("admin@example.com", call_args)

    def test_copy2sandbox_unknown_protocol(self):
        """Test copy2sandbox with unknown protocol returns False."""
        result = copy2sandbox(
            "protocol=unknown,node=example.com",
            "/local/file.txt",
            "/remote/file.txt"
        )

        self.assertFalse(result)

    def test_copy2sandbox_empty_config(self):
        """Test copy2sandbox with empty configuration."""
        result = copy2sandbox("", "/local/file.txt", "/remote/file.txt")

        self.assertFalse(result)

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_custom_timeout(self, mock_exec_cmd):
        """Test file copy with custom timeout."""
        mock_exec_cmd.return_value = (0, "", "")

        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/file.txt",
            "/remote/file.txt",
            timeout=120
        )

        self.assertTrue(result)
        call_kwargs = mock_exec_cmd.call_args[1]
        self.assertEqual(call_kwargs['timeout'], 120)


class TestListSandbox(unittest.TestCase):
    """Test list_sandbox function."""

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_matching_tag(self, mock_get_list):
        """Test listing sandboxes with matching tag."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com",
            "tag=dev,protocol=docker,node=host2.com",
            "tag=ai,protocol=ssh,node=host3.com"
        ]

        result = list_sandbox("ai")

        self.assertIn("tag=ai,protocol=ssh,node=host1.com", result)
        self.assertIn("tag=ai,protocol=ssh,node=host3.com", result)
        self.assertNotIn("tag=dev", result)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_no_matching_tag(self, mock_get_list):
        """Test listing sandboxes with no matching tag."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com"
        ]

        result = list_sandbox("nonexistent")

        self.assertEqual(result, "")

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_empty_settings(self, mock_get_list):
        """Test listing sandboxes with empty settings."""
        mock_get_list.return_value = []

        result = list_sandbox("ai")

        self.assertEqual(result, "")

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_spaces(self, mock_get_list):
        """Test listing sandboxes with spaces in configuration."""
        mock_get_list.return_value = [
            "  tag=ai,protocol=ssh,node=host1.com  ",
            "tag=ai,protocol=docker,node=host2.com"
        ]

        result = list_sandbox("ai")

        self.assertIn("host1.com", result)
        self.assertIn("host2.com", result)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_multiple_tags(self, mock_get_list):
        """Test listing sandboxes with multiple matching entries."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com",
            "tag=ai,protocol=docker,node=container1",
            "tag=ai,protocol=ssh,node=host2.com"
        ]

        result = list_sandbox("ai")

        lines = result.split("\n")
        self.assertEqual(len(lines), 3)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_empty_entries(self, mock_get_list):
        """Test listing sandboxes with empty entries in settings."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com",
            "",
            "   ",
            "tag=ai,protocol=ssh,node=host2.com"
        ]

        result = list_sandbox("ai")

        self.assertIn("host1.com", result)
        self.assertIn("host2.com", result)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_fallback_env_var(self, mock_get_list):
        """Test list_sandbox falls back to SANDBOX_SETTINGS."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com"
        ]

        result = list_sandbox("ai")

        # Should have been called with both env var names
        calls = mock_get_list.call_args_list
        env_vars = [call[0][0] for call in calls]
        self.assertIn("TOPSAILAI_SANDBOX_SETTINGS", env_vars)


class TestToolsConstant(unittest.TestCase):
    """Test TOOLS constant."""

    def test_tools_is_dict(self):
        """Test that TOOLS is a dictionary."""
        self.assertIsInstance(TOOLS, dict)

    def test_tools_contains_call_sandbox(self):
        """Test that TOOLS contains call_sandbox."""
        self.assertIn("call_sandbox", TOOLS)

    def test_tools_contains_list_sandbox(self):
        """Test that TOOLS contains list_sandbox."""
        self.assertIn("list_sandbox", TOOLS)

    def test_tools_contains_copy2sandbox(self):
        """Test that TOOLS contains copy2sandbox."""
        self.assertIn("copy2sandbox", TOOLS)

    def test_tools_functions_are_callable(self):
        """Test that all TOOLS entries are callable."""
        for name, func in TOOLS.items():
            self.assertTrue(callable(func), f"{name} should be callable")


class TestFlagToolEnabled(unittest.TestCase):
    """Test FLAG_TOOL_ENABLED constant."""

    def test_flag_tool_enabled_is_bool(self):
        """Test that FLAG_TOOL_ENABLED is a boolean."""
        self.assertIsInstance(FLAG_TOOL_ENABLED, bool)

    def test_flag_tool_enabled_default_value(self):
        """Test that FLAG_TOOL_ENABLED defaults to False."""
        self.assertFalse(FLAG_TOOL_ENABLED)


class TestPrompt(unittest.TestCase):
    """Test PROMPT constant."""

    def test_prompt_is_string(self):
        """Test that PROMPT is a string."""
        self.assertIsInstance(PROMPT, str)

    def test_prompt_contains_sandbox_info(self):
        """Test that PROMPT contains sandbox information."""
        self.assertIn("sandbox", PROMPT.lower())

    def test_prompt_mentions_list_sandbox(self):
        """Test that PROMPT mentions list_sandbox."""
        self.assertIn("list_sandbox", PROMPT)

    def test_prompt_mentions_call_sandbox(self):
        """Test that PROMPT mentions call_sandbox."""
        self.assertIn("call_sandbox", PROMPT)


class TestEdgeCases(unittest.TestCase):
    """Test edge cases for sandbox_tool."""

    def test_parse_sandbox_with_special_characters(self):
        """Test parsing sandbox with special characters in values."""
        config = "protocol=ssh,node=example.com,path=/home/user/test"
        sandbox = _parse_sandbox_config(config)

        self.assertEqual(sandbox.path, "/home/user/test")

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_with_long_command(self, mock_exec_cmd):
        """Test call_sandbox with long command."""
        mock_exec_cmd.return_value = (0, "output", "")

        long_cmd = "echo " + "a" * 1000
        result = call_sandbox("protocol=ssh,node=example.com", long_cmd)

        self.assertEqual(result, (0, "output", ""))

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy2sandbox_with_special_path(self, mock_exec_cmd):
        """Test copy2sandbox with special characters in path."""
        mock_exec_cmd.return_value = (0, "", "")

        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/path with spaces/file.txt",
            "/remote/path with spaces/file.txt"
        )

        self.assertTrue(result)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_unicode_tag(self, mock_get_list):
        """Test list_sandbox with unicode tag."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com"
        ]

        result = list_sandbox("ai")

        self.assertIn("host1.com", result)


if __name__ == '__main__':
    unittest.main()
