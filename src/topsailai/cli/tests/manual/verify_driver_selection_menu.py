#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Manually verify interactive driver selection in topsailai_launch_agent.

Drives the real launcher through a pseudo-terminal so the TTY-only selection
paths are exercised end to end, then asserts on the captured terminal output.

Author: DawsonLin
"""

import os
import pty
import select
import shutil
import sys
import tempfile
import time

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LAUNCHER = os.path.join(CLI_DIR, "topsailai_launch_agent.py")

SETTINGS = """ai_agent_driver: "topsailai_agent_chats"
workspace: "."
context:
  _:
    - "base.md"
  default:
    - "default.md"
  memo:
    - "memo.md"
environment:
  _:
    TOPSAILAI_INTERACTIVE_MODE: "1"
  default:
    TOPSAILAI_AGENT_DRIVER: "ai-team-flow-dev"
  memo:
    TOPSAILAI_AGENT_DRIVER: "ai-team-flow-dev"
"""



def _read_until(fd, marker, timeout=20.0):
    """Read terminal output until *marker* appears or the timeout expires."""
    deadline = time.time() + timeout
    chunks = []
    while time.time() < deadline:
        ready, _, _ = select.select([fd], [], [], 0.2)
        if not ready:
            continue
        try:
            data = os.read(fd, 4096)
        except OSError:
            break
        if not data:
            break
        chunks.append(data.decode("utf-8", "replace"))
        if marker in "".join(chunks):
            return "".join(chunks)
    return "".join(chunks)


def _run(answers, argv_extra=(), timeout=20.0):
    """Run the launcher in a PTY, feeding *answers* one line at a time."""
    workspace = tempfile.mkdtemp(prefix="topsailai-driver-menu-")
    try:
        os.makedirs(os.path.join(workspace, ".topsailai"), exist_ok=True)
        with open(
            os.path.join(workspace, ".topsailai", "settings.yaml"), "w", encoding="utf-8"
        ) as handle:
            handle.write(SETTINGS)
        for name in ("base.md", "default.md", "memo.md"):
            with open(os.path.join(workspace, name), "w", encoding="utf-8") as handle:
                handle.write(f"# {name}\n")

        pid, fd = pty.fork()
        if pid == 0:
            os.chdir(workspace)
            os.execv(
                sys.executable,
                [sys.executable, LAUNCHER, "--dry-run", *argv_extra],
            )
            os._exit(127)

        output = _read_until(fd, "Select context item")
        for answer in answers:
            os.write(fd, (answer + "\n").encode())
            output += _read_until(fd, "Select context item", timeout=5.0)
        output += _read_until(fd, "Dry Run Mode", timeout=timeout)
        output += _read_until(fd, "\x00", timeout=3.0)
        os.close(fd)
        os.waitpid(pid, 0)
        return output
    finally:
        shutil.rmtree(workspace, ignore_errors=True)


def _check(label, output, expected, unexpected=()):
    """Assert that *expected* appears and no *unexpected* text appears."""
    if expected not in output:
        raise AssertionError(f"{label}: missing {expected!r}\n--- output ---\n{output}")
    for text in unexpected:
        if text in output:
            raise AssertionError(f"{label}: unexpected {text!r}\n--- output ---\n{output}")
    print(f"PASS {label}")


def _launched_env_section(output):
    """Return only the dry-run merged-environment section of the output.

    The item page legitimately lists each item's configured
    TOPSAILAI_AGENT_DRIVER, so environment assertions must be scoped to the
    section that reports what the child actually receives.
    """
    marker = "Environment variables (merged from base and item):"
    if marker not in output:
        raise AssertionError(
            f"missing dry-run environment section\n--- output ---\n{output}"
        )
    return output.split(marker, 1)[1]


def main():
    """Run the interactive driver-selection scenarios."""
    # Menu choice wins over the item environment (ai-team-flow-dev).
    # Option 1 is the current driver (topsailai_agent_chats), option 2 is
    # topsailai_agent_plan_tasks.
    output = _run(["d", "2", "memo"])
    _check("menu opens from item page", output, "Select the agent driver to launch")
    _check("item page re-rendered", output, "Multiple context items are configured")
    _check("chosen driver launched", output, "Command: topsailai_agent_plan_tasks")
    launched_env = _launched_env_section(output)
    _check(
        "menu choice overrides item env",
        launched_env,
        "TOPSAILAI_AGENT_DRIVER=topsailai_agent_plan_tasks",
        unexpected=("TOPSAILAI_AGENT_DRIVER=ai-team-flow-dev",),
    )

    # Returning from the menu keeps the settings.yaml driver.
    output = _run(["d", "b", "memo"])
    _check("back keeps item env driver", output, "Command: ai-team-flow-dev")

    # Not using the menu preserves the historical priority order.
    output = _run(["memo"])
    _check("no menu keeps historical priority", output, "Command: ai-team-flow-dev")

    print("ALL MANUAL CHECKS PASSED")
    return 0

if __name__ == "__main__":
    sys.exit(main())
