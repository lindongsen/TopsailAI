#!/usr/bin/env python3
"""Verify CJK editing through the raw runtime editor in a pseudo-terminal."""

import fcntl
import os
import pty
import select
import struct
import sys
import termios
import time

WORKSPACE = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, WORKSPACE)

from cli_topsailai.streaming import _build_runtime_prompt, _read_input_line_tty


def read_until(fd: int, needle: bytes, timeout: float = 5.0) -> bytes:
    """Read PTY output until a marker is observed or timeout is reached."""
    output = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            output.extend(os.read(fd, 4096))
            if needle in output:
                return bytes(output)
    raise TimeoutError(f"PTY marker not observed: {needle!r}; output={bytes(output)!r}")


def read_until_exit(fd: int, pid: int, timeout: float = 5.0) -> tuple[bytes, int]:
    """Read PTY output until the child exits or timeout is reached."""
    output = bytearray()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.05)
        if ready:
            try:
                output.extend(os.read(fd, 4096))
            except OSError:
                pass
        waited_pid, status = os.waitpid(pid, os.WNOHANG)
        if waited_pid == pid:
            return bytes(output), status
    os.kill(pid, 9)
    _, status = os.waitpid(pid, 0)
    raise TimeoutError(f"raw runtime editor did not exit: status={status}")


def main() -> int:
    """Drive Chinese input, cursor movement, and deletion through a PTY."""
    pid, fd = pty.fork()
    if pid == 0:
        prompt = _build_runtime_prompt("manual-cjk")
        result = _read_input_line_tty(prompt, already_raw=False)
        print(f"RESULT={result}", flush=True)
        os._exit(0)

    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
    try:
        initial_output = read_until(fd, b"runtime:manual-cjk]>")
        os.write(fd, "中文测试".encode("utf-8"))
        os.write(fd, b"\x1b[D\x1b[C\x7f\r")
        final_output, status = read_until_exit(fd, pid)
    except Exception:
        try:
            os.kill(pid, 9)
            os.waitpid(pid, 0)
        except (ChildProcessError, ProcessLookupError):
            pass
        raise
    finally:
        os.close(fd)

    text = (initial_output + final_output).decode("utf-8", errors="replace")
    expected = "RESULT=中文测"
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        print(f"FAIL child status={status}")
        return 1
    if expected not in text:
        print(f"FAIL expected {expected!r} in {text!r}")
        return 1
    if "中文测" not in text:
        print("FAIL edited Chinese text was not rendered")
        return 1
    print("PASS CJK input, movement, deletion, and result")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
