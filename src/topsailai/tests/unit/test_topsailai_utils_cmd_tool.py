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
from topsailai.utils.env_tool import resolve_python_interpreter


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

    @staticmethod
    def _assert_process_exited(pid):
        """Assert that an exact process ID no longer exists."""
        for _ in range(100):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            import time
            time.sleep(0.01)
        pytest.fail(f"Process {pid} is still running after exec_cmd timed out")

    @staticmethod
    def _read_pid(pid_file):
        """Read a child PID recorded by a spawned test command."""
        for _ in range(100):
            if pid_file.exists():
                return int(pid_file.read_text(encoding="utf-8").strip())
            import time
            time.sleep(0.01)
        pytest.fail("Timed-out command did not record its child PID")

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
        assert stderr == ''

    def test_exec_cmd_timeout(self):
        """Test timeout cleanup preserves the TimeoutExpired contract."""
        with pytest.raises(subprocess.TimeoutExpired):
            exec_cmd("sleep 10", timeout=0.1)

    @pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
    def test_exec_cmd_string_timeout_kills_child(self, tmp_path):
        """Test a timed-out shell command leaves no child process behind."""
        pid_file = tmp_path / "string-child.pid"
        command = f"sleep 30 & echo $! > '{pid_file}'; wait"

        with pytest.raises(subprocess.TimeoutExpired):
            exec_cmd(command, timeout=0.2)

        self._assert_process_exited(self._read_pid(pid_file))

    @pytest.mark.skipif(os.name != "posix", reason="POSIX process-group regression")
    def test_exec_cmd_list_timeout_kills_descendant(self, tmp_path):
        """Test a timed-out list command leaves no descendant process behind."""
        pid_file = tmp_path / "list-child.pid"
        command = f"sleep 30 & echo $! > '{pid_file}'; wait"

        with pytest.raises(subprocess.TimeoutExpired):
            exec_cmd(["sh", "-c", command], timeout=0.2)

        self._assert_process_exited(self._read_pid(pid_file))

    def test_exec_cmd_timeout_reaps_process_and_pipes(self):
        """Test timeout cleanup communicates again after killing the process tree."""
        process = MagicMock()
        process.pid = 12345
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["consumer"], 0.1),
            (b"partial stdout", b"partial stderr"),
        ]
        with patch("topsailai.utils.cmd_tool.subprocess.Popen", return_value=process), \
                patch("topsailai.utils.cmd_tool._kill_process_tree") as kill_tree:
            with pytest.raises(subprocess.TimeoutExpired):
                exec_cmd(["consumer"], timeout=0.1)

        kill_tree.assert_called_once_with(process)
        assert process.communicate.call_count == 2
        process.communicate.assert_any_call()

    def test_exec_cmd_with_env(self):
        """Test executing command with custom environment."""
        custom_env = {'CUSTOM_VAR': 'test_value'}
        code, stdout, stderr = exec_cmd("echo $CUSTOM_VAR", env_info=custom_env)

        assert code == 0
        assert 'test_value' in stdout

    def test_exec_cmd_passes_utf8_stdin_text(self):
        """Test UTF-8 text is encoded and passed through subprocess stdin."""
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"ok", b"")
        with patch("topsailai.utils.cmd_tool.subprocess.Popen", return_value=process) as popen:
            result = exec_cmd(["consumer"], stdin_text="記憶")

        assert result == (0, "ok", "")
        assert popen.call_args.kwargs["stdin"] == subprocess.PIPE
        assert process.communicate.call_args.kwargs["input"] == "記憶".encode("utf-8")

    def test_exec_cmd_input_reaches_child_stdin(self):
        """Test input bytes are delivered through the child process stdin pipe."""
        result = exec_cmd(
            [resolve_python_interpreter(), "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())"],
            input=b"raw input",
        )

        assert result == (0, "raw input", "")

    def test_exec_cmd_passes_input_option_without_collision(self):
        """Test an input option is forwarded without a duplicate keyword error."""
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"ok", b"")
        with patch("topsailai.utils.cmd_tool.subprocess.Popen", return_value=process) as popen:
            result = exec_cmd(["consumer"], input=b"raw input")

        assert result == (0, "ok", "")
        assert popen.call_args.kwargs["stdin"] == subprocess.PIPE
        assert process.communicate.call_args.kwargs["input"] == b"raw input"

    def test_exec_cmd_rejects_input_with_explicit_stdin(self):
        """Test input and an explicit stdin cannot be used together."""
        with pytest.raises(ValueError, match="stdin and input arguments may not both be used"):
            exec_cmd(["consumer"], input=b"raw input", stdin=subprocess.PIPE)

    def test_exec_cmd_stdin_text_overrides_input_option(self):
        """Test explicit stdin_text takes precedence over the input option."""
        process = MagicMock(returncode=0)
        process.communicate.return_value = (b"ok", b"")
        with patch("topsailai.utils.cmd_tool.subprocess.Popen", return_value=process):
            result = exec_cmd(["consumer"], stdin_text="explicit", input=b"raw input")

        assert result == (0, "ok", "")
        assert process.communicate.call_args.kwargs["input"] == b"explicit"


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