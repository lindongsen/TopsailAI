"""Streaming session helpers for the TopsailAI CLI."""

import errno
import os
import select
import stat
import subprocess
import sys
import time
from typing import Any, Callable, Dict, List, Optional

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
from cli_topsailai import yaml_commands
import cli_topsailai.state as state


def _extract_session_id_from_path(path: str) -> Optional[str]:
    """Extract the session_id from a stdout file path, if possible."""
    session_id, _ = _parse_stdout_filename(os.path.basename(path))
    return session_id


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


def _can_use_curses() -> bool:
    """Return True if the two-pane curses UI can be used."""
    from cli_topsailai.tui import is_curses_available

    return is_curses_available()


def stream_file(
    filepath: str,
    task_dir: str = "",
    log_files: Optional[List[dict]] = None,
    default_session_id: Optional[str] = None,
    default_stdout_path: Optional[str] = None,
    runtime_raw: bool = False,
    tail_lines: int = 100,
) -> None:
    """
    Stream a log file in real-time, similar to ``tail -f``.

    Shows the last 100 lines, then follows new writes.  Supports ``q`` to
    quit, ``/send [message]`` to send a message to the watched session,
    ``/ctx.btw [message]`` to inject an agent2llm message, or Ctrl+C for
    graceful exit.

    When ``runtime_raw`` is True, a simple curses-free raw streaming mode is
    used instead of the two-pane curses UI or legacy single-pane fallback.
    The last ``tail_lines`` lines are echoed on startup.

    When the terminal supports it and ``runtime_raw`` is False, a two-pane
    curses UI is used so that the log scrolls in the top pane while a fixed
    input bar stays at the bottom.  In non-TTY environments or when curses is
    unavailable, the legacy single-pane mode is used instead.

    While streaming, the interactive scope is temporarily set to
    ``"runtime"`` so that scope-aware YAML commands target the watched
    session automatically.

    Args:
        filepath: Path to the log file to stream.
        task_dir: Task directory for resolving session targets.
        log_files: Current list of discovered log files.
        default_session_id: Session ID associated with the watched file.
        default_stdout_path: Exact stdout path for the watched session.
        runtime_raw: Use the simple curses-free raw streaming mode.
        tail_lines: Number of recent log lines to echo on startup.
    """
    previous_scope = state.current_scope
    previous_session_id = state.current_session_id
    if default_session_id is not None:
        state.current_scope = "runtime"
        state.current_session_id = default_session_id

    try:
        if runtime_raw:
            _stream_file_raw(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
                tail_lines=tail_lines,
            )
        elif _can_use_curses():
            _run_curses_ui(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
            )
        else:
            _stream_file_legacy(
                filepath,
                task_dir,
                log_files or [],
                default_session_id,
                default_stdout_path,
            )
    finally:
        state.current_scope = previous_scope
        state.current_session_id = previous_session_id


def _run_curses_ui(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """Run the two-pane curses UI for streaming."""
    from cli_topsailai.tui import CursesStreamUI

    ui: Any = None  # type: ignore[assignment]
    real_handler: Callable[[str], bool] = lambda _: True

    def command_handler(cmd_line: str) -> bool:
        return real_handler(cmd_line)

    ui = CursesStreamUI(
        filepath=filepath,
        task_dir=task_dir,
        log_files=log_files,
        default_session_id=default_session_id,
        default_stdout_path=default_stdout_path,
        command_handler=command_handler,
    )
    real_handler = _build_stream_command_handler(
        ui,
        task_dir,
        log_files,
        default_session_id,
        default_stdout_path,
    )
    ui.run()


class _CursesOutputCapture:
    """Capture stdout/stderr writes and forward them to a curses UI."""

    def __init__(self, ui: Any) -> None:
        self.ui = ui
        self._buffer: List[str] = []
        self._original_stdout = sys.stdout
        self._original_stderr = sys.stderr

    def write(self, text: str) -> None:
        self._buffer.append(text)
        if "\n" in text:
            self._flush()

    def flush(self) -> None:
        self._flush()
        if hasattr(self._original_stdout, "flush"):
            self._original_stdout.flush()

    def _flush(self) -> None:
        if not self._buffer:
            return
        data = "".join(self._buffer)
        self._buffer = []
        for line in data.splitlines():
            if line:
                self.ui.append_status(line)

    def __enter__(self) -> "_CursesOutputCapture":
        sys.stdout = self  # type: ignore[assignment]
        sys.stderr = self  # type: ignore[assignment]
        return self

    def __exit__(self, *args: Any) -> None:
        self._flush()
        sys.stdout = self._original_stdout
        sys.stderr = self._original_stderr


def _build_stream_command_handler(
    ui: Any,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> Any:
    """Build the command callback used by the curses UI."""

    def _multi_line_input_provider(prompt: str) -> Optional[str]:
        return ui.read_multi_line_blocking(prompt)

    def handler(cmd_line: str) -> bool:
        lower = cmd_line.lower()
        if lower in ("q", "quit", "cd", "/cd"):
            return False
        with _CursesOutputCapture(ui):
            if lower.startswith("/"):
                _handle_stream_command(
                    cmd_line,
                    task_dir,
                    log_files,
                    default_session_id,
                    default_stdout_path,
                    input_provider=_multi_line_input_provider,
                )
            else:
                _prompt_send_as_message(
                    cmd_line,
                    task_dir,
                    log_files,
                    default_session_id,
                    default_stdout_path,
                    input_provider=_multi_line_input_provider,
                    output_callback=ui.append_status,
                    input_callback=ui.read_multi_line_blocking,
                )
        return True

    return handler


def _prompt_send_as_message(
    raw_input: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
    output_callback: Optional[Callable[[str], None]] = None,
    input_callback: Optional[Callable[[str], Optional[str]]] = None,
) -> bool:
    """
    Ask the user whether to send unrecognized runtime input as a message.

    If the user confirms, the raw input is forwarded to the existing ``/send``
    mechanism.  If the user declines, the original "Unknown command" behavior
    is preserved.

    Returns ``True`` if the input was handled (sent or declined), ``False``
    when the user cancels the prompt.
    """
    prompt = "Send as message? [y/N]: "
    if input_callback is not None:
        answer = input_callback(prompt)
    else:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            return False

    if answer is None:
        return False

    answer_lower = answer.strip().lower()
    if answer_lower in ("y", "yes"):
        _handle_stream_command(
            f"/send {raw_input}",
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
            input_provider=input_provider,
        )
        return True

    if output_callback is not None:
        output_callback(
            f"[ERROR] Unknown streaming command: {raw_input}. "
            f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'."
        )
    else:
        print(
            f"{Colors.RED}[ERROR] Unknown streaming command: {raw_input}. "
            f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'.{Colors.RESET}"
        )
    return True


def _tail_file(path: str, tail_lines: int) -> None:
    """Print the most recent ``tail_lines`` lines of ``path`` to stdout."""
    n = max(0, tail_lines)
    try:
        subprocess.run(
            ["tail", "-n", str(n), path],
            check=False,
        )
        return
    except FileNotFoundError:
        pass
    except Exception:
        pass

    # Fallback pure-Python tail when the system ``tail`` is unavailable.
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            all_lines = fh.readlines()
        for line in all_lines[-n:]:
            print(line, end="")
    except Exception:
        pass


def _read_input_line(prompt: str = "") -> Optional[str]:
    """Read a single line from stdin, returning None on EOF/KeyboardInterrupt."""
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        return None


def _dispatch_input(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> bool:
    """Handle a single raw-mode user command.

    Returns ``False`` when the user wants to leave the stream (q/quit/exit/cd).
    """
    lower = cmd_line.lower()
    if lower in ("q", "quit", "exit"):
        print(f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}")
        return False
    if lower in ("cd", "/cd"):
        print(
            f"\n{Colors.YELLOW}[INFO] Return to workspace scope requested.{Colors.RESET}"
        )
        return False
    if lower.startswith("/"):
        _handle_stream_command(
            cmd_line,
            task_dir,
            log_files,
            default_session_id,
            default_stdout_path,
        )
        return True
    return _prompt_send_as_message(
        cmd_line,
        task_dir,
        log_files,
        default_session_id,
        default_stdout_path,
        input_provider=None,
        output_callback=None,
        input_callback=None,
    )


def _stream_file_raw(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    tail_lines: int = 100,
) -> None:
    """Raw curses-free stream implementation used when ``--runtime-raw`` is set."""

    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' then Enter to quit, "
        f"type '/send [message]' to send a message, "
        f"'/ctx.btw [message]' to inject an agent2llm message, or Ctrl+C to exit.{Colors.RESET}\n"
    )
    session_label = default_session_id or "(temp)"
    prompt = f"[runtime:{session_label}]> "

    _tail_file(filepath, tail_lines)

    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            while state.running:
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
                            cmd_line = _read_input_line(prompt)
                            if cmd_line is None:
                                break
                            if not cmd_line:
                                continue
                            if not _dispatch_input(
                                cmd_line,
                                task_dir,
                                log_files,
                                default_session_id,
                                default_stdout_path,
                            ):
                                break
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


def _stream_file_legacy(
    filepath: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
) -> None:
    """Legacy single-pane stream implementation for non-TTY environments."""

    filename = os.path.basename(filepath)
    print_header(f"Streaming: {filename}")
    print(
        f"{Colors.YELLOW}[INFO] Press 'q' then Enter to quit, "
        f"type '/send [message]' to send a message, "
        f"'/ctx.btw [message]' to inject an agent2llm message, or Ctrl+C to exit.{Colors.RESET}\n"
    )

    session_label = default_session_id or "(temp)"
    prompt = f"[runtime:{session_label}]> "

    try:
        subprocess.run(["tail", "-n", "100", filepath], check=False)
    except Exception:
        pass

    try:
        with open(filepath, "rb") as f:
            f.seek(0, 2)
            while state.running:
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
                            cmd_line = _read_input_line(prompt)
                            if cmd_line is None:
                                break
                            if not cmd_line:
                                continue
                            lower = cmd_line.lower()
                            if lower in ("q", "quit", "exit"):
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Quit requested.{Colors.RESET}"
                                )
                                break
                            if lower in ("cd", "/cd"):
                                print(
                                    f"\n{Colors.YELLOW}[INFO] Return to workspace scope requested.{Colors.RESET}"
                                )
                                break
                            if lower.startswith("/"):
                                _handle_stream_command(
                                    cmd_line,
                                    task_dir,
                                    log_files,
                                    default_session_id,
                                    default_stdout_path,
                                )
                                continue
                            _prompt_send_as_message(
                                cmd_line,
                                task_dir,
                                log_files,
                                default_session_id,
                                default_stdout_path,
                                input_provider=None,
                                output_callback=None,
                                input_callback=None,
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
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Execute a command entered while streaming a log file.

    Supports ``/send`` (defaulting to the watched session), ``/ctx.btw``
    (inject an agent2llm message), and ``/help``.

    Args:
        input_provider: Optional callable used to collect multi-line input
            in environments where ``input()`` is not available (e.g. the
            curses UI).  Receives a prompt string and returns the collected
            text, or ``None`` if the user cancelled.
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
            input_provider=input_provider,
        )
        return

    if cmd == "/ctx.btw":
        _handle_stream_ctx_btw(cmd_line, task_dir, input_provider=input_provider)
        return

    if cmd == "/help":
        print(
            "Available commands:\n"
            "  /send [message]      - Send a message to the watched session\n"
            "  /ctx.btw [message]   - Inject an agent2llm message\n"
            "  /help                - Show this help message\n"
            "  q / quit / exit      - Stop streaming\n"
            "  cd or /cd            - Return to workspace scope"
        )
        return

    print(
        f"{Colors.RED}[ERROR] Unknown streaming command: {cmd_line}. "
        f"Use '/send [message]', '/ctx.btw [message]', '/help', 'q', 'quit', 'exit', or 'cd'.{Colors.RESET}"
    )


def _handle_stream_send(
    cmd_line: str,
    task_dir: str,
    log_files: List[dict],
    default_session_id: Optional[str],
    default_stdout_path: Optional[str],
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Handle ``/send`` while streaming, defaulting to the watched session.

    In runtime scope the watched session is already known, so any text after
    ``/send`` is treated as the message body.  When no message is provided,
    multi-line input is collected through the available input provider.
    """
    if default_session_id is None:
        print(
            f"{Colors.RED}[ERROR] No session associated with this log file.{Colors.RESET}"
        )
        return

    message: Optional[str] = cmd_line[len("/send"):].strip() or None

    if message is None:
        if input_provider is not None:
            message = input_provider(
                f"{Colors.CYAN}[INFO] Enter /send message (Ctrl+D to finish):{Colors.RESET}"
            )
        else:
            message = _read_multiline_input_for_send()
        if message is None:
            return

    send_message_to_session(
        default_session_id, message, task_dir, stdout_path=default_stdout_path
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


def _handle_stream_ctx_btw(
    cmd_line: str,
    task_dir: str,
    input_provider: Optional[Callable[[str], Optional[str]]] = None,
) -> None:
    """
    Handle ``/ctx.btw`` while streaming by delegating to the YAML command.

    The ``runtime`` scope and watched session ID are already set by
    ``stream_file``, so ``match_yaml_command`` can resolve the target
    session automatically.  Supports inline arguments as well as
    interactive multi-line input when no argument is provided.
    """
    matched = yaml_commands.match_yaml_command(cmd_line, task_dir)
    if matched is None:
        print(
            f"{Colors.RED}[ERROR] Could not match /ctx.btw command. "
            f"Is there a session associated with this log file?{Colors.RESET}"
        )
        return
    instruction, variables = matched

    # When no inline message is provided and an external input provider is
    # available, use it to collect multi-line input without blocking the UI.
    if (
        input_provider is not None
        and not variables.get("message", "").strip()
        and instruction.get("shell", "")
    ):
        message = input_provider(
            f"{Colors.CYAN}[INFO] Enter /ctx.btw message (Ctrl+D to finish):{Colors.RESET}"
        )
        if message is None:
            print(f"\n{Colors.YELLOW}[INFO] Cancelled.{Colors.RESET}")
            return
        message = message.strip()
        if not message:
            print(f"{Colors.RED}[ERROR] Message cannot be empty.{Colors.RESET}")
            return
        variables = dict(variables)
        variables["message"] = message

    yaml_commands.handle_yaml_command(instruction, variables)


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
      1. ``pid`` argument when provided (e.g. from the task list entry).
      2. PID parsed from the stdout filename.
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
