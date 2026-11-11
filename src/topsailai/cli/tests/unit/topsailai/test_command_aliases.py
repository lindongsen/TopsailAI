"""Verify the /messages, /list and /l command aliases.

Author: DawsonLin
"""

import io
from contextlib import redirect_stdout

import pytest

from cli_topsailai import completer, core, help_text, state, yaml_commands

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


SESSION_ALIASES = ["messages 1", "/messages 1"]
REFRESH_ALIASES = ["list", "/list", "l", "/l"]
REFRESH_ALL_ALIASES = ["list all", "/list all", "l all", "/l all"]


@pytest.mark.parametrize("scope", ["workspace", "project"])
@pytest.mark.parametrize("command", SESSION_ALIASES)
def test_session_alias_binds_to_session_action(monkeypatch, scope, command):
    """Every /messages spelling resolves the selected row."""
    action, value, _ = run(monkeypatch, scope, command)
    assert action == "session"
    assert value == 0


@pytest.mark.parametrize("command", ["messages s2", "/messages s2"])
def test_session_alias_accepts_a_literal_session_id(monkeypatch, command):
    """A literal session id keeps the session_id action."""
    action, value, _ = run(monkeypatch, "workspace", command)
    assert action == "session_id"
    assert value == "s2"


@pytest.mark.parametrize("scope", ["workspace", "project", "doc"])
@pytest.mark.parametrize("command", REFRESH_ALIASES)
def test_refresh_alias_binds_to_plain_refresh(monkeypatch, scope, command):
    """Every /list and /l spelling resolves a plain refresh."""
    action, value, _ = run(monkeypatch, scope, command)
    assert action == "refresh"
    assert value is None


@pytest.mark.parametrize("command", REFRESH_ALL_ALIASES)
def test_refresh_all_alias_includes_completed_rows(monkeypatch, command):
    """The "all" form of every alias opts in to completed rows."""
    action, value, _ = run(monkeypatch, "workspace", command)
    assert action == "refresh"
    assert value == "all"


@pytest.mark.parametrize("command", ["r", "/r", "refresh", "/refresh"])
def test_original_refresh_spellings_still_work(monkeypatch, command):
    """The pre-existing refresh spellings keep their behavior."""
    action, value, _ = run(monkeypatch, "workspace", command)
    assert action == "refresh"
    assert value is None


@pytest.mark.parametrize("command", ["r all", "/r all"])
def test_original_refresh_all_spellings_still_work(monkeypatch, command):
    """The pre-existing "all" spellings keep their behavior."""
    action, value, _ = run(monkeypatch, "workspace", command)
    assert action == "refresh"
    assert value == "all"


def test_project_scope_r_limit_is_preserved(monkeypatch):
    """Project-scope r [limit] keeps its limit argument."""
    action, value, _ = run(monkeypatch, "project", "r 5")
    assert action == "show_recent_projects"
    assert value is None
    assert state.project_scope_limit == 5


@pytest.mark.parametrize("command", ["list 5", "/list 5", "l 5", "/l 5"])
def test_refresh_alias_rejects_a_limit(monkeypatch, command):
    """The aliases take no limit, exactly like /refresh."""
    action, value, _ = run(monkeypatch, "project", command)
    assert action != "show_recent_projects"


@pytest.mark.parametrize("command", SESSION_ALIASES + REFRESH_ALIASES)
def test_managed_project_view_rejects_the_aliases(monkeypatch, command):
    """The restricted managed-project view keeps its own accepted set."""
    action, value, output = run(monkeypatch, "workspace", command, managed=True)
    assert action != "session"
    assert action != "session_id"
    assert action != "refresh"
    assert "In projects list; supported commands" in output


def test_bare_session_alias_prints_usage_with_alias_name(monkeypatch):
    """A bare /messages reports the usage error and names the alias."""
    action, value, output = run(monkeypatch, "workspace", "/messages")
    assert action == "quit"
    assert "Usage: /session" in output
    assert "alias: /messages" in output


def test_help_renders_aliases_for_refresh_and_session():
    """Help output advertises the aliases next to their commands."""
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        help_text.print_help([], "workspace")
    output = buffer.getvalue()
    assert "alias: list, l" in output
    assert "alias: messages" in output


def test_completion_offers_the_aliases(monkeypatch):
    """Tab completion offers every alias spelling."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands())
    completions = completer.get_available_completions()
    for spelling in ["/messages", "/list", "/l", "/list all", "/l all"]:
        assert spelling in completions


def test_unrecognized_guidance_names_the_aliases(monkeypatch):
    """The unknown-command guidance mentions the aliases."""
    _, _, output = run(monkeypatch, "workspace", "definitely-not-a-command")
    assert "alias: /list, /l" in output
    assert "alias: /messages" in output
