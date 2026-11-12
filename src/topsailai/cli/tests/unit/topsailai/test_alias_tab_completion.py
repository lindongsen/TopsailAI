"""Verify that command aliases are reachable through TAB completion.

Author: DawsonLin

The advertised inventory holds one canonical "/"-prefixed spelling per command.
The leading "/" is optional in workspace, project, session and doc scope, so a
bare alias such as ``list`` must complete to ``list`` while ``/list`` completes
to ``/list``. All three completion surfaces (readline, raw TTY, curses) must
agree, because a spelling that completes on one surface and not another is the
defect this module guards against.
"""

import io
from unittest.mock import MagicMock, patch

import pytest

from cli_topsailai import completer, state, yaml_commands
from cli_topsailai.constants import (
    MANAGED_PROJECT_SPELLINGS,
    PROJECT_RECENT_SPELLINGS,
    QUIT_COMMAND_SPELLINGS,
    REFRESH_COMMAND_ALIASES,
    RUNTIME_COMMAND_ALIASES,
    SESSION_COMMAND_ALIASES,
)
from cli_topsailai.streaming import _read_input_line_tty
from cli_topsailai.tui import CursesStreamUI

ALL_SCOPES = ["workspace", "project", "session", "doc"]


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Reset the completion globals and load the real YAML command set."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "current_session_id", None)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "yaml_commands", yaml_commands.load_yaml_commands())
    return state


def candidates(monkeypatch, scope, prefix, managed=False):
    """Return the completion candidates for one prefix in one scope."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    return completer.get_completion_candidates(prefix)


# ---------------------------------------------------------------------------
# Candidate resolution
# ---------------------------------------------------------------------------


def test_bare_prefix_returns_bare_spellings(monkeypatch):
    """A bare prefix completes to bare spellings, not to slash spellings."""
    assert candidates(monkeypatch, "workspace", "list") == ["list", "list all"]


def test_slash_prefix_returns_canonical_spellings(monkeypatch):
    """A slash prefix keeps the canonical slash spelling."""
    assert candidates(monkeypatch, "workspace", "/list") == ["/list", "/list all"]


@pytest.mark.parametrize("scope", ALL_SCOPES)
@pytest.mark.parametrize(
    "alias", list(SESSION_COMMAND_ALIASES) + list(REFRESH_COMMAND_ALIASES)
)
def test_declared_alias_completes_in_every_optional_slash_scope(
    monkeypatch, scope, alias
):
    """Every declared alias completes in each scope that accepts a bare token."""
    assert alias in candidates(monkeypatch, scope, alias)


@pytest.mark.parametrize("alias", list(RUNTIME_COMMAND_ALIASES))
def test_runtime_alias_completes_in_runtime_scope(monkeypatch, alias):
    """Runtime aliases complete in runtime scope."""
    assert alias in candidates(monkeypatch, "runtime", alias)


@pytest.mark.parametrize("alias", list(RUNTIME_COMMAND_ALIASES))
def test_runtime_alias_is_not_advertised_outside_runtime_scope(monkeypatch, alias):
    """Runtime aliases are not offered where the runtime recognizer is absent."""
    for scope in ALL_SCOPES:
        assert alias not in candidates(monkeypatch, scope, alias)


@pytest.mark.parametrize("prefix", ["list all", "l all", "/list all", "/l all"])
def test_refresh_all_forms_complete(monkeypatch, prefix):
    """The "all" forms of the refresh aliases complete."""
    assert prefix in candidates(monkeypatch, "workspace", prefix)


def test_candidates_are_unique(monkeypatch):
    """No spelling repeats, so TAB cycling cannot stall on a duplicate."""
    for scope in ALL_SCOPES + ["runtime"]:
        for prefix in ("l", "list", "/l", "s", "q", "e", "p", "r"):
            found = candidates(monkeypatch, scope, prefix)
            assert len(found) == len(set(found)), (scope, prefix, found)


def test_no_match_prefix_returns_empty_list(monkeypatch):
    """An unknown prefix yields no candidate instead of a partial match."""
    assert candidates(monkeypatch, "workspace", "zzz") == []


# ---------------------------------------------------------------------------
# Advertised inventory stays canonical
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bare", list(SESSION_COMMAND_ALIASES) + list(REFRESH_COMMAND_ALIASES)
)
def test_inventory_does_not_append_bare_alias(monkeypatch, bare):
    """The inventory keeps one canonical spelling, so no bare alias is added."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    inventory = completer.get_available_completions()
    assert "/" + bare in inventory
    assert bare not in inventory


@pytest.mark.parametrize("alias", list(RUNTIME_COMMAND_ALIASES))
def test_inventory_advertises_runtime_alias_only_in_runtime_scope(monkeypatch, alias):
    """Runtime aliases are advertised only where they are accepted."""
    monkeypatch.setattr(state, "current_scope", "runtime")
    assert "/" + alias in completer.get_available_completions()
    monkeypatch.setattr(state, "current_scope", "workspace")
    assert "/" + alias not in completer.get_available_completions()


# ---------------------------------------------------------------------------
# Newly declared aliases: exit, projects, recent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ALL_SCOPES + ["runtime"])
def test_exit_completes_in_every_scope(monkeypatch, scope):
    """"exit" is the same command as q/quit, so it completes everywhere."""
    assert "exit" in candidates(monkeypatch, scope, "exit")


def test_exit_is_accepted_where_q_is_accepted():
    """The quit spelling group contains q, quit and exit in both forms."""
    for spelling in ("q", "/q", "quit", "/quit", "exit", "/exit"):
        assert spelling in QUIT_COMMAND_SPELLINGS


@pytest.mark.parametrize("scope", ["workspace", "project"])
def test_projects_completes_where_it_is_accepted(monkeypatch, scope):
    """"projects" completes in the scopes that accept the managed-project list."""
    assert "projects" in candidates(monkeypatch, scope, "projects")


@pytest.mark.parametrize("scope", ["session", "doc", "runtime"])
def test_projects_is_not_offered_where_it_is_rejected(monkeypatch, scope):
    """Completion never offers a spelling the parser rejects."""
    assert "projects" not in candidates(monkeypatch, scope, "projects")


def test_recent_completes_in_project_scope(monkeypatch):
    """"recent" completes in project scope, where it is accepted."""
    assert "recent" in candidates(monkeypatch, "project", "recent")


def test_recent_completes_in_workspace_managed_project_view(monkeypatch):
    """"recent" refreshes the managed-project list, so it completes there."""
    assert "recent" in candidates(monkeypatch, "workspace", "recent", managed=True)


def test_recent_is_not_offered_in_the_ordinary_workspace_list(monkeypatch):
    """The ordinary workspace list rejects "recent", so it is not offered."""
    assert candidates(monkeypatch, "workspace", "recent") == []


def test_recent_spelling_group_matches_the_parser():
    """The recent spelling group holds the bare and slash forms."""
    for spelling in ("r", "/r", "recent", "/recent"):
        assert spelling in PROJECT_RECENT_SPELLINGS


def test_managed_project_spelling_group_matches_the_parser():
    """The managed-project spelling group holds the bare and slash forms."""
    for spelling in ("p", "/p", "projects", "/projects"):
        assert spelling in MANAGED_PROJECT_SPELLINGS


# ---------------------------------------------------------------------------
# Surface parity: readline, raw TTY, curses
# ---------------------------------------------------------------------------


def _readline_complete(monkeypatch, scope, text):
    """Return the first readline candidate for *text* in *scope*."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    with patch("readline.get_begidx", return_value=0), patch(
        "readline.get_line_buffer", return_value=text
    ):
        return completer.tab_completer(text, 0)


@pytest.mark.parametrize("prefix", ["list", "l", "messages", "refresh", "exit"])
def test_readline_completes_bare_alias(monkeypatch, prefix):
    """The readline surface completes a bare alias."""
    assert _readline_complete(monkeypatch, "workspace", prefix) == prefix


def _run_tty_input(monkeypatch, scope, input_bytes):
    """Drive the raw TTY editor with *input_bytes* in *scope*."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "current_session_id", "s1")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    stdout = io.StringIO()
    mock_stdin = MagicMock()
    mock_stdin.isatty.return_value = True
    mock_stdin.fileno.return_value = 0
    mock_stdin.buffer = io.BytesIO(input_bytes)
    with patch("cli_topsailai.streaming.sys.stdin", mock_stdin), patch(
        "cli_topsailai.streaming.sys.stdout", stdout
    ), patch("cli_topsailai.streaming.termios") as mock_termios, patch(
        "cli_topsailai.streaming.tty"
    ):
        mock_termios.tcgetattr.return_value = []
        return _read_input_line_tty("", already_raw=True, session_id="s1")


@pytest.mark.parametrize("prefix", ["list", "l", "messages", "refresh", "exit"])
def test_raw_tty_completes_bare_alias(monkeypatch, prefix):
    """The raw TTY surface completes a bare alias."""
    assert _run_tty_input(monkeypatch, "workspace", prefix.encode() + b"\t\r") == prefix


def _make_ui():
    """Build a curses UI without starting a real terminal."""
    return CursesStreamUI(
        filepath="/tmp/test.log",
        task_dir="/tmp/tasks",
        log_files=[],
        default_session_id="s1",
        default_stdout_path="/tmp/tasks/s1.123.session.stdout",
        default_pid=123,
        command_handler=lambda _: True,
    )


@pytest.mark.parametrize("prefix", ["list", "l", "messages", "refresh", "exit"])
def test_curses_completes_bare_alias(monkeypatch, prefix):
    """The curses surface completes a bare alias and reports a redraw."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    ui = _make_ui()
    ui._input_buffer = prefix
    ui._cursor_pos = len(prefix)

    assert ui._handle_tab_completion() is True
    assert ui._input_buffer == prefix


@pytest.mark.parametrize("prefix", ["list", "l", "messages", "refresh", "exit"])
def test_all_three_surfaces_agree_on_the_candidate_set(monkeypatch, prefix):
    """Every surface resolves the same prefix to the same first candidate."""
    expected = candidates(monkeypatch, "workspace", prefix)[0]

    readline_result = _readline_complete(monkeypatch, "workspace", prefix)
    tty_result = _run_tty_input(monkeypatch, "workspace", prefix.encode() + b"\t\r")

    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    ui = _make_ui()
    ui._input_buffer = prefix
    ui._cursor_pos = len(prefix)
    ui._handle_tab_completion()

    assert readline_result == expected
    assert tty_result == expected
    assert ui._input_buffer == expected


def test_curses_cycles_through_every_candidate(monkeypatch):
    """Repeated TAB presses cycle through all candidates and wrap around."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    expected = candidates(monkeypatch, "workspace", "list")
    ui = _make_ui()
    ui._input_buffer = "list"
    ui._cursor_pos = 4

    seen = []
    for _ in range(len(expected)):
        ui._handle_tab_completion()
        seen.append(ui._input_buffer)
        ui._input_buffer = "list"
        ui._cursor_pos = 4

    assert seen == expected
