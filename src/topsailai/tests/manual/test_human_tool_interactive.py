"""
Manual/interactive test for tools/human_tool.py ask_decision.

Run directly:
    python tests/manual/test_human_tool_interactive.py

The script simulates an agent context by installing a thread-local runtime
input function backed by builtin input(), then calls ask_decision so a human
can type an answer interactively. It demonstrates the answered / cancelled /
timeout paths end-to-end.

Author: DawsonLin
"""

import sys
import os

sys.path.insert(0, '/TopsailAI/src/topsailai')

from topsailai.utils import thread_local_tool
from topsailai.tools.human_tool import ask_decision


def _stdin_input(prompt):
    """Read one line from stdin using builtin input()."""
    return input(prompt)


def main():
    print('=== human_tool ask_decision manual test ===')
    print("Type an option index, free text, or 'cancel'/'abort'. Ctrl+C aborts.")
    print()

    # Install a plain thread-local runtime input source.
    thread_local_tool.set_agent_runtime_input(_stdin_input)

    try:
        r = ask_decision(
            'Which deployment strategy should we use?',
            options=['blue-green', 'canary', 'rolling'],
            allow_free_text=False,
            default='rolling',
        )
        print()
        print('RESULT:', r)
    finally:
        thread_local_tool.set_agent_runtime_input(None)


if __name__ == '__main__':
    main()
