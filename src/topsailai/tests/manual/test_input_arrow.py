#!/usr/bin/env python3
"""
Manual test script for arrow-key / readline behavior in input_message.

Usage:
    SESSION_ID=test TOPSAILAI_INPUT_PIPE_ENABLED=1 ./tests/manual/test_input_arrow.py
    SESSION_ID=test TOPSAILAI_CHAT_MULTI_LINE=1 ./tests/manual/test_input_arrow.py
    SESSION_ID=test TOPSAILAI_INPUT_PIPE_ENABLED=1 TOPSAILAI_CHAT_MULTI_LINE=1 ./tests/manual/test_input_arrow.py

This script is intentionally simple: it calls input_message() once, prints the
returned repr, and exits.  This lets tmux send-keys drive it deterministically.
"""

import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from topsailai.workspace.input_tool import input_message


class MockHookInstruction:
    def __init__(self):
        self.hook_map = {}

    def exist_hook(self, message: str) -> bool:
        return False

    def call_hook(self, message: str):
        return None

    def show_help(self, hook_name: str | None = None):
        print("[mock hooks: no commands registered]")


def main() -> int:
    env = os.environ
    print("=" * 72)
    print("Manual test for arrow-key / readline behavior")
    print(f"PID              : {os.getpid()}")
    print(f"SESSION_ID       : {env.get('SESSION_ID') or env.get('TOPSAILAI_SESSION_ID', '<unset>')}")
    print(f"TOPSAILAI_INPUT_PIPE_ENABLED : {env.get('TOPSAILAI_INPUT_PIPE_ENABLED', '<unset>')}")
    print(f"TOPSAILAI_CHAT_MULTI_LINE    : {env.get('TOPSAILAI_CHAT_MULTI_LINE', '<unset>')}")
    print(f"CWD              : {os.getcwd()}")
    print("=" * 72)
    sys.stdout.flush()

    hook = MockHookInstruction()
    try:
        message = input_message(tips="Your input:", hook=hook)
    except (EOFError, KeyboardInterrupt):
        print("\n[exiting]")
        return 0

    print(f"[RETURNED] {message!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
