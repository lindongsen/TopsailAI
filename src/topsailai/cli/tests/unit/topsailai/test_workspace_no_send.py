"""Workspace send restriction regressions.

Author: DawsonLin
"""
from unittest.mock import Mock

import pytest

from cli_topsailai import completer, core, help_text, state, streaming


@pytest.mark.parametrize("command", ["/send", "/send 1 hello", "send", "send s1 hello", "/SEND hello"])
def test_workspace_rejects_send(monkeypatch, capsys, command):
    """Reject all existing send forms before returning a delivery action."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    inputs = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    assert core.prompt_selection([], "/unused") == ("quit", None)
    assert "/send is not available in workspace scope" in capsys.readouterr().out


@pytest.mark.parametrize("scope", ["session", "project"])
def test_other_scope_send_preserved(monkeypatch, scope):
    """Keep nonworkspace parsing unchanged."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: "/send hello")
    assert core.prompt_selection([], "/unused") == ("send", "/send hello")


def test_workspace_discovery_surfaces(monkeypatch, capsys):
    """Workspace completion, help and fallback must not advertise send."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "yaml_commands", [])
    monkeypatch.setattr(state, "history_manager", None)
    assert "/send" not in completer.get_available_completions()
    help_text.print_help([], "workspace")
    assert "/send" not in capsys.readouterr().out
    help_text.print_scopes()
    workspace_section = capsys.readouterr().out.split("runtime")[0]
    assert "send messages" not in workspace_section
    inputs = iter(["unknown", "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    core.prompt_selection([], "/unused")
    assert "/send" not in capsys.readouterr().out
    monkeypatch.setattr(state, "current_scope", "runtime")
    assert "/send" in completer.get_available_completions()


def test_runtime_delivery_preserved(monkeypatch):
    """The watched runtime session still receives its message."""
    sender = Mock()
    monkeypatch.setattr(streaming, "send_message_to_session", sender)
    streaming._handle_stream_command("/send hello", "/unused", [], "s1", "/unused/log", 123)
    sender.assert_called_once_with("s1", "hello", "/unused", stdout_path="/unused/log", pid=123)
