#!/usr/bin/env python3
"""Unit tests for runtime-scope control command PID targeting."""

import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(
    0,
    os.path.dirname(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    ),
)

from cli_topsailai.streaming import _handle_stream_command


class TestRuntimeControlCommand(unittest.TestCase):
    """Verify runtime control commands target the watched process."""

    @patch("cli_topsailai.process.run_external_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_passes_watched_filename_pid_to_control_cli(self, mock_match, mock_run):
        """The runtime command must pass the watched file PID to the control CLI."""
        instruction = {
            "cmd": "/control.hard_interrupt",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_send_control -s '{session_id}' -c 'hard_interrupt' -a '{}'",
        }
        variables = {"session_id": "s1", "task_dir": "/task"}
        mock_match.return_value = (instruction, variables)

        _handle_stream_command(
            "/control.hard_interrupt",
            "/task",
            [],
            "s1",
            "/task/s1.2468.session.stdout",
            default_pid=None,
        )

        command = mock_run.call_args.args[0]
        self.assertEqual(
            command,
            [
                "topsailai_send_control",
                "-s",
                "s1",
                "-c",
                "hard_interrupt",
                "-a",
                "{}",
                "-p",
                "2468",
            ],
        )
        self.assertEqual(
            instruction["shell"],
            "topsailai_send_control -s '{session_id}' -c 'hard_interrupt' -a '{}'",
        )

    @patch("cli_topsailai.streaming.get_file_pid", return_value=None)
    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_unresolved_pid_reports_error_without_dispatch(
        self, mock_match, mock_handle, mock_get_file_pid
    ):
        """Control dispatch must fail closed when the watched PID is unavailable."""
        mock_match.return_value = (
            {
                "cmd": "/control.hard_interrupt",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_send_control -s '{session_id}' -c 'hard_interrupt' -a '{}'",
            },
            {"session_id": "s1", "task_dir": "/task"},
        )

        with patch("builtins.print") as mock_print:
            _handle_stream_command(
                "/control.hard_interrupt",
                "/task",
                [],
                "s1",
                "/task/not-a-session.log",
                default_pid=None,
            )

        mock_get_file_pid.assert_called_once_with("/task/not-a-session.log")
        mock_handle.assert_not_called()
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Could not resolve the watched session PID", printed)


if __name__ == "__main__":
    unittest.main()
