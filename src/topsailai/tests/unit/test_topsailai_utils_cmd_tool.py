#!/usr/bin/env python3
"""Unit tests for cmd_tool.py module."""

import os
import subprocess
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from topsailai.utils.cmd_tool import (
    build_env,
    exec_cmd,
    exec_cmd_in_remote,
    exec_cmd_in_new_process
)


class TestBuildEnv:
    """Test cases for build_env function."""

    def test_build_env_basic(self):
        """Test building environment with basic system variables."""
        with patch.dict(os.environ, {
            'PYTHONPATH': '/test/python/path',
            'PATH': '/test/path',
            'HOSTNAME': 'test-host',
            'SHELL': '/bin/bash'
        }):
            env = build_env()
            
            assert 'PYTHONPATH' in env
            assert 'PATH' in env
            assert 'HOSTNAME' in env
            assert 'SHELL' in env
            assert env['PYTHONPATH'] == '/test/python/path'
            assert env['PATH'] == '/test/path'

    def test_build_env_with_additional_dict(self):
        """Test building environment with additional variables."""
        with patch.dict(os.environ, {'PATH': '/test/path'}):
            additional_vars = {'CUSTOM_VAR': 'custom_value', 'ANOTHER_VAR': 'another_value'}
            env = build_env(d=additional_vars)
            
            assert env['PATH'] == '/test/path'
            assert env['CUSTOM_VAR'] == 'custom_value'
            assert env['ANOTHER_VAR'] == 'another_value'

    def test_build_env_with_keys_parameter(self):
        """Test building environment with specific keys parameter."""
        with patch.dict(os.environ, {
            'PATH': '/test/path',
            'CUSTOM_KEY': 'custom_value',
            'ANOTHER_KEY': 'another_value'
        }):
            env = build_env(keys=['CUSTOM_KEY', 'ANOTHER_KEY'])
            
            assert 'PATH' in env  # Default key
            assert 'CUSTOM_KEY' in env
            assert 'ANOTHER_KEY' in env
            assert env['CUSTOM_KEY'] == 'custom_value'
            assert env['ANOTHER_KEY'] == 'another_value'

    def test_build_env_missing_variables(self):
        """Test building environment when some variables are missing."""
        with patch.dict(os.environ, {'PATH': '/test/path'}):
            # Clear other default variables
            for var in ['PYTHONPATH', 'HOSTNAME', 'SHELL']:
                if var in os.environ:
                    del os.environ[var]
            
            env = build_env()
            
            assert 'PATH' in env
            assert env['PATH'] == '/test/path'
            # Missing variables should not be in the result
            assert 'PYTHONPATH' not in env
            assert 'HOSTNAME' not in env
            assert 'SHELL' not in env


class TestExecCmd:
    """Test cases for exec_cmd function."""

    def test_exec_cmd_string_success(self):
        """Test executing command as string successfully."""
        code, stdout, stderr = exec_cmd("echo 'hello world'")
        
        assert code == 0
        assert 'hello world' in stdout
        assert stderr == ''

    def test_exec_cmd_list_success(self):
        """Test executing command as list successfully."""
        code, stdout, stderr = exec_cmd(["echo", "hello list"])
        
        assert code == 0
        assert 'hello list' in stdout
        assert stderr == ''

    def test_exec_cmd_with_error(self):
        """Test executing command that returns error."""
        code, stdout, stderr = exec_cmd("ls /nonexistent/directory")
        
        assert code != 0
        assert stdout == ''
        assert 'nonexistent' in stderr or 'No such file' in stderr

    def test_exec_cmd_no_need_stderr(self):
        """Test executing command with no_need_stderr=True."""
        code, stdout, stderr = exec_cmd("ls /nonexistent/directory", no_need_stderr=True)
        
        assert code != 0
        assert stdout == ''
        assert stderr == ''  # stderr should be empty string

    def test_exec_cmd_timeout(self):
        """Test executing command with timeout."""
        # This should timeout quickly
        with pytest.raises(subprocess.TimeoutExpired):
            exec_cmd("sleep 10", timeout=0.1)

    def test_exec_cmd_with_env(self):
        """Test executing command with custom environment."""
        custom_env = {'CUSTOM_VAR': 'test_value'}
        code, stdout, stderr = exec_cmd("echo $CUSTOM_VAR", env_info=custom_env)
        
        assert code == 0
        # The custom env var should be available to the command
        assert 'test_value' in stdout


class TestExecCmdInRemote:
    """Test cases for exec_cmd_in_remote function."""

    def test_exec_cmd_in_remote_localhost(self):
        """Test remote execution with localhost (should execute locally)."""
        with patch('topsailai.utils.cmd_tool.exec_cmd') as mock_exec_cmd:
            mock_exec_cmd.return_value = (0, 'local output', '')
            
            code, stdout, stderr = exec_cmd_in_remote("echo test", "localhost")
            
            mock_exec_cmd.assert_called_once_with("echo test")
            assert code == 0
            assert stdout == 'local output'
            assert stderr == ''

    def test_exec_cmd_in_remote_127_0_0_1(self):
        """Test remote execution with 127.0.0.1 (should execute locally)."""
        with patch('topsailai.utils.cmd_tool.exec_cmd') as mock_exec_cmd:
            mock_exec_cmd.return_value = (0, 'local output', '')
            
            code, stdout, stderr = exec_cmd_in_remote("echo test", "127.0.0.1")
            
            mock_exec_cmd.assert_called_once_with("echo test")
            assert code == 0
            assert stdout == 'local output'
            assert stderr == ''

    def test_exec_cmd_in_remote_actual_remote(self):
        """Test remote execution with actual remote host."""
        with patch('topsailai.utils.cmd_tool.exec_cmd') as mock_exec_cmd:
            mock_exec_cmd.return_value = (0, 'remote output', '')
            
            code, stdout, stderr = exec_cmd_in_remote("echo test", "remote-host")
            
            # Should call exec_cmd with SSH command
            call_args = mock_exec_cmd.call_args[0][0]
            assert 'ssh' in call_args
            assert 'remote-host' in call_args
            assert 'echo test' in call_args
            assert code == 0
            assert stdout == 'remote output'
            assert stderr == ''

    def test_exec_cmd_in_remote_with_port(self):
        """Test remote execution with custom port."""
        with patch('topsailai.utils.cmd_tool.exec_cmd') as mock_exec_cmd:
            mock_exec_cmd.return_value = (0, 'remote output', '')
            
            code, stdout, stderr = exec_cmd_in_remote("echo test", "remote-host", port=2222)
            
            call_args = mock_exec_cmd.call_args[0][0]
            assert '-p 2222' in call_args
            assert code == 0
            assert stdout == 'remote output'
            assert stderr == ''


class TestExecCmdInNewProcess:
    """Test cases for exec_cmd_in_new_process function."""

    def test_exec_cmd_in_new_process_string(self):
        """Test creating new process with string command."""
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 12345
            mock_popen.return_value = mock_process
            
            pid = exec_cmd_in_new_process("sleep 5")
            
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['shell'] == True
            assert call_kwargs['start_new_session'] == True
            assert pid == 12345

    def test_exec_cmd_in_new_process_list(self):
        """Test creating new process with list command."""
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 67890
            mock_popen.return_value = mock_process
            
            pid = exec_cmd_in_new_process(["sleep", "5"])
            
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert call_kwargs['shell'] == False
            assert call_kwargs['start_new_session'] == True
            assert pid == 67890

    def test_exec_cmd_in_new_process_with_env(self):
        """Test creating new process with custom environment."""
        with patch('subprocess.Popen') as mock_popen:
            mock_process = MagicMock()
            mock_process.pid = 11111
            mock_popen.return_value = mock_process
            
            custom_env = {'CUSTOM_VAR': 'test_value'}
            pid = exec_cmd_in_new_process("echo test", env=custom_env)
            
            mock_popen.assert_called_once()
            call_kwargs = mock_popen.call_args[1]
            assert 'env' in call_kwargs
            assert call_kwargs['env']['CUSTOM_VAR'] == 'test_value'
            assert pid == 11111


if __name__ == "__main__":
    pytest.main([__file__, "-v"])