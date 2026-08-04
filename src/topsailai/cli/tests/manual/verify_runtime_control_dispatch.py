#!/usr/bin/env python
"""Verify runtime-scope control command matching and safe argument dispatch."""

import json
import os
import sys
from unittest.mock import patch

CLI_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, CLI_DIR)

import cli_topsailai.state as state
from cli_topsailai.yaml_commands import (
    handle_yaml_command,
    load_yaml_commands,
    match_yaml_command,
)


def verify_command(user_input: str, expected_payload: str) -> None:
    """Match and dispatch one runtime control command without contacting a session."""
    result = match_yaml_command(user_input, "/tmp/task")
    if result is None:
        raise AssertionError(f"Runtime command did not match: {user_input}")

    instruction, variables = result
    with patch("cli_topsailai.process.run_external_command") as mock_run:
        handle_yaml_command(instruction, variables)

    command = mock_run.call_args[0][0]
    expected = [
        "topsailai_send_control",
        "-s",
        "manual-session",
        "-c",
        "hard_interrupt",
        "-a",
        expected_payload,
    ]
    if command != expected:
        raise AssertionError(f"Unexpected dispatch command: {command!r}")


def main() -> int:
    """Run runtime control matching checks against the real YAML definition."""
    state.yaml_commands = load_yaml_commands(os.path.join(CLI_DIR, "topsailai.yaml"))
    state.current_scope = "runtime"
    state.current_session_id = "manual-session"

    verify_command("/control hard_interrupt", "")
    payload = json.dumps({"reason": "timeout"}, separators=(",", ":"))
    verify_command(f"/control hard_interrupt {payload}", payload)
    print("PASS runtime /control dispatch preserves optional JSON arguments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
