#!/usr/bin/env python
"""Verify TAB completion reaches command aliases in the raw runtime editor.

This manual test drives the real raw runtime loop through a pseudo-terminal, so
the interactive TAB path is exercised end to end instead of through mocks.

Procedure:
1. Create a temporary session stdout file and a temporary task directory.
2. Start ``_stream_file_raw`` in a child process attached to a pty.
3. Type ``mode`` then TAB and confirm the input buffer becomes ``model``, the
   bare spelling of the runtime alias ``/agent.models``.
4. Erase the buffer with backspaces, type ``exi`` then TAB and confirm the
   buffer becomes ``exit``, the alias of ``q``/``quit``.
5. Press Enter and confirm the completed ``exit`` is dispatched as the quit
   command, so the stream stops.

Author: DawsonLin
"""

import os
import pty
import re
import select
import subprocess
import sys
import tempfile
import time

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

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


def read_for(fd, seconds):
    """Read pty output for *seconds* and return everything received."""
    deadline = time.time() + seconds
    buffer = b""
    while time.time() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.1)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 4096)
        except OSError:
            break
        if not chunk:
            break
        buffer += chunk
    return buffer.decode("utf-8", errors="replace")

def strip_ansi(text):
    """Remove ANSI escape sequences so the input buffer can be asserted."""
    return ANSI_ESCAPE_RE.sub("", text)


def normalize(text):
    """Remove ANSI escapes and pty row terminators from *text*.

    A pty slave emits a carriage return and line feed after every character it
    relays, so the repainted input buffer arrives interleaved with ``\\r\\n``.
    Removing those bytes leaves the logical screen text, which is what the
    assertion needs; a missing completion still leaves the buffer without the
    completed spelling, so the check stays sensitive.
    """
    return strip_ansi(text).replace("\r", "").replace("\n", "")


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
                print("FAIL startup banner did not appear")
                print(strip_ansi(banner))
                return 1

            # Case 1: a bare runtime alias must complete to its bare spelling.
            os.write(fd, b"mode")
            read_for(fd, 0.5)
            os.write(fd, b"\t")
            after_tab = normalize(read_for(fd, 1.0))
            if "> model" not in after_tab:
                print("FAIL TAB did not complete 'mode' to 'model'")
                print(repr(after_tab))
                return 1
            print("PASS TAB completed bare alias 'mode' to 'model'")

            # Clear the buffer so the next case starts from an empty line.
            os.write(fd, b"\x7f" * len("model"))
            read_for(fd, 0.5)

            # Case 2: the quit alias must complete and then dispatch.
            os.write(fd, b"exi")
            read_for(fd, 0.5)
            os.write(fd, b"\t")
            after_exit_tab = normalize(read_for(fd, 1.0))
            if "> exit" not in after_exit_tab:
                print("FAIL TAB did not complete 'exi' to 'exit'")
                print(repr(after_exit_tab))
                return 1
            print("PASS TAB completed alias 'exi' to 'exit'")

            os.write(fd, b"\n")
            after_enter = normalize(read_until(fd, "Streaming stopped", timeout=10.0))
            if "Quit requested" not in after_enter:
                print("FAIL completed 'exit' was not dispatched as the quit command")
                print(repr(after_enter))
                return 1
            if "Streaming stopped" not in after_enter:
                print("FAIL stream did not stop after the completed 'exit'")
                print(repr(after_enter))
                return 1
            print("PASS completed 'exit' dispatched as quit and the stream stopped")
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
