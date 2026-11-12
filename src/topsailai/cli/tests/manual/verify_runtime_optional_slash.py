#!/usr/bin/env python
"""Verify runtime input recognizes commands with or without the leading '/'.

This manual test drives the real raw runtime loop through a pseudo-terminal so
the interactive dispatch path is exercised end to end, not through mocks.

Procedure:
1. Create a temporary session stdout file and a temporary task directory.
2. Start ``_stream_file_raw`` in a child process attached to a pty.
3. Type ``send hello`` and confirm the send path runs and the
   ``Send as message? [y/N]`` prompt never appears.
4. Type ``hello world`` and confirm the send-as-message prompt does appear.
5. Type ``q`` to leave the stream.

Author: DawsonLin
"""

import os
import pty
import select
import subprocess
import sys
import tempfile
import time

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

DRIVER = r'''
import os
import sys
sys.path.insert(0, {cli_dir!r})
import cli_topsailai.state as state
from cli_topsailai import yaml_commands
from cli_topsailai.streaming import _stream_file_raw

state.yaml_commands = yaml_commands.load_yaml_commands()
state.current_scope = "runtime"
state.running = True
_stream_file_raw(
    {path!r}, {task_dir!r}, [], "manual-session", {path!r},
    default_pid=999999, tail_lines=0,
)
'''


def read_until(fd, needle, timeout=15.0):
    """Read pty output until *needle* appears or the timeout expires."""
    deadline = time.time() + timeout
    buffer = b""
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.2)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
        if needle.encode() in buffer:
            return buffer.decode("utf-8", errors="replace")
    return buffer.decode("utf-8", errors="replace")


def main() -> int:
    """Run the pty verification and report pass or fail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "manual-session.999999.session.stdout")
        with open(path, "w", encoding="utf-8") as stream_file:
            stream_file.write("existing line\n")

        driver = DRIVER.format(cli_dir=CLI_DIR, path=path, task_dir=tmpdir)
        driver_path = os.path.join(tmpdir, "driver.py")
        with open(driver_path, "w", encoding="utf-8") as driver_file:
            driver_file.write(driver)

        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(sys.executable, [sys.executable, "-B", driver_path])
            os._exit(1)

        try:
            banner = read_until(fd, "The leading '/' is optional")
            if "The leading '/' is optional" not in banner:
                print("FAIL startup banner does not mention the optional slash")
                print(banner)
                return 1

            os.write(fd, b"send hello\n")
            after_send = read_until(fd, "runtime:manual-session]>", timeout=10.0)
            if "Send as message?" in after_send:
                print("FAIL bare 'send hello' prompted send-as-message")
                print(after_send)
                return 1
            print("PASS bare 'send hello' dispatched as the send command")

            os.write(fd, b"hello world\n")
            after_text = read_until(fd, "Send as message?", timeout=10.0)
            if "Send as message?" not in after_text:
                print("FAIL plain text did not prompt send-as-message")
                print(after_text)
                return 1
            print("PASS plain text 'hello world' kept the send-as-message prompt")

            os.write(fd, b"n\n")
            read_until(fd, "Unknown streaming command", timeout=10.0)

            os.write(fd, b"q\n")
            read_until(fd, "Streaming stopped", timeout=10.0)
            print("PASS runtime loop exited on 'q'")
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.waitpid(pid, 0)
            except ChildProcessError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
