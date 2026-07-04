"""Streaming session helpers for the TopsailAI CLI."""

import errno
import os
import select
import stat
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional

from cli_topsailai.colors import (
    Colors,
    print_error,
    print_info,
    print_success,
    print_warning,
)
from cli_topsailai.constants import DEFAULT_TIMEOUT_SECONDS
from cli_topsailai.formatting import print_header
from cli_topsailai.log_files import (
    _build_pipe_path,
    _find_session_stdout_file,
    _get_pid_from_stdout_path,
    _parse_stdout_filename,
    _resolve_send_target_from_arg,
    get_file_pid,
)
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.process import register_process, unregister_process
import cli_topsailai.state as state


def stream_sessions(
    command: List[str],
    env: Optional[Dict[str, str]] = None,
    timeout: int = DEFAULT_TIMEOUT_SECONDS,
    poll_interval: float = 1.0,
) -> int:
    """
    Run a command and stream its stdout/stderr line by line.

    Args:
        command: Command and arguments to execute.
        env: Environment variables for the subprocess.
        timeout: Maximum runtime in seconds.
        poll_interval: Interval between output polls.

    Returns:
        Subprocess return code.
    """
    proc = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    start = time.time()
    try:
        while proc.poll() is None:
            if time.time() - start > timeout:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
                print_error("Streaming timed out")
                return 1
            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                print(line, end="")
            else:
                time.sleep(poll_interval)
        # Drain remaining output
        if proc.stdout:
            for line in proc.stdout:
                print(line, end="")
        return proc.returncode or 0
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        raise


def tail_session_log(
    session_id: str,
    lines: int = 20,
    follow: bool = False,
    log_dir: Optional[str] = None,
) -> int:
    """
    Tail the log file for a session.

    Args:
        session_id: Session identifier.
        lines: Number of trailing lines to display.
        follow: Whether to keep following new output.
        log_dir: Directory containing session logs.

    Returns:
        Exit code.
    """
    if log_dir is None:
        log_dir = os.path.join(get_topsailai_home(), "logs")
    log_path = os.path.join(log_dir, f"{session_id}.log")
    if not os.path.isfile(log_path):
        print_error(f"Log not found: {log_path}")
        return 1

    cmd = ["tail"]
    if follow:
        cmd.append("-f")
    cmd.extend(["-n", str(lines), log_path])
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        # Fallback pure-Python tail when `tail` is unavailable.
        with open(log_path, "r", encoding="utf-8") as fh:
            all_lines = fh.readlines()
        for line in all_lines[-lines:]:
            print(line, end="")
        if follow:
            print_warning("'tail' not available; follow mode is not supported")
        return 0


def stream_file(
    filepath: str,
    task_dir: str = "",
    log_files: Optional[List[dict]] = None,
    default_session_id: Optional[str] = None,
    default_stdout_path: Optional[str] = None,
) -> None:
    """
    Stream a log file in real-time, similar to ``tail -f``.

    Shows the last 100 lines, then follows new writes.  Supports ``q`` to
    quit, ``/send [message]`` to send a message to the watched session, or
    Ctrl+C for graceful exit.

    Args:
        filepath: Path to the log file to stream.
        task_dir: Task directory for resolving session targets.
        log_files: Current list of discovered log files.
        default_session_id: Session ID associated with the watched file.
        default_stdout_path: Exact stdout path for the watched session.
    """
    from cli_topsailai.state import running

    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' then Enter to quit, "
        f"type '/send [message]' then Enter to send a message, or Ctrl+C to exit.{Colors.RESET}\n"
    )

    try:
        subprocess.run(["tail", "-n", "100", filepath], check=False)
    except Exception:
        pass

    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            while running:
                chunk = f.read(4096)
                if chunk:
                    if hasattr(sys.stdout, "buffer"):
                        sys.stdout.buffer.write(chunk)
                        sys.stdout.buffer.flush()
                    else:
                        print(chunk.decode("utf-8", errors="replace"), end="")
                        sys.stdout.flush()
                else:
                    if sys.stdin.isatty():
                        readable, _, _ = select.select([sys.stdin], [], [], 0.05)
                        if readable:
                            try:
                                cmd_line = input().strip()
                            except (EOFError, KeyboardInterrupt):
                                break
                            if not cmd_line:
                                continue
                            lower = cmd_line.lower()
                            if lower in ("q", "quit"):
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}"
                                )
                                break
                            if lower.startswith("/"):
                                _handle_stream_command(
                                    cmd_line,
                                    task_dir,
                                    log_files or [],
                                    default_session_id,
                                    default_stdout_path,
                                )
                                continue
                            print(
                                f"{Colors.RED}[ERROR] Unknown streaming command: {cmd_line}. "
                                f"Use '/send [message]', '/help', or 'q'.{Colors.RESET}"
                            )
                    else:
                        time.sleep(0.05)
    except FileNotFoundError:
        print(f"{Colors.RED}[ERROR] File not found: {filepath}{Colors.RESET}")
    except PermissionError:
        print(f"{Colors.RED}[ERROR] Permission denied: {filepath}{Colors.RESET}")
    except KeyboardInterrupt:
        print(f"\n{Colors.YELLOW}[INFO] Interrupted by user.{Colors.RESET}")
    except Exception as e:
        print(f"{Colors.RED}[ERROR] Failed to stream file: {e}{Colors.RESET}")

    print(f"\n{Colors.CYAN}[INFO] Streaming stopped.{Colors.RESET}")


def _handle_stream_command(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """
    Execute a command entered while streaming a log file.

    Supports ``/send`` (defaulting to the watched session) and ``/help``.
    """
    if not cmd_line:
        return

    parts = cmd_line.split(None, 1)
    cmd = parts[0].lower()
    if cmd == "/send":
        _handle_stream_send(
            cmd_line,
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
        )
        return

    if cmd == "/help":
        print(
            f"\n{Colors.CYAN}[INFO] Streaming commands: "
            f"'q' then Enter to quit, '/send [message]' send to watched session, "
            f"'/help' show this help.{Colors.RESET}"
        )
        return

    print(
        f"{Colors.RED}[ERROR] Unknown streaming command: {cmd_line}. "
        f"Use '/send [message]', '/help', or 'q'.{Colors.RESET}"
    )


def _handle_stream_send(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """
    Handle ``/send`` while streaming, defaulting to the watched session.
    """
    if default_session_id is None:
        print(
            f"{Colors.RED}[ERROR] No session associated with this log file.{Colors.RESET}"
        )
        return

    rest = cmd_line[len("/send"):].strip()

    message: Optional[str] = None
    stdout_path = default_stdout_path
    session_id = default_session_id
    pid: Optional[int] = None

    if rest:
        sub_parts = rest.split(None, 1)
        first = sub_parts[0]
        target = _resolve_send_target_from_arg(first, log_files)
        if target is not None:
            session_id, stdout_path, pid = target
            if len(sub_parts) > 1:
                message = sub_parts[1]
        else:
            message = rest

    if message is None:
        message = _read_multiline_input_for_send()
        if message is None:
            return

    send_message_to_session(
        session_id, message, task_dir, stdout_path=stdout_path, pid=pid
    )


def _read_multiline_input_for_send() -> Optional[str]:
    """
    Read multi-line input until a standalone 'EOF' line is entered.

    Returns ``None`` if the user cancels with Ctrl+C.
    """
    print(
        f"{Colors.CYAN}[INFO] Enter message (type EOF on its own line to finish):{Colors.RESET}"
    )
    lines: List[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            print(f"\n{Colors.YELLOW}[INFO] Cancelled.{Colors.RESET}")
            return None
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)


def _format_pipe_payload(message: str) -> bytes:
    """
    Format a message for the pipe protocol.

    Ensures the message body ends with a newline, then appends the EOF
    marker on its own line.
    """
    if not message.endswith("\n"):
        message += "\n"
    if not message.endswith("EOF\n"):
        message += "EOF\n"
    return message.encode("utf-8")


def send_message_to_session(
    session_id: str,
    message: str,
    task_dir: str,
    timeout: float = 5.0,
    stdout_path: Optional[str] = None,
    pid: Optional[int] = None,
) -> bool:
    """
    Send a message to a running session through its named pipe.

    Session and task stdout files follow the conventions documented in
    README.md:
      - Session stdout: ``{session_id}.{pid}.session.stdout``
      - Task stdout: ``{session_id}.{pid}[.{other}].task.stdout``
      - ``topsailai`` as ``{session_id}`` means the session id is undefined
        and is displayed as ``(temp)``.

    PID resolution priority:
      1. ``pid`` argument when provided (e.g. the PID recorded in the task
         list entry selected by the user).
      2. PID parsed from the stdout filename (session stdout files contain
         the session PID; task stdout files contain the task child PID).
      3. PID discovered by scanning processes that currently have the stdout
         file open (``lsof`` / ``fuser``).

    Args:
        session_id: Target session identifier.
        message: Message text to send.
        task_dir: Task directory containing stdout/pipe files.
        timeout: Maximum seconds to wait for the receiver to open the pipe.
        stdout_path: Exact stdout file path when known (e.g. from numeric
            selection), used to target temporary sessions precisely.
        pid: Optional process PID known to own the session. When provided,
            this takes precedence over filename parsing and process scanning.

    Returns:
        ``True`` if the message was sent, ``False`` otherwise.
    """
    if stdout_path is None:
        stdout_path = _find_session_stdout_file(task_dir, session_id)
        if stdout_path is None:
            print(
                f"{Colors.RED}[ERROR] No stdout file found for session '{session_id}'.{Colors.RESET}"
            )
            return False
    elif stdout_path.endswith(".task.stdout"):
        # Task stdout files use the child task PID in the filename
        # ({session_id}.{pid}[.{other}].task.stdout), not the session PID.
        # Resolve the canonical session stdout file for the same session so
        # the named pipe path uses the session process PID.
        task_session_id, _ = _parse_stdout_filename(os.path.basename(stdout_path))
        resolved_session_id = (
            task_session_id if task_session_id is not None else session_id
        )
        resolved_stdout = _find_session_stdout_file(task_dir, resolved_session_id)
        if resolved_stdout is None:
            print(
                f"{Colors.RED}[ERROR] No session stdout file found for session "
                f"'{resolved_session_id}'.{Colors.RESET}"
            )
            return False
        stdout_path = resolved_stdout
    elif not os.path.isfile(stdout_path):
        print(
            f"{Colors.RED}[ERROR] Stdout file not found: {stdout_path}.{Colors.RESET}"
        )
        return False

    # Resolve the session PID using the documented priority:
    #   1. Caller-supplied pid (e.g. from the task list entry).
    #   2. PID embedded in the stdout filename.
    #   3. PID from scanning open files (lsof / fuser).
    pipe_path: Optional[str] = None

    if pid is not None:
        candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
        if os.path.exists(candidate_pipe):
            pipe_path = candidate_pipe

    if pipe_path is None:
        pid = _get_pid_from_stdout_path(stdout_path)
        if pid is not None:
            candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
            if os.path.exists(candidate_pipe):
                pipe_path = candidate_pipe

    if pipe_path is None:
        pid = get_file_pid(stdout_path)
        if pid is not None:
            candidate_pipe = _build_pipe_path(task_dir, session_id, pid)
            if os.path.exists(candidate_pipe):
                pipe_path = candidate_pipe

    if pipe_path is None:
        print(
            f"{Colors.RED}[ERROR] Session '{session_id}' does not appear to be running "
            f"(no process owns its stdout file).{Colors.RESET}"
        )
        return False

    if not stat.S_ISFIFO(os.stat(pipe_path).st_mode):
        print(
            f"{Colors.RED}[ERROR] Path exists but is not a named pipe: {pipe_path}.{Colors.RESET}"
        )
        return False

    payload = _format_pipe_payload(message)
    fd: Optional[int] = None
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fd = os.open(pipe_path, os.O_WRONLY | os.O_NONBLOCK)
                break
            except OSError as exc:
                if exc.errno == errno.ENXIO:
                    if time.monotonic() >= deadline:
                        print(
                            f"{Colors.RED}[ERROR] Timed out waiting for session to open "
                            f"the pipe for reading.{Colors.RESET}"
                        )
                        return False
                    time.sleep(0.1)
                    continue
                raise
        os.write(fd, payload)
        print(
            f"{Colors.GREEN}[INFO] Message sent to session '{session_id}' via "
            f"{pipe_path} ({len(payload)} bytes).{Colors.RESET}"
        )
        return True
    except OSError as exc:
        print(
            f"{Colors.RED}[ERROR] Failed to write to pipe {pipe_path}: {exc}{Colors.RESET}"
        )
        return False
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

def handle_send_command(
    user_input: str, task_dir: str, log_files: List[dict]
) -> None:
    """
    Parse and execute the ``/send`` command.

    In session scope, the argument is the message.  In workspace scope, the
    first argument is a session ID or 1-based index, and the remainder is the
    message.  When no message is provided, interactive multi-line input is used.
    """
    stdout_path: Optional[str] = None
    pid: Optional[int] = None
    parts = user_input.split(None, 1)
    if len(parts) < 2:
        if state.current_scope == "session" and state.current_session_id:
            session_id = state.current_session_id
            message: Optional[str] = None
        else:
            print(
                f"{Colors.RED}[ERROR] Usage: /send <session_id_or_index> [message...] "
                f"or enter a session scope first with /cd.{Colors.RESET}"
            )
            return
    else:
        arg = parts[1]
        if state.current_scope == "session" and state.current_session_id:
            session_id = state.current_session_id
            message = arg
        else:
            sub_parts = arg.split(None, 1)
            target = _resolve_send_target_from_arg(sub_parts[0], log_files)
            if target is None:
                print(
                    f"{Colors.RED}[ERROR] Could not resolve session from "
                    f"'{sub_parts[0]}'.{Colors.RESET}"
                )
                return
            session_id, stdout_path, pid = target
            message = sub_parts[1] if len(sub_parts) > 1 else None

    if message is None:
        message = _read_multiline_input_for_send()
        if message is None:
            return

    if stdout_path is not None:
        send_message_to_session(
            session_id, message, task_dir, stdout_path=stdout_path, pid=pid
        )
    else:
        send_message_to_session(session_id, message, task_dir, pid=pid)
