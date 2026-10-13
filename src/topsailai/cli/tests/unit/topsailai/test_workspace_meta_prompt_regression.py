"""Cover existing prompt boundaries affected by workspace meta integration.

Author: DawsonLin
"""
from unittest.mock import Mock

import pytest
from cli_topsailai import core, state, process, yaml_commands


@pytest.mark.parametrize("scope,managed,command,rows,expected", [
    ("workspace", True, "p agent 1", [{}], ("agent_managed_project", "1")),
    ("workspace", True, "p agent", [{}], ("quit", None)),
    ("workspace", True, "p agent x", [{}], ("quit", None)),
    ("workspace", True, "p agent 0", [{}], ("quit", None)),
    ("project", False, "r 0", [{}], ("quit", None)),
    ("project", False, "r x", [{}], ("quit", None)),
    ("project", False, "cd 1", [{}], ("quit", None)),
    ("project", False, "cd 1", [{"session_id": "(temp)"}], ("quit", None)),
    ("project", False, "cd 1", [{"session_id": "sample"}], ("enter_session", "sample")),
    ("project", False, "cd 9", [{}], ("quit", None)),
    ("project", False, "cd sample", [{}], ("enter_session", "sample")),
    ("doc", False, "cd", [{}], ("leave_scope", None)),
    ("workspace", False, "p add /folder name", [{}], ("add_managed_project", "/folder name")),
    ("workspace", False, "p del 1", [{}], ("delete_managed_project", "1")),
    ("workspace", False, "p del", [{}], ("quit", None)),
    ("workspace", False, "p unknown", [{}], ("quit", None)),
    ("doc", False, "/models", [{}], ("leave_scope", None)),
    ("doc", False, "/models clear", [{}], ("leave_scope", None)),
    ("workspace", False, "/models wat", [{}], ("quit", None)),
    ("workspace", False, "/session", [{}], ("quit", None)),
    ("workspace", False, "/session 9", [{}], ("quit", None)),
    ("workspace", False, "/session (temp)", [{}], ("session_id", "topsailai")),
    ("workspace", False, "/agent", [{}], ("quit", None)),
    ("workspace", False, "/resume", [{}], ("quit", None)),
    ("doc", False, "1", [{}], ("read_doc", 0)),
    ("doc", False, "9", [{}], ("leave_scope", None)),
    ("project", False, "1", [{}], ("quit", None)),
    ("project", False, "unknown", [{}], ("quit", None)),
])
def test_prompt_boundary(monkeypatch, scope, managed, command, rows, expected):
    """Check exact actions for valid input and recovery after rejected input."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(yaml_commands, "match_yaml_command", Mock(return_value=None))
    monkeypatch.setattr(process, "cleanup_children", Mock())
    inputs = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    assert core.prompt_selection(rows, "/unused") == expected


@pytest.mark.parametrize("error", [EOFError, KeyboardInterrupt])
def test_prompt_interrupt_cleanup(monkeypatch, error):
    """Input interruption requests exact cleanup and returns quit."""
    cleanup = Mock()
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(core, "_read_input_with_prompt", Mock(side_effect=error))
    monkeypatch.setattr(process, "cleanup_children", cleanup)
    assert core.prompt_selection([], "/unused") == ("quit", None)
    cleanup.assert_called_once()


def test_prompt_unrecognized_guard(monkeypatch):
    """Repeated unknown input terminates instead of spinning indefinitely."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(yaml_commands, "match_yaml_command", Mock(return_value=None))
    read = Mock(return_value="unknown")
    monkeypatch.setattr(core, "_read_input_with_prompt", read)
    assert core.prompt_selection([], "/unused") == ("quit", None)
    assert read.call_count == 10
