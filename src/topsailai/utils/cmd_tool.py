'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-10
  Purpose:
'''

import os
import socket
import subprocess

from topsailai.logger import logger
from .text_tool import safe_decode


def build_env(d:dict=None):
    """Build environment dictionary with essential system variables.

    This function creates a dictionary containing commonly used environment
    variables (PYTHONPATH, PATH, HOSTNAME, SHELL) from the current process
    environment, and optionally updates it with additional variables.

    Args:
        d (dict, optional): Additional environment variables to merge.

    Returns:
        dict: Environment dictionary containing system variables and any
              provided additional variables.
    """
    env = {}
    for k in ["PYTHONPATH", "PATH", "HOSTNAME", "SHELL"]:
        v = os.getenv(k)
        if v:
            env[k] = v
    if d:
        env.update(d)
    return env


def exec_cmd(cmd:str|list, no_need_stderr:bool=False, timeout:int=None, need_error_log=False):
    """Execute a shell command and return the result.

    This function runs a command using subprocess.run, capturing stdout and stderr.
    It automatically handles encoding of output and allows suppressing stderr output.

    Args:
        cmd (str|list): Command to execute. If string, runs with shell=True.
        no_need_stderr (bool): If True, stderr will be returned as empty string.
                               Defaults to False.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a subprocess.TimeoutExpired
                                 exception will be raised. Defaults to None.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.

    Example:
        >>> exec_cmd(["echo", "hello"])
        (0, "hello\n", "")

        >>> exec_cmd("ls /nonexistent", no_need_stderr=True)
        (2, "", "")
    """
    env = build_env()
    result = subprocess.run(
        cmd,
        env=env,
        shell=isinstance(cmd, str),
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        timeout=timeout,
    )
    ret = (
        result.returncode,
        safe_decode(result.stdout),
        "" if no_need_stderr else safe_decode(result.stderr),
    )
    if need_error_log:
        if result.returncode != 0:
            logger.error("failed to execute command: cmd=[%s], ret=[%s]", cmd, ret)
    return ret

def exec_cmd_in_remote(cmd:str, remote:str, port=22, timeout:int=None):
    """Execute a command on a remote host via SSH.

    This function runs a command on a remote host using SSH. If the remote host
    is localhost or similar, it executes locally. It sets up SSH options to skip
    host key checking and uses a timeout for connection.

    Args:
        cmd (str): Command line to execute on remote host.
        remote (str): Remote hostname or IP address.
        port (int, optional): SSH port number. Defaults to 22.
        timeout (int, optional): Timeout in seconds for command execution.
                                 Defaults to None (no timeout).

    Returns:
        tuple: (return_code, stdout, stderr) as strings.

    Note:
        The SSH command uses root user; ensure SSH key authentication is set up.
        The remote command is executed via bash -s.
    """
    assert cmd
    if not remote \
        or remote in ["localhost", "local", "127.0.0.1", socket.gethostname()]:
        return exec_cmd(cmd)

    options = (
        "-o 'StrictHostKeyChecking no' "
        "-o 'UserKnownHostsFile /dev/null' "
        "-o ConnectTimeout=10 "
        "-o ConnectionAttempts=3 "
    )
    if port:
        options += f"-p {port}"

    cmd_ssh = f"cat << topsailaiEOF | ssh {options} root@{remote} bash -s\n{cmd}\ntopsailaiEOF"
    return exec_cmd(cmd_ssh, timeout=timeout)

def exec_cmd_in_new_process(cmd:str|list, env:dict=None) -> int:
    """Launch a command in a new detached process.

    This function starts a new process using subprocess.Popen with a new session.
    The process runs independently and its PID is returned.

    Args:
        cmd (str|list): Command to execute. If string, runs with shell=True.
        env (dict, optional): Additional environment variables to merge with
                              the base environment. Defaults to None.

    Returns:
        int: Process ID (PID) of the newly created process.

    Note:
        The process is started with start_new_session=True, which detaches it
        from the current process group. The caller is responsible for managing
        the process lifecycle.
    """
    env = build_env(env)
    p = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        env=env,
        start_new_session=True,
    )
    return p.pid
