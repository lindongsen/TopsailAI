'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-10
  Purpose: Test sandbox tool for executing commands in different environments
'''

import pytest
from unittest.mock import patch, MagicMock

from topsailai.tools.sandbox_tool import (
    Sandbox,
    _parse_sandbox_config,
    call_sandbox,
    list_sandbox,
    copy2sandbox,
    TOOLS,
    PROMPT,
    FLAG_TOOL_ENABLED,
)


class TestSandboxClass:
    """Test cases for the Sandbox class."""

    def test_sandbox_init_default_values(self):
        """Test Sandbox class initializes with correct default values."""
        sandbox = Sandbox()
        assert sandbox.protocol == ""
        assert sandbox.node == ""
        assert sandbox.tags == set()
        assert sandbox.port == 22
        assert sandbox.name == ""

    def test_sandbox_attributes_can_be_modified(self):
        """Test Sandbox attributes can be modified after initialization."""
        sandbox = Sandbox()
        sandbox.protocol = "ssh"
        sandbox.node = "example.com"
        sandbox.port = 2222
        sandbox.name = "test_container"
        sandbox.tags.add("ai")
        
        assert sandbox.protocol == "ssh"
        assert sandbox.node == "example.com"
        assert sandbox.port == 2222
        assert sandbox.name == "test_container"
        assert "ai" in sandbox.tags


class TestParseSandboxConfig:
    """Test cases for the _parse_sandbox_config function."""

    def test_parse_ssh_sandbox(self):
        """Test parsing SSH sandbox configuration."""
        config_str = "protocol=ssh,node=example.com,port=2222"
        sandbox = _parse_sandbox_config(config_str)
        
        assert sandbox.protocol == "ssh"
        assert sandbox.node == "example.com"
        assert sandbox.port == "2222"

    def test_parse_docker_sandbox(self):
        """Test parsing Docker sandbox configuration."""
        config_str = "protocol=docker,node=localhost,name=my_container"
        sandbox = _parse_sandbox_config(config_str)
        
        assert sandbox.protocol == "docker"
        assert sandbox.node == "localhost"
        assert sandbox.name == "my_container"

    def test_parse_sandbox_with_tags(self):
        """Test parsing sandbox configuration with tags."""
        config_str = "protocol=ssh,node=example.com,tag=ai,tag=test"
        sandbox = _parse_sandbox_config(config_str)
        
        assert sandbox.tags == {"ai", "test"}
        assert sandbox.protocol == "ssh"

    def test_parse_sandbox_with_spaces(self):
        """Test parsing sandbox configuration with extra spaces."""
        config_str = "protocol=ssh , node=example.com , tag=ai "
        sandbox = _parse_sandbox_config(config_str)
        
        assert sandbox.protocol == "ssh"
        assert sandbox.node == "example.com"
        assert "ai" in sandbox.tags

    def test_parse_empty_config(self):
        """Test parsing empty configuration string."""
        sandbox = _parse_sandbox_config("")
        
        assert sandbox.protocol == ""
        assert sandbox.node == ""
        assert sandbox.tags == set()

    def test_parse_config_with_empty_values(self):
        """Test parsing configuration with empty parts."""
        sandbox = _parse_sandbox_config("protocol=ssh,,node=example.com,")
        
        assert sandbox.protocol == "ssh"
        assert sandbox.node == "example.com"


class TestCallSandbox:
    """Test cases for the call_sandbox function."""

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_call_sandbox_ssh_success(self, mock_format, mock_exec):
        """Test calling sandbox with SSH protocol - success case."""
        mock_result = ("output", "error", 0)
        mock_exec.return_value = mock_result
        mock_format.return_value = "formatted_output"
        
        result = call_sandbox("protocol=ssh,node=example.com", "ls -la")
        
        mock_exec.assert_called_once_with(
            "ls -la",
            remote="example.com",
            port=22,
            timeout=30
        )
        mock_format.assert_called_once_with("ls -la", mock_result)

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    @patch('topsailai.tools.cmd_tool.format_return')
    def test_call_sandbox_ssh_custom_port(self, mock_format, mock_exec):
        """Test calling sandbox with SSH protocol and custom port."""
        mock_result = ("output", "error", 0)
        mock_exec.return_value = mock_result
        mock_format.return_value = "formatted_output"
        
        result = call_sandbox("protocol=ssh,node=example.com,port=2222", "pwd", timeout=60)
        
        mock_exec.assert_called_once_with(
            "pwd",
            remote="example.com",
            port="2222",
            timeout=60
        )

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_unknown_protocol(self, mock_exec):
        """Test calling sandbox with unknown protocol."""
        result = call_sandbox("protocol=unknown,node=example.com", "ls")
        
        mock_exec.assert_not_called()
        assert result == "unknown sandbox"

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_no_result(self, mock_exec):
        """Test calling sandbox when exec returns None."""
        mock_exec.return_value = None
        
        result = call_sandbox("protocol=ssh,node=example.com", "ls")
        
        assert result == "unknown sandbox"


class TestCopy2Sandbox:
    """Test cases for the copy2sandbox function."""

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    @patch('os.path.isdir')
    def test_copy_file_to_ssh_sandbox(self, mock_isdir, mock_exec):
        """Test copying a file to SSH sandbox."""
        mock_isdir.return_value = False
        mock_exec.return_value = (0, "success")
        
        result = copy2sandbox(
            "protocol=ssh,node=example.com,port=2222",
            "/local/file.txt",
            "/remote/file.txt"
        )
        
        assert result is True
        mock_exec.assert_called_once()
        call_args = mock_exec.call_args[0][0]
        assert "scp" in call_args
        assert "2222" in call_args

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    @patch('os.path.isdir')
    def test_copy_directory_to_ssh_sandbox(self, mock_isdir, mock_exec):
        """Test copying a directory to SSH sandbox."""
        mock_isdir.return_value = True
        mock_exec.return_value = (0, "success")
        
        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/mydir",
            "/remote/mydir"
        )
        
        assert result is True
        call_args = mock_exec.call_args[0][0]
        assert "-r" in call_args

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy_with_unknown_protocol(self, mock_exec):
        """Test copying with unknown protocol returns False."""
        result = copy2sandbox(
            "protocol=unknown,node=example.com",
            "/local/file.txt",
            "/remote/file.txt"
        )
        
        assert result is False
        mock_exec.assert_not_called()

    @patch('topsailai.tools.sandbox_tool.exec_cmd')
    def test_copy_failure(self, mock_exec):
        """Test copying when command fails."""
        mock_exec.return_value = (1, "error")
        
        result = copy2sandbox(
            "protocol=ssh,node=example.com",
            "/local/file.txt",
            "/remote/file.txt"
        )
        
        assert result is False


class TestListSandbox:
    """Test cases for the list_sandbox function."""

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_matching_tag(self, mock_get_list):
        """Test listing sandbox with matching tag."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com",
            "tag=test,protocol=docker,node=host2.com"
        ]
        
        result = list_sandbox("ai")
        
        assert "tag=ai" in result
        assert "tag=test" not in result

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_no_matching_tag(self, mock_get_list):
        """Test listing sandbox with no matching tag."""
        mock_get_list.return_value = [
            "tag=ai,protocol=ssh,node=host1.com"
        ]
        
        result = list_sandbox("nonexistent")
        
        assert result == ""

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_empty_settings(self, mock_get_list):
        """Test listing sandbox when no settings configured."""
        mock_get_list.return_value = []
        
        result = list_sandbox("ai")
        
        assert result == ""

    @patch('topsailai.tools.sandbox_tool.env_tool.EnvReaderInstance.get_list_str')
    def test_list_sandbox_with_spaces(self, mock_get_list):
        """Test listing sandbox with spaces in settings."""
        mock_get_list.return_value = [
            "  tag=ai , protocol=ssh , node=host1.com  "
        ]
        
        result = list_sandbox("ai")
        
        assert "tag=ai" in result


class TestModuleConstants:
    """Test cases for module-level constants."""

    def test_tools_dictionary(self):
        """Test TOOLS dictionary contains expected functions."""
        assert "call_sandbox" in TOOLS
        assert "list_sandbox" in TOOLS
        assert "copy2sandbox" in TOOLS
        assert TOOLS["call_sandbox"] is call_sandbox
        assert TOOLS["list_sandbox"] is list_sandbox
        assert TOOLS["copy2sandbox"] is copy2sandbox

    def test_prompt_contains_sandbox_info(self):
        """Test PROMPT contains sandbox tool information."""
        assert "sandbox" in PROMPT.lower()
        assert "list_sandbox" in PROMPT
        assert "call_sandbox" in PROMPT

    def test_flag_tool_enabled_is_false(self):
        """Test FLAG_TOOL_ENABLED is set to False."""
        assert FLAG_TOOL_ENABLED is False


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_parse_config_with_equals_in_value(self):
        """Test parsing config where value contains equals sign."""
        config_str = "protocol=ssh,node=example.com,cmd=echo 'a=b'"
        sandbox = _parse_sandbox_config(config_str)
        
        assert sandbox.protocol == "ssh"
        assert sandbox.node == "example.com"

    @patch('topsailai.tools.sandbox_tool.exec_cmd_in_remote')
    def test_call_sandbox_default_timeout(self, mock_exec):
        """Test that default timeout is 30 seconds."""
        mock_exec.return_value = None
        
        call_sandbox("protocol=ssh,node=example.com", "ls")
        
        call_kwargs = mock_exec.call_args[1]
        assert call_kwargs["timeout"] == 30
