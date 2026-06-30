#!/usr/bin/env python3
"""
Manual test script for topsailai.workspace.input_tool.input_message.

Usage:
    SESSION_ID=test python /TopsailAI/src/topsailai/tests/manual/test_input_message.py

This script constructs a minimal mock HookInstruction so that input_message()
can run without the full agent framework. It then enters a loop reading user
input and echoing the returned message.
"""

import os
import sys

# Ensure the project source is on PYTHONPATH when running directly.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from topsailai.workspace.input_tool import input_message


class MockHookInstruction:
    """Minimal stand-in for workspace.hook_instruction.HookInstruction."""

    def __init__(self):
        self.hook_map = {}

    def exist_hook(self, message: str) -> bool:
        return False

    def call_hook(self, message: str):
        return None

    def show_help(self, hook_name: str | None = None):
        print("[mock hooks: no commands registered]")
def _print_runtime_header() -> None:
    """Print PID, session, and relevant environment/runtime information."""
    env = os.environ
    print("=" * 72)
    print("Manual test for workspace.input_tool.input_message")
    print(f"PID              : {os.getpid()}")
    print(f"SESSION_ID       : {env.get("SESSION_ID") or env.get('TOPSAILAI_SESSION_ID', '<unset>')}")
    print(f"TOPSAILAI_HOME   : {env.get('TOPSAILAI_HOME', '<unset>')}")
    print(f"TOPSAILAI_INPUT_PIPE_ENABLED : {env.get('TOPSAILAI_INPUT_PIPE_ENABLED', '<unset>')}")
    print(f"TOPSAILAI_CHAT_MULTI_LINE    : {env.get('TOPSAILAI_CHAT_MULTI_LINE', '<unset>')}")
    print(f"WORK_FOLDER      : {env.get('TOPSAILAI_WORK_FOLDER', '<unset>')}")
    print(
        f"PROJECT_WORKSPACE: "
        f"{env.get('TOPSAILAI_PROJECT_WORKSPACE', env.get('TOPSAILAI_PROJECT_FOLDER', '<unset>'))}"
    )
    print(f"TOPSAILAI_PWD    : {env.get('TOPSAILAI_PWD', '<unset>')}")
    print(f"AGENT_NAME       : {env.get('TOPSAILAI_AGENT_NAME', '<unset>')}")
    print(f"HUMAN_NAME       : {env.get('TOPSAILAI_HUMAN_NAME', '<unset>')}")
    print(f"CWD              : {os.getcwd()}")
    print(f"PYTHON           : {sys.executable}")
    print("-" * 72)
    print("Type messages below. Use Ctrl+C to quit.")
    print("=" * 72)


def main() -> int:
    _print_runtime_header()

    hook = MockHookInstruction()

    while True:
        try:
            message = input_message(tips="Your input:", hook=hook)
        except (EOFError, KeyboardInterrupt):
            print("\n[exiting]")
            break

        print(f"[RETURNED] {message!r}")
        print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
