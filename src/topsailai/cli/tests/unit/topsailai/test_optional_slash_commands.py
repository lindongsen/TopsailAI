"""Verify the leading '/' is optional for workspace, session and project commands.

Author: DawsonLin
"""

import io
from contextlib import redirect_stdout

import pytest

from cli_topsailai import core, state, yaml_commands

FILES = [
    {"filename": "a.stdout", "session_id": "s1", "pid": 111, "path": "/x/a.stdout"},
    {"filename": "b.stdout", "session_id": "s2", "pid": 222, "path": "/x/b.stdout"},
]


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Reset prompt globals and load the real YAML command set."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "current_session_id", None)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands())
    return state


def run(monkeypatch, scope, command, managed=False):
    """Return (action, value, output) for one command in one scope."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "current_session_id", "s1" if scope == "session" else None)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    inputs = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _p: next(inputs))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        action, value = core.prompt_selection(list(FILES), "/unused")
    return action, value, buffer.getvalue()


WORKSPACE_PAIRS = [
    ("meta 1", "/meta 1"),
    ("kill 1", "/kill 1"),
    ("driver 1", "/driver 1"),
    ("driver status 1", "/driver status 1"),
    ("driver stop 1", "/driver stop 1"),
    ("driver log 1", "/driver log 1"),
    ("driver meta 1", "/driver meta 1"),
    ("models", "/models"),
    ("models current", "/models current"),
    ("models clear", "/models clear"),
    ("scopes", "/scopes"),
    ("r", "/r"),
    ("refresh", "/refresh"),
    ("r all", "/r all"),
    ("refresh all", "/refresh all"),
    ("p", "/p"),
    ("projects", "/projects"),
    ("p add /tmp/x", "/p add /tmp/x"),
    ("p del 1", "/p del 1"),
    ("clean", "/clean"),
    ("clean 1", "/clean 1"),
    ("help", "/help"),
    ("help ctx", "/help ctx"),
    ("session 1", "/session 1"),
    ("agent 1", "/agent 1"),
    ("resume 1", "/resume 1"),
    ("retrieve", "/retrieve"),
    ("stream", "/stream"),
    ("cd doc", "/cd doc"),
    ("q", "/q"),
    ("quit", "/quit"),
    ("exit", "/exit"),
]

SESSION_PAIRS = [
    ("help", "/help"),
    ("retrieve", "/retrieve"),
    ("stream", "/stream"),
    ("clean", "/clean"),
    ("session 1", "/session 1"),
    ("agent 1", "/agent 1"),
    ("resume 1", "/resume 1"),
    ("q", "/q"),
    ("quit", "/quit"),
    ("exit", "/exit"),
]

PROJECT_PAIRS = [
    ("r", "/r"),
    ("r 5", "/r 5"),
    ("recent", "/recent"),
    ("recent 5", "/recent 5"),
    ("p", "/p"),
    ("projects", "/projects"),
    ("p add /tmp/x", "/p add /tmp/x"),
    ("p del 1", "/p del 1"),
    ("models", "/models"),
    ("models current", "/models current"),
    ("models clear", "/models clear"),
    ("clean", "/clean"),
    ("help", "/help"),
    ("session 1", "/session 1"),
    ("agent 1", "/agent 1"),
    ("resume 1", "/resume 1"),
    ("cd 1", "/cd 1"),
    ("q", "/q"),
    ("quit", "/quit"),
    ("exit", "/exit"),
]


@pytest.mark.parametrize("bare,slashed", WORKSPACE_PAIRS)
def test_workspace_forms_are_equivalent(monkeypatch, bare, slashed):
    """Workspace scope accepts both spellings with identical action and value."""
    bare_result = run(monkeypatch, "workspace", bare)
    slashed_result = run(monkeypatch, "workspace", slashed)
    assert bare_result[:2] == slashed_result[:2]
    assert "Unknown command" not in bare_result[2]
    assert "Unknown command" not in slashed_result[2]


@pytest.mark.parametrize("bare,slashed", SESSION_PAIRS)
def test_session_forms_are_equivalent(monkeypatch, bare, slashed):
    """Session scope accepts both spellings with identical action and value."""
    bare_result = run(monkeypatch, "session", bare)
    slashed_result = run(monkeypatch, "session", slashed)
    assert bare_result[:2] == slashed_result[:2]
    assert "Unknown command" not in bare_result[2]
    assert "Unknown command" not in slashed_result[2]


@pytest.mark.parametrize("bare,slashed", PROJECT_PAIRS)
def test_project_forms_are_equivalent(monkeypatch, bare, slashed):
    """Project scope accepts both spellings with identical action and value."""
    bare_result = run(monkeypatch, "project", bare)
    slashed_result = run(monkeypatch, "project", slashed)
    assert bare_result[:2] == slashed_result[:2]
    assert "Unknown command" not in bare_result[2]
    assert "Unknown command" not in slashed_result[2]


@pytest.mark.parametrize("scope", ["workspace", "session", "project"])
@pytest.mark.parametrize("command", ["q", "/q", "quit", "/quit", "exit", "/exit"])
def test_quit_forms(monkeypatch, scope, command):
    """Every quit spelling quits from the three slash-optional scopes."""
    assert run(monkeypatch, scope, command)[0] == "quit"


@pytest.mark.parametrize("command", ["send hello", "/send hello"])
def test_send_keeps_raw_value(monkeypatch, command):
    """Both send spellings dispatch, and the raw line stays the action value."""
    action, value, output = run(monkeypatch, "session", command)
    assert action == "send"
    assert value == command
    assert "[ERROR]" not in output


@pytest.mark.parametrize("command", ["send hello", "/send hello"])
def test_send_still_rejected_in_workspace(monkeypatch, command):
    """Workspace scope rejects both send spellings identically."""
    action, _value, output = run(monkeypatch, "workspace", command)
    assert action == "quit"
    assert "/send is not available in workspace scope" in output


@pytest.mark.parametrize(
    "command,expected",
    [
        ("r", ("refresh", None)),
        ("/r", ("refresh", None)),
        ("recent", ("refresh", None)),
        ("/recent", ("refresh", None)),
        ("p", ("show_managed_projects", None)),
        ("/p", ("show_managed_projects", None)),
        ("projects", ("show_managed_projects", None)),
        ("/projects", ("show_managed_projects", None)),
        ("p agent 1", ("agent_managed_project", "1")),
        ("/p agent 1", ("agent_managed_project", "1")),
    ],
)
def test_managed_project_view_accepts_both_forms(monkeypatch, command, expected):
    """The restricted managed-project view accepts slash and bare spellings."""
    action, value, output = run(monkeypatch, "workspace", command, managed=True)
    assert (action, value) == expected
    assert "In projects list" not in output


@pytest.mark.parametrize("command", ["meta 1", "/meta 1", "kill 1", "/kill 1"])
def test_managed_project_view_still_rejects_task_list_commands(monkeypatch, command):
    """Task-list-only commands stay rejected while the project list is shown."""
    action, _value, output = run(monkeypatch, "workspace", command, managed=True)
    assert action == "quit"
    assert "ordinary workspace task list" in output


@pytest.mark.parametrize("command", ["meta 1", "/meta 1"])
def test_doc_scope_keeps_workspace_only_rejection(monkeypatch, command):
    """Doc scope keeps reporting the ordinary-workspace restriction."""
    action, _value, output = run(monkeypatch, "doc", command)
    assert action in ("quit", "leave_scope")
    assert "ordinary workspace task list" in output


@pytest.mark.parametrize("command", ["q", "/q", "quit", "/quit", "cd", "/cd"])
def test_doc_scope_leaves_scope(monkeypatch, command):
    """Doc scope still leaves the scope instead of quitting the CLI."""
    assert run(monkeypatch, "doc", command)[0] == "leave_scope"


@pytest.mark.parametrize("command", ["!echo hi", "!git status"])
def test_shell_escape_is_not_normalized(monkeypatch, command):
    """The '!' escape executes the raw line and never becomes a command."""
    calls = []
    monkeypatch.setattr(
        "cli_topsailai.shell_commands.execute_shell_command",
        lambda line: calls.append(line),
    )
    action, _value, _output = run(monkeypatch, "workspace", command)
    assert calls == [command]
    assert action == "quit"


@pytest.mark.parametrize("command", ["cd project", "/cd project"])
def test_yaml_command_forms_match_same_instruction(monkeypatch, command):
    """YAML instructions match with and without the leading slash."""
    matched = []

    def fake_handle(instruction, variables):
        matched.append(instruction.get("cmd"))
        return "yaml_handled"

    monkeypatch.setattr(yaml_commands, "handle_yaml_command", fake_handle)
    action, _value, _output = run(monkeypatch, "workspace", command)
    assert action == "yaml_handled"
    assert matched == ["/cd {session_id}"]


@pytest.mark.parametrize("command", ["env.get HOME", "/env.get HOME"])
def test_yaml_variable_command_forms_match_same_instruction(monkeypatch, command):
    """A YAML command with a variable placeholder matches in both forms."""
    matched = []

    def fake_handle(instruction, variables):
        matched.append((instruction.get("cmd"), variables.get("key")))
        return "yaml_handled"

    monkeypatch.setattr(yaml_commands, "handle_yaml_command", fake_handle)
    action, _value, _output = run(monkeypatch, "workspace", command)
    assert action == "yaml_handled"
    assert matched == [("/env.get {key}", "HOME")]
