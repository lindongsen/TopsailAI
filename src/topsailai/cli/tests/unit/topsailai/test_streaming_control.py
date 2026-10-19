#!/usr/bin/env python3
"""Unit tests for runtime-scope control command PID targeting."""

import json
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


class TestRuntimeAgentInstructionShortcut(unittest.TestCase):
    """Verify /agent.<instruction> forwards through call_instruction."""

    @patch("cli_topsailai.process.run_external_command")
    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_forwards_instruction_without_args(self, mock_match, mock_handle, mock_run):
        """A bare /agent.models must send call_instruction with no args."""
        instruction = {
            "cmd": "/control.call_instruction {args}",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_send_control -s '{session_id}' -c 'call_instruction' -a '{args}'",
        }
        variables = {"session_id": "s1", "task_dir": "/task"}
        mock_match.return_value = (instruction, variables)

        _handle_stream_command(
            "/agent.models",
            "/task",
            [],
            "s1",
            "/task/s1.2468.session.stdout",
            default_pid=None,
        )

        mock_handle.assert_called_once()
        sent_instruction, sent_variables = mock_handle.call_args.args
        self.assertEqual(sent_instruction["cmd"], "/control.call_instruction {args}")
        self.assertEqual(
            sent_instruction["shell"],
            "topsailai_send_control -s '{session_id}' -c 'call_instruction' -a '{args}' -p '{pid}'",
        )
        self.assertEqual(sent_variables["pid"], "2468")
        self.assertEqual(sent_variables["session_id"], "s1")
        self.assertEqual(
            json.loads(sent_variables["args"]),
            {"instruction": "agent.models"},
        )

    @patch("cli_topsailai.process.run_external_command")
    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_forwards_positional_args(self, mock_match, mock_handle, mock_run):
        """Trailing tokens become positional args in the payload."""
        instruction = {
            "cmd": "/control.call_instruction {args}",
            "scopes": ["session", "runtime"],
            "shell": "topsailai_send_control -s '{session_id}' -c 'call_instruction' -a '{args}'",
        }
        mock_match.return_value = (instruction, {"session_id": "s1", "task_dir": "/task"})

        _handle_stream_command(
            "/agent.models 1",
            "/task",
            [],
            "s1",
            "/task/s1.2468.session.stdout",
            default_pid=None,
        )

        sent_variables = mock_handle.call_args.args[1]
        self.assertEqual(
            json.loads(sent_variables["args"]),
            {"instruction": "agent.models", "args": ["1"]},
        )

    @patch("cli_topsailai.streaming.get_file_pid", return_value=None)
    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_unresolved_pid_reports_error_without_dispatch(
        self, mock_match, mock_handle, mock_get_file_pid
    ):
        """The shortcut must fail closed when the watched PID is unavailable."""
        mock_match.return_value = (
            {
                "cmd": "/control.call_instruction {args}",
                "scopes": ["session", "runtime"],
                "shell": "topsailai_send_control -s '{session_id}' -c 'call_instruction' -a '{args}'",
            },
            {"session_id": "s1", "task_dir": "/task"},
        )

        with patch("builtins.print") as mock_print:
            _handle_stream_command(
                "/agent.models",
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

    @patch("cli_topsailai.streaming.yaml_commands.handle_yaml_command")
    @patch("cli_topsailai.streaming.yaml_commands.match_yaml_command")
    def test_empty_instruction_reports_usage(self, mock_match, mock_handle):
        """A bare /agent. must report usage and not dispatch."""
        with patch("builtins.print") as mock_print:
            _handle_stream_command(
                "/agent.",
                "/task",
                [],
                "s1",
                "/task/s1.2468.session.stdout",
                default_pid=2468,
            )

        mock_match.assert_not_called()
        mock_handle.assert_not_called()
        printed = " ".join(str(call) for call in mock_print.call_args_list)
        self.assertIn("Usage: /agent.<instruction>", printed)


if __name__ == "__main__":
    unittest.main()


def test_live_fbt_yaml_dispatch(monkeypatch):
    """Dispatch live shortcuts with exact payloads and immutable definitions."""
    import copy
    from pathlib import Path
    from cli_topsailai import state, yaml_commands

    commands = yaml_commands.load_yaml_commands(str(Path(__file__).resolve().parents[3] / "topsailai.yaml"))
    original = copy.deepcopy(commands)
    monkeypatch.setattr(state, "yaml_commands", commands)
    monkeypatch.setattr(state, "current_session_id", "fbt-session")
    sent = []
    monkeypatch.setattr("cli_topsailai.process.run_external_command", lambda argv, *args: sent.append(argv))
    for scope in ("runtime", "session"):
        monkeypatch.setattr(state, "current_scope", scope)
        for suffix, operation in (("hard_interrupt", "hard_interrupt"), ("force_retry", "force_retry")):
            command = "/control.fbt." + suffix
            for explicit_pid, expected_pid in ((None, "2468"), (9753, "9753")):
                _handle_stream_command(command, "/task", [], "fbt-session",
                                       "/task/fbt-session.2468.session.stdout", default_pid=explicit_pid)
                assert sent[-1] == ["topsailai_send_control", "-s", "fbt-session", "-c", "llm_control",
                                    "-a", json.dumps({"operation": operation}, separators=(",", ":")),
                                    "-p", expected_pid]
                assert json.loads(sent[-1][6]) == {"operation": operation}
            instruction, variables = yaml_commands.match_yaml_command(command, "/task")
            yaml_commands.handle_yaml_command(instruction, variables)
            assert "-p" not in sent[-1]
    assert commands == original


def test_live_fbt_boundaries_and_legacy(monkeypatch, capsys):
    """Reject extra arguments, unavailable PIDs and ineligible scopes."""
    from pathlib import Path
    from cli_topsailai import state, yaml_commands

    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands(
        str(Path(__file__).resolve().parents[3] / "topsailai.yaml")))
    monkeypatch.setattr(state, "current_session_id", "fbt-session")
    sent = []
    monkeypatch.setattr("cli_topsailai.process.run_external_command", lambda argv, *args: sent.append(argv))
    for scope in ("runtime", "session"):
        monkeypatch.setattr(state, "current_scope", scope)
        assert yaml_commands.match_yaml_command("/control.fbt.hard__interrupt", "/task") is None
        assert yaml_commands.match_yaml_command("/control.fbt.force__retry", "/task") is None
        for suffix in ("hard_interrupt", "force_retry"):
            command = "/control.fbt." + suffix
            assert yaml_commands.match_yaml_command(command + " extra", "/task") is None
            _handle_stream_command(command + " extra", "/task", [], "fbt-session", None, default_pid=2468)
            _handle_stream_command(command, "/task", [], "fbt-session", None, default_pid=None)
    assert sent == []
    assert "Could not resolve the watched session PID" in capsys.readouterr().out
    for scope in ("workspace", "project", "doc"):
        monkeypatch.setattr(state, "current_scope", scope)
        for suffix in ("hard_interrupt", "force_retry"):
            assert yaml_commands.match_yaml_command("/control.fbt." + suffix, "/task") is None
    monkeypatch.setattr(state, "current_scope", "runtime")
    _handle_stream_command("/control.hard_interrupt", "/task", [], "fbt-session", None, default_pid=2468)
    assert sent == [["topsailai_send_control", "-s", "fbt-session", "-c", "hard_interrupt", "-a", "{}", "-p", "2468"]]
