'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2025-12-10
  Purpose:
'''

import os
import shutil
import signal
import socket
import subprocess

from topsailai.logger import logger
from .text_tool import safe_decode
from .env_tool import EnvReaderInstance


def format_cmd(cmd, remote=None):
    if isinstance(cmd, str):
        if remote:
            cmd = cmd.replace('$', r'\$')
    elif isinstance(cmd, list):
        if len(cmd) == 1:
            return cmd[0]
    return cmd

def build_env(d:dict=None, keys:list=None):
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
    for k in [
        "HOME",
        "PYTHONPATH", "PATH", "HOSTNAME", "SHELL",
        "GOCACHE", "GOPATH", "GOMODCACHE",
    ] + (
            keys or []
    ) + (
            EnvReaderInstance.get_list_str("TOPSAILAI_CMD_ENV_KEYS", separator=None) or []
    ):
        v = os.getenv(k)
        if v:
            env[k] = v
    if d:
        env.update(d)

    if not env.get("HOME"):
        env["HOME"] = os.path.abspath(os.curdir)

    return env


def _set_process_group_options(options):
    """Configure a new process group for timeout cleanup."""
    if os.name == "posix":
        options["start_new_session"] = True
        return
    if os.name == "nt":
        creationflags = options.get("creationflags", 0)
        options["creationflags"] = creationflags | subprocess.CREATE_NEW_PROCESS_GROUP


def _kill_process_tree(process):
    """Kill a process and its descendants after a command timeout.

    KNOWN LIMITATION: this only reaches processes that stayed inside the process
    group created by ``_set_process_group_options``. A command that daemonizes
    itself escapes that group and survives the kill. Measured behaviour:

    - ``ssh -f``, ``setsid``, and any double-forking daemon call ``setsid()`` and
      become the leader of a brand new session, so ``os.killpg`` never signals
      them. Only the direct shell dies, and it is left as a zombie until reaped.
    - Killing by session id does NOT help. The escapee owns its own session
      (observed ``sid=2473662`` for the escapee versus ``sid=2473661`` for the
      shell), so ``os.killpg(os.getsid(process.pid), SIGKILL)`` misses it.
    - Tracking descendants does NOT help either. The escapee is reparented to
      ``PPID=1``, so ``psutil.Process(process.pid).children(recursive=True)``
      returns an empty list once the shell exits.
    - The only reliable identification is scanning ``/proc/<pid>/fd`` for every
      process still holding the pipe write end. That is Linux-only, has no
      macOS or Windows equivalent, can match an unrelated process that
      legitimately inherited the pipe, and costs O(processes x fds) per call
      (measured 0.056s across 539 processes).

    Consequence: a surviving escapee keeps the stdout/stderr pipe write end
    open, so the pipe never reaches EOF. See the timeout handler in ``exec_cmd``
    for why that turns into an unbounded hang.
    """
    if os.name == "posix":
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        return
    if os.name == "nt":
        result = subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if result.returncode == 0:
            return
    if process.poll() is None:
        process.kill()


def _set_preferred_shell(cmd, options):
    """Prefer Bash for string commands while preserving the default fallback."""
    if not isinstance(cmd, str) or "executable" in options:
        return
    bash_path = shutil.which("bash")
    if bash_path:
        options["executable"] = bash_path


def exec_cmd(
        cmd:str|list,
        no_need_stderr:bool=False,
        timeout:int=None,
        need_error_log=False,
        env_keys:list=None,
        env_info:dict=None,
        stdin_text:str=None,
        **options
    ):
    """Execute a shell command and return the result.

    This function runs a command using subprocess.Popen, capturing stdout and stderr.
    It automatically handles encoding of output and allows suppressing stderr output.

    Args:
        cmd (str|list): Command to execute. If string, runs with shell=True.
        no_need_stderr (bool): If True, stderr will be returned as empty string.
                               Defaults to False.
        timeout (int, optional): Timeout in seconds. If the command does not finish
                                 within this time, a subprocess.TimeoutExpired
                                 exception will be raised. Defaults to None.
        stdin_text (str, optional): UTF-8 text passed to the command through stdin.

    Returns:
        tuple: (return_code, stdout, stderr) where stdout and stderr are strings.
               If no_need_stderr is True, stderr will be empty string.

    Example:
        >>> exec_cmd(["echo", "hello"])
        (0, "hello\n", "")

        >>> exec_cmd("ls /nonexistent", no_need_stderr=True)
        (2, "", "")
    """
    cmd = format_cmd(cmd)
    env = build_env(env_info, env_keys)
    subprocess_input = options.pop("input", None)
    if stdin_text is not None:
        subprocess_input = stdin_text.encode("utf-8")
    if subprocess_input is not None:
        if options.get("stdin") is not None:
            raise ValueError("stdin and input arguments may not both be used.")
        options["stdin"] = subprocess.PIPE
    _set_process_group_options(options)
    _set_preferred_shell(cmd, options)
    process = subprocess.Popen(
        cmd,
        env=env,
        shell=isinstance(cmd, str),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=False,
        **options
    )
    # ------------------------------------------------------------------
    # TIMEOUT CLEANUP: KNOWN UNBOUNDED HANG (not yet fixed, documented only)
    # ------------------------------------------------------------------
    # HUMAN DECISION: the human explicitly REJECTS every candidate solution
    # listed below (A, B, C and D). None of them may be implemented. The human
    # has not yet found an acceptable approach, so this stays an open problem
    # until the human decides otherwise. Do not pick one of these options on
    # your own initiative, even if it looks like the obvious fix.
    # The cleanup below is NOT bounded by ``timeout``. When the command spawns a
    # process that escapes the process group (``ssh -f``, ``setsid``, any
    # double-forking daemon), the sequence is:
    #
    #   1. ``communicate(timeout=...)`` raises ``TimeoutExpired`` as designed.
    #   2. ``_kill_process_tree`` kills only the process group, so the escapee
    #      survives and the direct shell is left as a zombie.
    #   3. The escapee still holds the stdout/stderr pipe write end, so the pipe
    #      never reaches EOF.
    #   4. ``process.communicate()`` is called WITHOUT a timeout. Internally it
    #      waits with ``endtime=None``, so ``selector.select(None)`` blocks
    #      forever. The caller never regains control.
    #
    # Observed in production: a command with ``timeout=180`` blocked the agent
    # main loop for 61277 seconds (about 17 hours) until the escaped ``ssh -f``
    # tunnel was killed by PID from outside. The timeout fired correctly; the
    # cleanup path is what hung. Reproduced twice more within minutes, because
    # ``ssh-tunnelctl`` itself launches ``ssh -f``.
    #
    # Measured facts that constrain any fix (probes run on this host):
    #
    #   - ``wait()`` alone, pipes left open, after ``killpg``: returns in 0.000s.
    #     ``wait()`` is what unblocks; closing the pipes is not what does it.
    #   - ``TimeoutExpired.output`` already carries partial output (observed
    #     ``b'PARTIAL\n'``), and no caller in this project reads ``.output`` or
    #     ``.stderr`` from the exception, so the payload contract is preserved
    #     even if the pipes are closed during cleanup.
    #   - ``wait(timeout=...)`` can raise ``TimeoutExpired`` a SECOND time if the
    #     process is still alive. That would mask the original exception, so any
    #     replacement must swallow it.
    #
    # Candidate fixes and their side effects, all verified by probe:
    #
    #   A. Close the pipes, then ``wait(timeout=...)``.
    #      Fixes the hang. Side effects:
    #      - A background process started as ``./server &`` WITHOUT output
    #        redirection dies from SIGPIPE when the read ends close (observed).
    #        A redirected daemon (``>/dev/null 2>&1``) survives.
    #      - It does NOT kill the escapee. A process that never writes to stderr
    #        stays alive after the pipes close (observed), so orphan tunnels
    #        keep accumulating; only the agent stops hanging.
    #      - The second ``TimeoutExpired`` from ``wait`` must be suppressed.
    #
    #   B. Kill by session id, or track descendants with psutil.
    #      Does NOT work, do not implement it as-is:
    #      - ``os.killpg(os.getsid(process.pid), SIGKILL)`` misses the escapee,
    #        which owns its own session (observed sid 2473662 vs 2473661).
    #      - ``psutil.Process(process.pid).children(recursive=True)`` returns an
    #        empty list, because the escapee is reparented to PPID=1.
    #      - Scanning ``/proc/<pid>/fd`` for pipe holders is the only reliable
    #        method, but it is Linux-only, may match an unrelated process that
    #        inherited the pipe, and costs O(processes x fds) per call
    #        (measured 0.056s across 539 processes).
    #
    #   C. An outer watchdog (SIGALRM or a timer thread).
    #      Side effects:
    #      - ``signal.signal`` raises "signal only works in main thread" outside
    #        the main thread, so the watchdog silently stops working if tool
    #        execution ever moves to a worker thread.
    #      - SIGALRM does interrupt a blocked ``communicate()`` (observed after
    #        2.0s), but it leaves the child unreaped and the pipes open, so the
    #        watchdog must also run the kill-and-close cleanup or it trades a
    #        hang for a zombie plus leaked file descriptors.
    #      - A tight bound would abort legitimate long-running commands.
    #
    #   D. Capture stdout/stderr into temporary files instead of pipes.
    #      Removes the hang at its source: with no pipe there is no EOF to wait
    #      for, so ``communicate()`` returned in 0.001s even with a live escapee.
    #      Partial output, stdin input, and multi-megabyte output all worked.
    #      Side effect: pipe backpressure is lost. ``yes`` wrote 681.9 MB to disk
    #      in 1.5s, where a pipe would have blocked the writer at about 64 KB.
    #      This option therefore requires an explicit output size cap.
    #
    # No fix is approved. Callers that may run a daemonizing command must not
    # rely on ``timeout`` to bound the call.
    #
    # HUMAN PROPOSAL (not rejected, not yet implemented): launch the process
    # through tmux and control it through tmux instead of running it directly.
    # This is the only approach so far that the human considers acceptable in
    # principle. It is documented here as a workaround, NOT as an approved fix
    # for the code below. Probes on this host confirmed it works:
    #
    #   - Baseline ``setsid sleep 30 2>&1 &`` through this function: HUNG, the
    #     outer alarm fired at 20s and the call never returned.
    #   - Same daemonizing command wrapped as
    #     ``tmux -L <socket> new-session -d 'setsid sleep 30'``: returned in
    #     0.024s with stdout ``b'started\n'``.
    #
    # Why it works: the tmux CLIENT is a short-lived process that exits as soon
    # as the session is created, and the tmux SERVER daemonizes itself
    # (``ppid=1``, its own session id). Scanning ``/proc/<pid>/fd`` after the
    # call returned found NO process holding the caller's stdout or stderr pipe,
    # so the pipe reaches EOF immediately and the unbounded ``communicate()``
    # has nothing to wait for. The escapee problem disappears because the
    # long-lived process is no longer a child of this function at all.
    #
    # Requirements and side effects, all measured:
    #
    #   - ``-d`` is mandatory. Without it tmux tries to attach a terminal and
    #     fails with ``open terminal failed: not a terminal`` (returned in
    #     0.013s, so it fails fast rather than hanging, but nothing runs).
    #   - Use a dedicated socket (``-L <name>``) per caller. The default socket
    #     is shared with the human's own sessions, and ``kill-server`` on it
    #     would destroy unrelated work.
    #   - Exit status is NOT propagated. The tmux client returns 0 no matter
    #     what the command does (verified: a command exiting 42 still gave
    #     client rc 0). The status must be read separately, either with
    #     ``set-option -t <session> remain-on-exit on`` set BEFORE the command
    #     exits and then ``display-message -p '#{pane_dead_status}'`` (verified
    #     returning 42), or by having a wrapper write ``$?`` to a file
    #     (verified). Without ``remain-on-exit`` the pane and its output are
    #     destroyed on exit and ``capture-pane`` returns an empty string.
    #   - Output is a terminal stream, not a clean pipe. It contains the echoed
    #     command, shell prompts, and ANSI escape sequences such as
    #     ``\x1b]0;root@host: ~/dir\x07``. Any consumer must strip these.
    #   - Output must be captured with ``pipe-pane -o 'cat > <file>'`` or
    #     ``capture-pane``. ``pipe-pane`` handled 1.48 MB from ``seq 1 200000``
    #     without loss, but the log file grows without bound, so it needs the
    #     same size cap that option D requires.
    #   - The tmux server outlives this function and is reparented to ``ppid=1``
    #     in its own session, so ``_kill_process_tree`` cannot reach it either.
    #     If the agent dies, the tmux server and everything inside it keep
    #     running. Cleanup must be explicit: ``tmux -L <socket> kill-server``
    #     was verified to kill the pane children as well.
    #   - tmux is an external dependency. It is absent on Windows and may be
    #     missing on minimal images, so any use must degrade gracefully rather
    #     than assume it exists.
    #   - Interactive control is possible: ``send-keys`` plus ``capture-pane``
    #     was verified to drive a shell and read its output, which is what makes
    #     this approach usable for long-running interactive work.
    try:
        stdout, stderr = process.communicate(input=subprocess_input, timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_process_tree(process)
        process.communicate()
        raise
    ret = (
        process.returncode,
        safe_decode(stdout),
        "" if no_need_stderr else safe_decode(stderr),
    )
    if need_error_log:
        if process.returncode != 0:
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
        "-o LogLevel=ERROR "
    )
    if port:
        options += f"-p {port}"

    cmd = format_cmd(cmd, remote=remote)
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
    cmd = format_cmd(cmd)
    env = build_env(env)
    p = subprocess.Popen(
        cmd,
        shell=isinstance(cmd, str),
        env=env,
        start_new_session=True,
    )
    return p.pid
