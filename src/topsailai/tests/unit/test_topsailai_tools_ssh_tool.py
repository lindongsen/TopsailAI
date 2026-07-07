"""
Test for topsailai/tools/ssh_tool.py

Author: Dawsonlin
Email: lin_dongsen@126.com
Created: 2026-07-06
"""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from topsailai.tools.ssh_tool import (
    SSHContext,
    SSHExecOperator,
    SSHScpOperator,
    SSHRsyncOperator,
    operate_ssh,
    _OPERATORS,
    _is_localhost,
    _validate_private_key,
    DEFAULT_SSH_PORT,
    DEFAULT_SSH_USERNAME,
    DEFAULT_SSH_OPTIONS,
)


class TestSSHContext:
    """Test cases for SSHContext normalization."""

    def test_default_values(self):
        """Test default host, port, username and timeout."""
        ctx = SSHContext(host="example.com")
        assert ctx.host == "example.com"
        assert ctx.port == DEFAULT_SSH_PORT
        assert ctx.username == DEFAULT_SSH_USERNAME
        assert ctx.timeout == 120
        assert ctx.private_key is None
        assert ctx.options["StrictHostKeyChecking"] == "no"

    def test_custom_port_and_username(self):
        """Test custom port and username."""
        ctx = SSHContext(host="example.com", port=2222, username="admin")
        assert ctx.port == 2222
        assert ctx.username == "admin"

    def test_options_dict(self):
        """Test options passed as dict."""
        ctx = SSHContext(
            host="example.com",
            options={"StrictHostKeyChecking": "yes", "ConnectTimeout": "20"},
        )
        assert ctx.options["StrictHostKeyChecking"] == "yes"
        assert ctx.options["ConnectTimeout"] == "20"
        assert ctx.options["UserKnownHostsFile"] == "/dev/null"

    def test_options_list(self):
        """Test options passed as list of key=value strings."""
        ctx = SSHContext(
            host="example.com",
            options=["StrictHostKeyChecking=yes", "ConnectTimeout=20", "BatchMode"],
        )
        assert ctx.options["StrictHostKeyChecking"] == "yes"
        assert ctx.options["ConnectTimeout"] == "20"
        assert ctx.options["BatchMode"] == "yes"

    def test_options_string(self):
        """Test options passed as a single string."""
        ctx = SSHContext(
            host="example.com",
            options="StrictHostKeyChecking=yes",
        )
        assert ctx.options["StrictHostKeyChecking"] == "yes"

    def test_empty_options(self):
        """Test empty options fall back to defaults."""
        ctx = SSHContext(host="example.com", options=[])
        assert ctx.options["StrictHostKeyChecking"] == "no"

    def test_ssh_option_args(self):
        """Test conversion of options to ssh argument list."""
        ctx = SSHContext(
            host="example.com",
            private_key="/key.pem",
            options={"StrictHostKeyChecking": "yes"},
        )
        args = ctx.ssh_option_args()
        assert "-o" in args
        assert "StrictHostKeyChecking=yes" in args
        assert "-i" in args
        assert "/key.pem" in args

    def test_user_host_and_remote_path(self):
        """Test user_host and remote_path helpers."""
        ctx = SSHContext(host="example.com", username="admin")
        assert ctx.user_host() == "admin@example.com"
        assert ctx.remote_path("/tmp/file") == "admin@example.com:/tmp/file"


class TestIsLocalhost:
    """Test cases for _is_localhost helper."""

    def test_localhost_variants(self):
        """Test localhost detection."""
        assert _is_localhost("localhost") is True
        assert _is_localhost("127.0.0.1") is True
        assert _is_localhost("") is True
        assert _is_localhost("remote.com") is False


class TestValidatePrivateKey:
    """Test cases for private key validation."""

    def test_missing_private_key(self):
        """Test validation returns error for missing key file."""
        result = _validate_private_key("/nonexistent/key.pem")
        assert result[0] == 1
        assert "private key not found" in result[2]

    def test_none_private_key(self):
        """Test validation passes when no key is provided."""
        assert _validate_private_key(None) is None


class TestSSHExecOperator:
    """Test cases for SSHExecOperator."""

    def test_exec_missing_command(self):
        """Test exec returns error when command is missing."""
        ctx = SSHContext(host="example.com")
        op = SSHExecOperator()
        result = op.run(ctx, command=None)
        assert result[0] == 1
        assert "command is required" in result[2]

    def test_exec_localhost(self):
        """Test exec on localhost runs command locally."""
        ctx = SSHContext(host="localhost")
        op = SSHExecOperator()
        with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
            mock_exec.return_value = (0, "local output", "")
            result = op.run(ctx, command="echo hello")
            assert result == (0, "local output", "")
            mock_exec.assert_called_once_with("echo hello", timeout=ctx.timeout)

    def test_exec_remote_list_command(self):
        """Test exec on remote host with list command."""
        ctx = SSHContext(host="remote.com", username="admin", port=2222)
        op = SSHExecOperator()
        with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
            mock_exec.return_value = (0, "remote output", "")
            result = op.run(ctx, command=["echo", "hello"])
            assert result == (0, "remote output", "")
            call_args = mock_exec.call_args[0][0]
            assert call_args[0] == "ssh"
            assert "admin@remote.com" in call_args
            assert "-p" in call_args
            assert "2222" in call_args
            assert mock_exec.call_args[1]["input"] == b"echo hello"

    def test_exec_remote_options(self):
        """Test exec passes SSH options safely."""
        ctx = SSHContext(
            host="remote.com",
            options={"StrictHostKeyChecking": "no"},
            private_key="/key.pem",
        )
        op = SSHExecOperator()
        with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
            mock_exec.return_value = (0, "ok", "")
            op.run(ctx, command="whoami")
            call_args = mock_exec.call_args[0][0]
            assert "-o" in call_args
            assert "StrictHostKeyChecking=no" in call_args
            assert "-i" in call_args
            assert "/key.pem" in call_args


class TestSSHScpOperator:
    """Test cases for SSHScpOperator."""

    def test_scp_missing_source_or_target(self):
        """Test scp returns error when source or target missing."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        assert op.run(ctx, source=None, target="/tmp")[0] == 1
        assert op.run(ctx, source="/tmp", target=None)[0] == 1

    def test_scp_rejects_relative_local_source(self):
        """Test scp rejects relative local source path."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        result = op.run(ctx, source="tmp/file.txt", target="/tmp/file.txt")
        assert result[0] == 1
        assert "source must be an absolute local path" in result[2]

    def test_scp_rejects_relative_remote_target(self):
        """Test scp rejects relative remote target path."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        result = op.run(ctx, source="/tmp/file.txt", target="tmp/file.txt")
        assert result[0] == 1
        assert "target must be an absolute remote path" in result[2]

    def test_scp_from_remote_rejects_relative_remote_source(self):
        """Test scp from_remote rejects relative remote source path."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        result = op.run(
            ctx,
            source="etc/file.txt",
            target="/tmp/file.txt",
            direction="from_remote",
        )
        assert result[0] == 1
        assert "source must be an absolute remote path" in result[2]

    def test_scp_from_remote_rejects_relative_local_target(self):
        """Test scp from_remote rejects relative local target path."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        result = op.run(
            ctx,
            source="/etc/file.txt",
            target="tmp/file.txt",
            direction="from_remote",
        )
        assert result[0] == 1
        assert "target must be an absolute local path" in result[2]

    def test_scp_file_to_remote(self):
        """Test scp file copy to remote."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHScpOperator()
        with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
            mock_exec.return_value = (0, "", "")
            result = op.run(ctx, source="/tmp/file.txt", target="/etc/file.txt")
            assert result[0] == 0
            call_args = mock_exec.call_args[0][0]
            assert call_args[0] == "scp"
            assert "-P" in call_args
            assert "admin@remote.com:/etc/file.txt" in call_args
            assert "/tmp/file.txt" in call_args

    def test_scp_folder_to_remote_with_trailing_slash(self):
        """Test scp folder to remote with target ending in '/'."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHScpOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = True
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(ctx, source="/app/config", target="/etc/config/")
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "-r" in call_args
                assert "/app/config" in call_args
                assert "admin@remote.com:/etc/config/" in call_args

    def test_scp_folder_to_remote_without_trailing_slash(self):
        """Test scp folder to remote without target trailing '/'."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHScpOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = True
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(ctx, source="/app/config", target="/etc/config")
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "-r" in call_args
                assert "/app/config/." in call_args
                assert "admin@remote.com:/etc/config" in call_args

    def test_scp_from_remote(self):
        """Test scp copy from remote."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHScpOperator()
        with patch.object(op, "_source_is_dir", return_value=False):
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(
                    ctx,
                    source="/etc/file.txt",
                    target="/tmp/file.txt",
                    direction="from_remote",
                )
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "admin@remote.com:/etc/file.txt" in call_args
                assert "/tmp/file.txt" in call_args

    def test_scp_private_key_validation(self):
        """Test scp validates private key before copying."""
        ctx = SSHContext(host="remote.com", private_key="/missing.pem")
        op = SSHScpOperator()
        result = op.run(ctx, source="/tmp/a", target="/tmp/b")
        assert result[0] == 1
        assert "private key not found" in result[2]


class TestSSHRsyncOperator:
    """Test cases for SSHRsyncOperator."""

    def test_rsync_missing_source_or_target(self):
        """Test rsync returns error when source or target missing."""
        ctx = SSHContext(host="remote.com")
        op = SSHRsyncOperator()
        assert op.run(ctx, source=None, target="/tmp")[0] == 1
        assert op.run(ctx, source="/tmp", target=None)[0] == 1

    def test_rsync_rejects_relative_local_source(self):
        """Test rsync rejects relative local source path."""
        ctx = SSHContext(host="remote.com")
        op = SSHRsyncOperator()
        result = op.run(ctx, source="tmp/file.txt", target="/tmp/file.txt")
        assert result[0] == 1
        assert "source must be an absolute local path" in result[2]

    def test_rsync_rejects_relative_remote_target(self):
        """Test rsync rejects relative remote target path."""
        ctx = SSHContext(host="remote.com")
        op = SSHRsyncOperator()
        result = op.run(ctx, source="/tmp/file.txt", target="tmp/file.txt")
        assert result[0] == 1
        assert "target must be an absolute remote path" in result[2]

    def test_rsync_from_remote_rejects_relative_remote_source(self):
        """Test rsync from_remote rejects relative remote source path."""
        ctx = SSHContext(host="remote.com")
        op = SSHRsyncOperator()
        result = op.run(
            ctx,
            source="etc/file.txt",
            target="/tmp/file.txt",
            direction="from_remote",
        )
        assert result[0] == 1
        assert "source must be an absolute remote path" in result[2]

    def test_rsync_from_remote_rejects_relative_local_target(self):
        """Test rsync from_remote rejects relative local target path."""
        ctx = SSHContext(host="remote.com")
        op = SSHRsyncOperator()
        result = op.run(
            ctx,
            source="/etc/file.txt",
            target="tmp/file.txt",
            direction="from_remote",
        )
        assert result[0] == 1
        assert "target must be an absolute local path" in result[2]

    def test_rsync_file_to_remote(self):
        """Test rsync file copy to remote."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHRsyncOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = False
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(ctx, source="/tmp/file.txt", target="/etc/file.txt")
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert call_args[0] == "rsync"
                assert "-a" in call_args
                assert "/tmp/file.txt" in call_args
                assert "admin@remote.com:/etc/file.txt" in call_args

    def test_rsync_folder_to_remote_with_trailing_slash(self):
        """Test rsync folder to remote with target ending in '/'."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHRsyncOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = True
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(ctx, source="/app/config", target="/etc/config/")
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "rsync" in call_args
                assert "/app/config" in call_args
                assert "/app/config/" not in call_args
                assert "admin@remote.com:/etc/config/" in call_args
                assert "--delete" not in call_args

    def test_rsync_folder_to_remote_without_trailing_slash(self):
        """Test rsync folder to remote without target trailing '/'."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHRsyncOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = True
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(ctx, source="/app/config", target="/etc/config")
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "/app/config/" in call_args
                assert "admin@remote.com:/etc/config" in call_args
                assert "--delete" not in call_args

    def test_rsync_opt_in_delete(self):
        """Test rsync --delete is only added when explicitly requested."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHRsyncOperator()
        with patch("topsailai.tools.ssh_tool.os.path.isdir") as mock_isdir:
            mock_isdir.return_value = True
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                op.run(
                    ctx,
                    source="/app/config",
                    target="/etc/config/",
                    delete=True,
                )
                call_args = mock_exec.call_args[0][0]
                assert "--delete" in call_args

    def test_rsync_from_remote(self):
        """Test rsync copy from remote."""
        ctx = SSHContext(host="remote.com", username="admin")
        op = SSHRsyncOperator()
        with patch.object(op, "_source_is_dir", return_value=False):
            with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
                mock_exec.return_value = (0, "", "")
                result = op.run(
                    ctx,
                    source="/etc/file.txt",
                    target="/tmp/file.txt",
                    direction="from_remote",
                )
                assert result[0] == 0
                call_args = mock_exec.call_args[0][0]
                assert "admin@remote.com:/etc/file.txt" in call_args
                assert "/tmp/file.txt" in call_args


class TestOperateSSH:
    """Test cases for operate_ssh factory entry point."""

    def test_unsupported_action(self):
        """Test operate_ssh returns error for unsupported action."""
        result = operate_ssh("ftp", "remote.com")
        assert result[0] == 1
        assert "unsupported action" in result[2]

    def test_factory_dispatch_exec(self):
        """Test factory dispatches exec action."""
        with patch.object(SSHExecOperator, "run") as mock_run:
            mock_run.return_value = (0, "ok", "")
            result = operate_ssh("exec", "remote.com", command="whoami")
            assert result == (0, "ok", "")
            mock_run.assert_called_once()
    def test_factory_dispatch_scp(self):
        """Test factory dispatches scp action."""
        with patch.object(SSHScpOperator, "run") as mock_run:
            mock_run.return_value = (0, "", "")
            result = operate_ssh(
                "scp",
                "remote.com",
                source="/tmp/a",
                target="/tmp/b",
            )
            assert result == (0, "", "")
            mock_run.assert_called_once()

    def test_factory_dispatch_rsync(self):
        """Test factory dispatches rsync action."""
        with patch.object(SSHRsyncOperator, "run") as mock_run:
            mock_run.return_value = (0, "", "")
            result = operate_ssh(
                "rsync",
                "remote.com",
                source="/tmp/a",
                target="/tmp/b",
            )
            assert result == (0, "", "")
            mock_run.assert_called_once()

    def test_operate_ssh_with_all_common_kwargs(self):
        """Test operate_ssh passes common kwargs to SSHContext."""
        with patch("topsailai.tools.ssh_tool.SSHContext") as mock_ctx_cls:
            mock_ctx = MagicMock()
            mock_ctx_cls.return_value = mock_ctx
            with patch.object(SSHExecOperator, "run") as mock_run:
                mock_run.return_value = (0, "", "")
                operate_ssh(
                    "exec",
                    "remote.com",
                    port=2222,
                    username="admin",
                    private_key="/key.pem",
                    options={"BatchMode": "yes"},
                    timeout=60,
                    command="ls",
                )
                mock_ctx_cls.assert_called_once_with(
                    host="remote.com",
                    port=2222,
                    username="admin",
                    private_key="/key.pem",
                    options={"BatchMode": "yes"},
                    timeout=60,
                )


class TestEdgeCases:
    """Test edge cases for ssh_tool."""

    def test_path_with_spaces_quoted_in_source_is_dir(self):
        """Test remote path with spaces is quoted."""
        ctx = SSHContext(host="remote.com")
        op = SSHScpOperator()
        with patch("topsailai.tools.ssh_tool.exec_cmd") as mock_exec:
            mock_exec.return_value = (0, "", "")
            op._source_is_dir(ctx, "/tmp/my dir", direction="from_remote")
            call_args = mock_exec.call_args[0][0]
            if isinstance(call_args, str):
                assert "'/tmp/my dir'" in call_args or '"/tmp/my dir"' in call_args
            else:
                # The quoted path is passed to the remote bash via stdin input,
                # not as a positional argument to ssh.
                assert mock_exec.call_args[1]["input"] == b"test -d '/tmp/my dir'"

    def test_operators_registry(self):
        """Test operator registry contains expected actions."""
        assert set(_OPERATORS.keys()) == {"exec", "scp", "rsync"}
        assert _OPERATORS["exec"] is SSHExecOperator
        assert _OPERATORS["scp"] is SSHScpOperator
        assert _OPERATORS["rsync"] is SSHRsyncOperator

    def test_tools_constant(self):
        """Test TOOLS constant exposes operate_ssh."""
        from topsailai.tools.ssh_tool import TOOLS
        assert "operate_ssh" in TOOLS
        assert callable(TOOLS["operate_ssh"])

    def test_prompt_constant(self):
        """Test PROMPT constant is a string.

        Usage documentation lives in the operate_ssh docstring, so PROMPT is
        intentionally left empty.
        """
        from topsailai.tools.ssh_tool import PROMPT
        assert isinstance(PROMPT, str)

    def test_flag_tool_enabled(self):
        """Test tool is disabled by default."""
        from topsailai.tools.ssh_tool import FLAG_TOOL_ENABLED
        assert FLAG_TOOL_ENABLED is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
