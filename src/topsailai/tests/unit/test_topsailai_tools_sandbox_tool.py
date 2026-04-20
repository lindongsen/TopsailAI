"""
Unit tests for tools/sandbox_tool.py

Author: DawsonLin
Test Developer: mm-m25
Reviewer: km-k25

Covers:
- Sandbox class initialization and attributes
- _parse_sandbox_config() function
- call_sandbox() function
- copy2sandbox() function
- list_sandbox() function
"""

import os
from unittest import TestCase
from unittest.mock import patch, MagicMock, mock_open

from topsailai.tools.sandbox_tool import (
    Sandbox,
    _parse_sandbox_config,
    call_sandbox,
    copy2sandbox,
    list_sandbox,
)


class TestSandboxClass(TestCase):
    """Test cases for Sandbox class initialization and attributes."""

    def test_init_default_values(self):
        """Verify Sandbox initializes with correct default values."""
        sandbox = Sandbox()
        self.assertEqual(sandbox.protocol, "")
        self.assertEqual(sandbox.node, "")
        self.assertEqual(sandbox.port, 22)
        self.assertEqual(sandbox.name, "")
        self.assertEqual(sandbox.tags, set())

    def test_protocol_attribute_can_be_set(self):
        """Protocol attribute can be set after initialization."""
        sandbox = Sandbox()
        sandbox.protocol = "ssh"
        self.assertEqual(sandbox.protocol, "ssh")

    def test_node_attribute_can_be_set(self):
        """Node attribute can be set after initialization."""
        sandbox = Sandbox()
        sandbox.node = "example.com"
        self.assertEqual(sandbox.node, "example.com")

    def test_tags_is_set_type(self):
        """Tags attribute is initialized as an empty set."""
        sandbox = Sandbox()
        self.assertIsInstance(sandbox.tags, set)
        self.assertEqual(len(sandbox.tags), 0)

    def test_port_default_22(self):
        """Default SSH port is 22."""
        sandbox = Sandbox()
        self.assertEqual(sandbox.port, 22)

    def test_name_attribute_can_be_set(self):
        """Name attribute can be set for Docker containers."""
        sandbox = Sandbox()
        sandbox.name = "my_container"
        self.assertEqual(sandbox.name, "my_container")


class TestParseSandboxConfig(TestCase):
    """Test cases for _parse_sandbox_config() function."""

    def test_parse_empty_string(self):
        """Handle empty config string gracefully."""
        sandbox = _parse_sandbox_config("")
        self.assertIsInstance(sandbox, Sandbox)
        self.assertEqual(sandbox.protocol, "")
        self.assertEqual(sandbox.node, "")

    def test_parse_protocol_ssh(self):
        """Parse SSH protocol from config string."""
        sandbox = _parse_sandbox_config("protocol=ssh,node=example.com")
        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")

    def test_parse_protocol_docker(self):
        """Parse Docker protocol from config string."""
        sandbox = _parse_sandbox_config("protocol=docker,node=container1,name=my_container")
        self.assertEqual(sandbox.protocol, "docker")
        self.assertEqual(sandbox.node, "container1")
        self.assertEqual(sandbox.name, "my_container")

    def test_parse_multiple_tags(self):
        """Handle multiple tag entries in config."""
        sandbox = _parse_sandbox_config("tag=ai,tag=dev,tag=test")
        self.assertEqual(len(sandbox.tags), 3)
        self.assertIn("ai", sandbox.tags)
        self.assertIn("dev", sandbox.tags)
        self.assertIn("test", sandbox.tags)

    def test_parse_port_override(self):
        """Override default port from config."""
        sandbox = _parse_sandbox_config("protocol=ssh,node=example.com,port=2222")
        self.assertEqual(sandbox.port, "2222")

    def test_parse_with_whitespace(self):
        """Handle whitespace in config string."""
        sandbox = _parse_sandbox_config("  protocol=ssh  ,  node=example.com  ")
        self.assertEqual(sandbox.protocol, "ssh")
        self.assertEqual(sandbox.node, "example.com")

    def test_parse_missing_equals(self):
        """Handle malformed config gracefully."""
        sandbox = _parse_sandbox_config("protocol=ssh,invalid_entry")
        self.assertEqual(sandbox.protocol, "ssh")

    def test_parse_single_tag(self):
        """Parse single tag entry."""
        sandbox = _parse_sandbox_config("tag=production")
        self.assertEqual(len(sandbox.tags), 1)
        self.assertIn("production", sandbox.tags)


class TestCallSandbox(TestCase):
    """Test cases for call_sandbox() function."""

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_call_sandbox_ssh_protocol(self, mock_parse):
        """Execute command via SSH protocol."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_parse.return_value = mock_sandbox

        with patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote') as mock_exec:
            mock_exec.return_value = "command output"
            with patch('topsailai.tools.sandbox_tool.format_return') as mock_format:
                mock_format.return_value = "formatted output"
                result = call_sandbox("protocol=ssh,node=example.com", "ls -la")
                mock_exec.assert_called_once()
                mock_format.assert_called_once()

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_call_sandbox_unknown_protocol(self, mock_parse):
        """Return 'unknown sandbox' for unknown protocol."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "unknown"
        mock_sandbox.node = "example.com"
        mock_parse.return_value = mock_sandbox

        result = call_sandbox("protocol=unknown,node=example.com", "ls -la")
        self.assertEqual(result, "unknown sandbox")

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_call_sandbox_with_timeout(self, mock_parse):
        """Pass timeout parameter to exec_cmd_in_remote."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_parse.return_value = mock_sandbox

        with patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote') as mock_exec:
            mock_exec.return_value = "output"
            with patch('topsailai.tools.sandbox_tool.format_return'):
                call_sandbox("protocol=ssh,node=example.com", "ls -la", timeout=60)
                mock_exec.assert_called_once()
                call_kwargs = mock_exec.call_args
                self.assertEqual(call_kwargs[1]['timeout'], 60)

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_call_sandbox_none_result(self, mock_parse):
        """Handle None result from exec_cmd_in_remote."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_parse.return_value = mock_sandbox

        with patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote') as mock_exec:
            mock_exec.return_value = None
            result = call_sandbox("protocol=ssh,node=example.com", "ls -la")
            self.assertEqual(result, "unknown sandbox")

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_call_sandbox_empty_result(self, mock_parse):
        """Handle empty result from exec_cmd_in_remote."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_parse.return_value = mock_sandbox

        with patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote') as mock_exec:
            mock_exec.return_value = ""
            result = call_sandbox("protocol=ssh,node=example.com", "ls -la")
            self.assertEqual(result, "unknown sandbox")


class TestCopy2Sandbox(TestCase):
    """Test cases for copy2sandbox() function."""

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    @patch('topsailai.tools.sandbox_tool.os.path.isdir')
    def test_copy2sandbox_ssh_file(self, mock_isdir, mock_parse):
        """Copy file via SSH protocol."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_sandbox.name = "root"
        mock_parse.return_value = mock_sandbox
        mock_isdir.return_value = False

        with patch('topsailai.tools.sandbox_tool.exec_cmd') as mock_exec:
            mock_exec.return_value = (0, "success", "")
            result = copy2sandbox("protocol=ssh,node=example.com", "/local/file.txt", "/remote/file.txt")
            self.assertTrue(result)
            mock_exec.assert_called_once()

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    @patch('topsailai.tools.sandbox_tool.os.path.isdir')
    @patch('topsailai.tools.sandbox_tool.os.path.basename')
    @patch('topsailai.tools.sandbox_tool.os.path.dirname')
    def test_copy2sandbox_ssh_directory(self, mock_dirname, mock_basename, mock_isdir, mock_parse):
        """Copy directory via SSH protocol."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_sandbox.name = "root"
        mock_parse.return_value = mock_sandbox
        mock_isdir.return_value = True
        mock_basename.return_value = "mydir"
        mock_dirname.return_value = "/remote"

        with patch('topsailai.tools.sandbox_tool.exec_cmd') as mock_exec:
            mock_exec.return_value = (0, "success", "")
            result = copy2sandbox("protocol=ssh,node=example.com", "/local/mydir", "/remote/mydir")
            self.assertTrue(result)

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    def test_copy2sandbox_unknown_protocol(self, mock_parse):
        """Return False for unknown protocol."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "unknown"
        mock_parse.return_value = mock_sandbox

        result = copy2sandbox("protocol=unknown,node=example.com", "/local/file.txt", "/remote/file.txt")
        self.assertFalse(result)

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    @patch('topsailai.tools.sandbox_tool.os.path.isdir')
    def test_copy2sandbox_success(self, mock_isdir, mock_parse):
        """Return True on successful copy (exit code 0)."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_sandbox.name = "root"
        mock_parse.return_value = mock_sandbox
        mock_isdir.return_value = False

        with patch('topsailai.tools.sandbox_tool.exec_cmd') as mock_exec:
            mock_exec.return_value = (0, "success", "")
            result = copy2sandbox("protocol=ssh,node=example.com", "/local/file.txt", "/remote/file.txt")
            self.assertTrue(result)

    @patch('topsailai.tools.sandbox_tool._parse_sandbox_config')
    @patch('topsailai.tools.sandbox_tool.os.path.isdir')
    def test_copy2sandbox_failure(self, mock_isdir, mock_parse):
        """Return False on failed copy (exit code non-zero)."""
        mock_sandbox = MagicMock()
        mock_sandbox.protocol = "ssh"
        mock_sandbox.node = "example.com"
        mock_sandbox.port = 22
        mock_sandbox.name = "root"
        mock_parse.return_value = mock_sandbox
        mock_isdir.return_value = False

        with patch('topsailai.tools.sandbox_tool.exec_cmd') as mock_exec:
            mock_exec.return_value = (1, "error", "connection failed")
            result = copy2sandbox("protocol=ssh,node=example.com", "/local/file.txt", "/remote/file.txt")
            self.assertFalse(result)


class TestListSandbox(TestCase):
    """Test cases for list_sandbox() function."""

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance')
    def test_list_sandbox_by_tag(self, mock_env):
        """Filter sandboxes by tag."""
        mock_env.get_list_str.return_value = [
            "tag=ai,protocol=ssh,node=server1.com",
            "tag=dev,protocol=ssh,node=server2.com",
            "tag=ai,protocol=docker,node=container1"
        ]

        result = list_sandbox("ai")
        self.assertIn("tag=ai", result)
        self.assertIn("server1.com", result)
        self.assertIn("container1", result)
        self.assertNotIn("server2.com", result)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance')
    def test_list_sandbox_empty_result(self, mock_env):
        """Return empty string when no matching tags."""
        mock_env.get_list_str.return_value = [
            "tag=ai,protocol=ssh,node=server1.com",
            "tag=dev,protocol=ssh,node=server2.com"
        ]

        result = list_sandbox("nonexistent")
        self.assertEqual(result, "")

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance')
    def test_list_sandbox_multiple_matches(self, mock_env):
        """Return multiple sandboxes with same tag."""
        mock_env.get_list_str.return_value = [
            "tag=ai,protocol=ssh,node=server1.com",
            "tag=ai,protocol=docker,node=container1",
            "tag=ai,protocol=ssh,node=server2.com"
        ]

        result = list_sandbox("ai")
        self.assertEqual(result.count("tag=ai"), 3)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance')
    def test_list_sandbox_env_var_fallback(self, mock_env):
        """Fallback to SANDBOX_SETTINGS when TOPSAILAI_SANDBOX_SETTINGS not set."""
        mock_env.get_list_str.side_effect = [None, ["tag=fallback,protocol=ssh,node=fallback.com"]]

        result = list_sandbox("fallback")
        self.assertIn("fallback.com", result)
        self.assertEqual(mock_env.get_list_str.call_count, 2)

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance')
    def test_list_sandbox_with_whitespace(self, mock_env):
        """Handle whitespace in sandbox configurations."""
        mock_env.get_list_str.return_value = [
            "  tag=ai  ,  protocol=ssh  ,  node=server1.com  ",
            "tag=dev,protocol=ssh,node=server2.com"
        ]

        result = list_sandbox("ai")
        self.assertIn("server1.com", result)
