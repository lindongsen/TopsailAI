'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-07-06
  Purpose: SSH agent tool for remote command execution and file transfer.
'''

import os
import shlex
import socket

from topsailai.utils.cmd_tool import exec_cmd
from topsailai.tools.cmd_tool import format_return


DEFAULT_SSH_PORT = 22
DEFAULT_SSH_USERNAME = "root"
DEFAULT_SSH_TIMEOUT = 120

DEFAULT_SSH_OPTIONS = {
    "StrictHostKeyChecking": "no",
    "UserKnownHostsFile": "/dev/null",
    "ConnectTimeout": "10",
    "ConnectionAttempts": "3",
    "LogLevel": "ERROR",
}


class SSHContext:
    """Normalized SSH connection context."""

    def __init__(
        self,
        host: str,
        port: int | str | None = None,
        username: str | None = None,
        private_key: str | None = None,
        options: dict | list | str | None = None,
        timeout: int | str | None = None,
    ):
        self.host = host
        self.port = int(port) if port is not None else DEFAULT_SSH_PORT
        self.username = (username or DEFAULT_SSH_USERNAME).strip()
        self.private_key = private_key
        self.options = self._normalize_options(options)
        self.timeout = int(timeout) if timeout is not None else DEFAULT_SSH_TIMEOUT

    def _normalize_options(self, options: dict | list | str | None) -> dict:
        """Merge user options with safe defaults."""
        merged = dict(DEFAULT_SSH_OPTIONS)
        if not options:
            return merged

        if isinstance(options, str):
            options = [options]

        if isinstance(options, list):
            for item in options:
                item = item.strip()
                if not item:
                    continue
                if "=" in item:
                    key, value = item.split("=", 1)
                    merged[key.strip()] = value.strip()
                else:
                    merged[item] = "yes"
        elif isinstance(options, dict):
            for key, value in options.items():
                merged[key.strip()] = str(value).strip()

        return merged

    def ssh_option_args(self) -> list:
        """Return SSH options as ['-o', 'key=value', ...] plus '-i' if needed."""
        args = []
        for key, value in self.options.items():
            args.extend(["-o", f"{key}={value}"])
        if self.private_key:
            args.extend(["-i", self.private_key])
        return args

    def ssh_options_string(self) -> str:
        """Return SSH options as a shell-safe string."""
        return " ".join(self.ssh_option_args())

    def user_host(self) -> str:
        return f"{self.username}@{self.host}"

    def remote_path(self, path: str) -> str:
        return f"{self.user_host()}:{path}"


def _is_localhost(host: str) -> bool:
    return not host or host in ("localhost", "local", "127.0.0.1", socket.gethostname())


def _validate_private_key(private_key: str | None) -> tuple | None:
    if private_key and not os.path.isfile(private_key):
        return (1, "", f"private key not found: {private_key}")
    return None


def _exec_remote_shell(ctx: SSHContext, command: str) -> tuple:
    """Execute a shell command on the remote host via SSH.

    Builds the SSH command as a list so subprocess handles argument quoting
    and no user input is interpolated into a shell string. The remote shell
    is invoked with ``bash -s`` and the command is fed through stdin.
    """
    cmd = (
        ["ssh"]
        + ctx.ssh_option_args()
        + ["-p", str(ctx.port), ctx.user_host(), "bash", "-s"]
    )
    return exec_cmd(cmd, input=command.encode("utf-8"), timeout=ctx.timeout)


class SSHExecOperator:
    """Execute a command on a remote host via SSH."""

    def run(self, ctx: SSHContext, command: str | list | None, **kwargs) -> tuple:
        if not command:
            return (1, "", "command is required")

        if isinstance(command, list):
            command = " ".join(str(part) for part in command)

        if _is_localhost(ctx.host):
            result = exec_cmd(command, timeout=ctx.timeout)
        else:
            result = _exec_remote_shell(ctx, command)

        return format_return(command, result)


class SSHScpOperator:
    """Copy files/folders via scp."""

    def run(
        self,
        ctx: SSHContext,
        source: str | None,
        target: str | None,
        direction: str = "to_remote",
        **kwargs,
    ) -> tuple:
        if not source or not target:
            return (1, "", "source and target are required")

        err = _validate_private_key(ctx.private_key)
        if err:
            return err

        source_is_dir = self._source_is_dir(ctx, source, direction)
        target_ends_with_slash = target.endswith("/")

        if direction == "to_remote":
            src_path = self._build_source_path(source, source_is_dir, target_ends_with_slash)
            dst_path = ctx.remote_path(target)
        else:
            src_path = ctx.remote_path(
                self._build_source_path(source, source_is_dir, target_ends_with_slash)
            )
            dst_path = target

        cmd = ["scp", "-P", str(ctx.port)] + ctx.ssh_option_args()
        if source_is_dir:
            cmd.append("-r")
        cmd.extend([src_path, dst_path])

        result = exec_cmd(cmd, timeout=ctx.timeout)
        return format_return(" ".join(cmd), result)

    def _source_is_dir(self, ctx: SSHContext, source: str, direction: str) -> bool:
        if direction == "to_remote":
            return os.path.isdir(source)

        test_cmd = f"test -d {shlex.quote(source)}"
        if _is_localhost(ctx.host):
            ret = exec_cmd(test_cmd, timeout=ctx.timeout)
        else:
            ret = _exec_remote_shell(ctx, test_cmd)
        return ret[0] == 0

    def _build_source_path(self, source: str, source_is_dir: bool, target_ends_with_slash: bool) -> str:
        if not source_is_dir:
            return source
        if target_ends_with_slash:
            # Copy the source directory itself into the target directory.
            return source
        # Target does not end with '/': copy contents to the target path,
        # preventing a nested subfolder when a same-named folder exists.
        return f"{source}/."


class SSHRsyncOperator:
    """Copy files/folders via rsync."""

    def run(
        self,
        ctx: SSHContext,
        source: str | None,
        target: str | None,
        direction: str = "to_remote",
        delete: bool = False,
        **kwargs,
    ) -> tuple:
        if not source or not target:
            return (1, "", "source and target are required")

        err = _validate_private_key(ctx.private_key)
        if err:
            return err

        source_is_dir = self._source_is_dir(ctx, source, direction)
        target_ends_with_slash = target.endswith("/")

        if direction == "to_remote":
            src_path = self._build_source_path(source, source_is_dir, target_ends_with_slash)
            dst_path = ctx.remote_path(target)
        else:
            src_path = ctx.remote_path(
                self._build_source_path(source, source_is_dir, target_ends_with_slash)
            )
            dst_path = target

        ssh_cmd_list = ["ssh", "-p", str(ctx.port)] + ctx.ssh_option_args()
        ssh_cmd = " ".join(ssh_cmd_list)
        cmd = ["rsync", "-a", "-e", ssh_cmd]
        if delete:
            cmd.append("--delete")
        cmd.extend([src_path, dst_path])

        result = exec_cmd(cmd, timeout=ctx.timeout)
        return format_return(" ".join(cmd), result)

    def _source_is_dir(self, ctx: SSHContext, source: str, direction: str) -> bool:
        if direction == "to_remote":
            return os.path.isdir(source)

        test_cmd = f"test -d {shlex.quote(source)}"
        if _is_localhost(ctx.host):
            ret = exec_cmd(test_cmd, timeout=ctx.timeout)
        else:
            ret = _exec_remote_shell(ctx, test_cmd)
        return ret[0] == 0

    def _build_source_path(self, source: str, source_is_dir: bool, target_ends_with_slash: bool) -> str:
        if not source_is_dir:
            return source
        if target_ends_with_slash:
            # Copy the source directory itself into the target directory.
            return source
        # Target does not end with '/': copy source contents to the target path.
        return f"{source}/"


_OPERATORS = {
    "exec": SSHExecOperator,
    "scp": SSHScpOperator,
    "rsync": SSHRsyncOperator,
}


def operate_ssh(action: str, host: str, **kwargs) -> tuple:
    """Single entry point for SSH operations.

    Use this function to execute commands or copy files via SSH.

    Supported actions:
        - "exec": execute a remote command.
        - "scp": copy files/folders via scp.
        - "rsync": copy files/folders via rsync.

    Common parameters (passed via **kwargs):
        port (int|str): SSH port, default 22.
        username (str): SSH username, default "root".
        private_key (str): Path to the private key file.
        options (dict|list|str): Extra SSH options, e.g. "StrictHostKeyChecking=no".
        timeout (int|str): Connection/operation timeout in seconds, default 120.

    Action-specific parameters (passed via **kwargs):
        exec:
            command (str|list): Command to execute on the remote host.
        scp / rsync:
            source (str): Local or remote source path.
            target (str): Local or remote target path.
            direction (str): "to_remote" (default) or "from_remote".
        rsync:
            delete (bool): Whether to add --delete, default False.

    Copy semantics for scp/rsync (Dockerfile-style):
        - target ends with '/': copy the source directory itself into the target
          directory.
          Example: source=/app/config, target=/etc/config/ -> creates
          /etc/config/config/...
        - target does not end with '/': copy source contents to the target path.
          Example: source=/app/config, target=/etc/config -> copies files to
          /etc/config/file1, /etc/config/file2, ...

    Security defaults:
        StrictHostKeyChecking=no, UserKnownHostsFile=/dev/null,
        ConnectTimeout=10, ConnectionAttempts=3, LogLevel=ERROR.

    Returns:
        tuple: (return_code, stdout, stderr)
    """
    operator_cls = _OPERATORS.get(action)
    if not operator_cls:
        return (1, "", f"unsupported action: {action}")

    ctx = SSHContext(
        host=host,
        port=kwargs.get("port"),
        username=kwargs.get("username"),
        private_key=kwargs.get("private_key"),
        options=kwargs.get("options"),
        timeout=kwargs.get("timeout"),
    )

    operator = operator_cls()
    return operator.run(ctx, **kwargs)


# Dictionary mapping tool names to their corresponding functions
TOOLS = dict(
    operate_ssh=operate_ssh,
)

PROMPT = ""

FLAG_TOOL_ENABLED = False
