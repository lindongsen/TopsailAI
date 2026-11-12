"""Unit tests for the workspace ``start`` command.

Author: DawsonLin
"""

import io
import os
from contextlib import redirect_stdout
from unittest.mock import Mock

import pytest

from cli_topsailai import core, state, yaml_commands


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Reset prompt globals and load the real YAML command set."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "current_session_id", None)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands())
    return state


def run(monkeypatch, command, scope="workspace", managed=False):
    """Return (action, value, output) for one command line."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    inputs = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _p: next(inputs))
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        action, value = core.prompt_selection([], "/unused")
    return action, value, buffer.getvalue()


@pytest.mark.parametrize("command", ["start", "/start"])
def test_start_without_folder_asks_for_a_row(monkeypatch, command):
    """Both spellings dispatch and carry no folder, so the list is shown."""
    action, value, output = run(monkeypatch, command)
    assert (action, value) == ("start", None)
    assert "[ERROR]" not in output


@pytest.mark.parametrize(
    "command,expected",
    [
        ("start -f /work/a", "/work/a"),
        ("/start -f /work/a", "/work/a"),
        ("start --folder /work/a", "/work/a"),
        ("start -f=/work/a", "/work/a"),
        ("start --folder=/work/a", "/work/a"),
        ("start -f /work/a b", "/work/a b"),
        ("start --folder=/work/a b", "/work/a b"),
    ],
)
def test_start_folder_forms(monkeypatch, command, expected):
    """Every accepted folder form yields the same folder value."""
    action, value, output = run(monkeypatch, command)
    assert (action, value) == ("start", expected)
    assert "[ERROR]" not in output


@pytest.mark.parametrize(
    "command",
    ["start -f", "start --folder", "start --folder=", "start -f=", "start /work/a"],
)
def test_malformed_start_is_rejected(monkeypatch, command):
    """A malformed option reports usage instead of launching a folder."""
    action, _value, output = run(monkeypatch, command)
    assert action == "quit"
    assert "Usage: start [-f <folder>]" in output


@pytest.mark.parametrize("scope", ["project", "session", "doc"])
def test_start_is_workspace_only(monkeypatch, scope):
    """Other scopes reject start instead of launching an agent.

    The trailing ``q`` maps to a different action per scope, so the contract
    asserted here is that ``start`` is never dispatched, not which action the
    next line produces.
    """
    action, _value, output = run(monkeypatch, "start -f /work/a", scope=scope)
    assert action != "start"
    assert "/start is only available in workspace scope" in output


def test_start_is_rejected_in_managed_project_view(monkeypatch):
    """The restricted managed-project view keeps its documented command set."""
    action, _value, output = run(monkeypatch, "start", managed=True)
    assert action == "quit"
    assert "In projects list; supported commands" in output


def test_parse_start_folder_returns_none_without_option():
    """A bare start line carries no folder."""
    assert core._parse_start_folder("start") is None
    assert core._parse_start_folder("/start") is None


def test_resolve_start_folder_requires_a_directory(tmp_path, capsys):
    """A missing folder is reported and never returned as a launch target."""
    assert core._resolve_start_folder(str(tmp_path)) == os.path.abspath(str(tmp_path))
    missing = tmp_path / "missing"
    assert core._resolve_start_folder(str(missing)) is None
    assert "Folder is not a directory" in capsys.readouterr().out


def test_handle_start_with_folder_skips_the_list(monkeypatch, tmp_path):
    """An explicit folder launches directly without listing or prompting."""
    build = Mock(return_value=[{"no": 1, "path": str(tmp_path)}])
    print_table = Mock()
    launch = Mock()
    monkeypatch.setattr(
        "cli_topsailai.project_scope.build_managed_project_list", build
    )
    monkeypatch.setattr(
        "cli_topsailai.project_scope.print_managed_project_table", print_table
    )
    monkeypatch.setattr("cli_topsailai.project_scope.launch_agent_in_folder", launch)
    prompt = Mock(side_effect=AssertionError("must not prompt"))
    monkeypatch.setattr(core, "_read_input_with_prompt", prompt)

    core._handle_start_command(str(tmp_path), agent_mode="raw")

    build.assert_not_called()
    print_table.assert_not_called()
    prompt.assert_not_called()
    launch.assert_called_once_with(os.path.abspath(str(tmp_path)), agent_mode="raw")


def test_handle_start_without_folder_uses_the_managed_list(monkeypatch, tmp_path):
    """The row number selects from exactly the list ``p`` displays."""
    entries = [
        {"no": 1, "name": "a", "path": str(tmp_path / "a")},
        {"no": 2, "name": "b", "path": str(tmp_path / "b")},
    ]
    build = Mock(return_value=entries)
    print_table = Mock()
    resolve = Mock(return_value=str(tmp_path / "b"))
    launch = Mock()
    monkeypatch.setattr(
        "cli_topsailai.project_scope.build_managed_project_list", build
    )
    monkeypatch.setattr(
        "cli_topsailai.project_scope.print_managed_project_table", print_table
    )
    monkeypatch.setattr("cli_topsailai.project_scope.resolve_agent_folder", resolve)
    monkeypatch.setattr("cli_topsailai.project_scope.launch_agent_in_folder", launch)
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _p: "2")

    core._handle_start_command(None, agent_mode="dtach")

    build.assert_called_once_with()
    print_table.assert_called_once_with(entries)
    resolve.assert_called_once_with("2", entries)
    launch.assert_called_once_with(str(tmp_path / "b"), agent_mode="dtach")


@pytest.mark.parametrize("answer", ["0", "3", "abc", ""])
def test_handle_start_rejects_invalid_row(monkeypatch, tmp_path, answer, capsys):
    """An invalid row number never reaches the folder resolver."""
    entries = [{"no": 1, "name": "a", "path": str(tmp_path / "a")}]
    resolve = Mock()
    launch = Mock()
    monkeypatch.setattr(
        "cli_topsailai.project_scope.build_managed_project_list",
        Mock(return_value=entries),
    )
    monkeypatch.setattr(
        "cli_topsailai.project_scope.print_managed_project_table", Mock()
    )
    monkeypatch.setattr("cli_topsailai.project_scope.resolve_agent_folder", resolve)
    monkeypatch.setattr("cli_topsailai.project_scope.launch_agent_in_folder", launch)
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _p: answer)

    core._handle_start_command(None)

    resolve.assert_not_called()
    launch.assert_not_called()
    assert "Invalid project number" in capsys.readouterr().out


@pytest.mark.parametrize("answer", ["q", "quit", "Q"])
def test_handle_start_cancels(monkeypatch, tmp_path, answer):
    """A cancel answer launches nothing."""
    entries = [{"no": 1, "name": "a", "path": str(tmp_path / "a")}]
    launch = Mock()
    monkeypatch.setattr(
        "cli_topsailai.project_scope.build_managed_project_list",
        Mock(return_value=entries),
    )
    monkeypatch.setattr(
        "cli_topsailai.project_scope.print_managed_project_table", Mock()
    )
    monkeypatch.setattr("cli_topsailai.project_scope.launch_agent_in_folder", launch)
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _p: answer)

    core._handle_start_command(None)

    launch.assert_not_called()


def test_handle_start_without_entries_does_not_prompt(monkeypatch, capsys):
    """An empty managed list reports the warning and never prompts."""
    monkeypatch.setattr(
        "cli_topsailai.project_scope.build_managed_project_list", Mock(return_value=[])
    )
    monkeypatch.setattr(
        "cli_topsailai.project_scope.print_managed_project_table", Mock()
    )
    prompt = Mock(side_effect=AssertionError("must not prompt"))
    monkeypatch.setattr(core, "_read_input_with_prompt", prompt)

    core._handle_start_command(None)

    prompt.assert_not_called()


def test_handle_start_reports_missing_folder(monkeypatch, tmp_path, capsys):
    """A folder that does not exist is reported and nothing is launched."""
    launch = Mock()
    monkeypatch.setattr("cli_topsailai.project_scope.launch_agent_in_folder", launch)

    core._handle_start_command(str(tmp_path / "missing"))

    launch.assert_not_called()
    assert "Folder is not a directory" in capsys.readouterr().out
