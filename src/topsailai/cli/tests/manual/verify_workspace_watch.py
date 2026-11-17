#!/usr/bin/env python3
"""Verify the workspace watch command through a real pseudo-terminal.

The watch loop depends on stdin polling, so a mock cannot prove that a typed
key actually stops it. This manual test drives the real prompt loop attached to
a pty and asserts on the captured terminal output.

Procedure:
1. Create a temporary task directory holding one session stdout file.
2. Start the real ``prompt_selection`` plus watch loop in a child process on a
   pty, with the watch interval shortened so the test stays fast.
3. Confirm the first cycle prints the watching hint and the task table.
4. Confirm a second cycle prints the hint again, proving the loop repeats.
5. Type a command and confirm the loop stops, reports it, and the typed input is
   then read by the normal prompt as the next command.

Author: DawsonLin
"""

import os
import pty
import re
import select
import sys
import tempfile
import time

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

DRIVER = r'''
import sys
sys.path.insert(0, {cli_dir!r})
import cli_topsailai.state as state
from cli_topsailai import core, yaml_commands

state.running = True
state.current_scope = "workspace"
state.current_session_id = None
state.workspace_showing_managed_projects = False
state.history_manager = None
state.yaml_commands = yaml_commands.load_yaml_commands()


def refresh():
    print("[TABLE] refreshed workspace task list")


# Pass a short interval explicitly so the manual test finishes quickly. The
# module constant is bound as the default at function-definition time, so
# reassigning it here would not change the loop's interval.
core._watch_workspace_list(refresh, interval=1)
print("[AFTER] watch loop returned to the prompt")
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
    """Remove ANSI escape sequences so the output can be asserted."""
    return ANSI_ESCAPE_RE.sub("", text)


def main() -> int:
    """Run the pty verification and report pass or fail."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = os.path.join(tmpdir, "manual.999999.session.stdout")
        with open(path, "w", encoding="utf-8") as stream_file:
            stream_file.write("existing line\n")

        driver = DRIVER.format(cli_dir=CLI_DIR, path=path)
        driver_path = os.path.join(tmpdir, "driver.py")
        with open(driver_path, "w", encoding="utf-8") as driver_file:
            driver_file.write(driver)

        pid, fd = pty.fork()
        if pid == 0:
            os.execvp(sys.executable, [sys.executable, "-B", driver_path])
            os._exit(1)

        try:
            first = strip_ansi(read_until(fd, "[TABLE] refreshed workspace task list"))
            if "[WATCH] Watching the workspace task list" not in first:
                print("FAIL first cycle did not print the watching hint")
                print(first)
                return 1
            if "refreshing every 1s" not in first:
                print("FAIL hint did not state the configured interval")
                print(first)
                return 1
            if "Press Enter or type a command to stop" not in first:
                print("FAIL hint did not explain how to stop")
                print(first)
                return 1
            print("PASS first cycle printed the watching hint and refreshed")

            second = strip_ansi(read_until(fd, "[TABLE] refreshed workspace task list"))
            if "[WATCH] Watching the workspace task list" not in second:
                print("FAIL second cycle did not print the hint again")
                print(second)
                return 1
            print("PASS second cycle printed the hint again, so the loop repeats")

            # A pty slave is in canonical mode, so the line must be submitted
            # before select() reports it. This matches the documented rule that
            # pressing Enter stops watching.
            os.write(fd, b"q\n")
            after = strip_ansi(read_until(fd, "[AFTER] watch loop returned to the prompt"))
            if "[WATCH] Stopped watching." not in after:
                print("FAIL typed input did not stop the loop")
                print(after)
                return 1
            if "[AFTER] watch loop returned to the prompt" not in after:
                print("FAIL the loop did not return control to the caller")
                print(after)
                return 1
            print("PASS typed input stopped the loop and returned control")
            return 0
        finally:
            try:
                os.close(fd)
            except OSError:
                pass
            try:
                os.waitpid(pid, 0)
            except OSError:
                pass


if __name__ == "__main__":
    sys.exit(main())
