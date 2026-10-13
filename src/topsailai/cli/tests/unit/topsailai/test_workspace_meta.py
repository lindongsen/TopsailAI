"""Verify current-row command selection without rescanning or scope changes.

Author: DawsonLin
"""

import pytest
from cli_topsailai import core, state


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Reset prompt globals through test-local injection."""
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(state, "yaml_commands", [])


@pytest.mark.parametrize("number", [1, 2])
def test_current_row(monkeypatch, number):
    """Return the exact current index, preserving both order and scope."""
    rows = [dict(session_id="first"), dict(session_id="last")]
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: f"/meta {number}")
    assert core.prompt_selection(rows, "/unused") == ("meta", number - 1)
    assert rows == [dict(session_id="first"), dict(session_id="last")]
    assert state.current_scope == "workspace"


@pytest.mark.parametrize("command", ["/meta", "/meta 0", "/meta -1", "/meta 3", "/meta x",
    "/meta " + "9" * 5000, "/meta 1 extra", "/meta 1 --json", "/meta --json"])
def test_bad_selection(monkeypatch, capsys, command):
    """Invalid arguments return to the prompt rather than dispatching."""
    inputs = iter([command, "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    assert core.prompt_selection([{}], "/unused") == ("quit", None)
    assert "[ERROR]" in capsys.readouterr().out


def test_empty_list(monkeypatch, capsys):
    """No index is valid against an empty current list."""
    inputs = iter(["/meta 1", "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    assert core.prompt_selection([], "/unused") == ("quit", None)
    assert "Invalid number" in capsys.readouterr().out


@pytest.mark.parametrize("scope,managed", [("project", False), ("session", False),
    ("doc", False), ("workspace", True)])
def test_scope_rejection(monkeypatch, capsys, scope, managed):
    """Reject unsupported scope before other command matching can run."""
    monkeypatch.setattr(state, "current_scope", scope)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", managed)
    inputs = iter(["/meta 1", "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    assert core.prompt_selection([{}], "/unused")[0] in ("quit", "leave_scope")
    assert "ordinary workspace task list" in capsys.readouterr().out


def test_main_dispatch_uses_displayed_row(monkeypatch, tmp_path):
    """Dispatch once without rediscovery, streaming or process operations."""
    from unittest.mock import Mock
    from cli_topsailai import (completer, formatting, history, log_files, paths,
                               process, session_info, session_meta, streaming,
                               yaml_commands)
    rows = [dict(session_id="first"), dict(session_id="last")]
    discover = Mock(return_value=rows)
    output = Mock()
    stream = Mock()
    monkeypatch.setattr(state, "running", True)
    monkeypatch.setattr(core, "setup_signal_handlers", Mock())
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(core, "_enrich_driver_rows", Mock())
    monkeypatch.setattr(core, "_reap_driver_children", Mock())
    monkeypatch.setattr(history, "HistoryManager", Mock())
    monkeypatch.setattr(history, "load_readline_history", Mock())
    monkeypatch.setattr(completer, "setup_tab_completion", Mock())
    monkeypatch.setattr(yaml_commands, "load_yaml_commands", Mock(return_value=[]))
    monkeypatch.setattr(paths, "get_topsailai_home", Mock(return_value=str(tmp_path)))
    monkeypatch.setattr(log_files, "discover_log_files", discover)
    monkeypatch.setattr(session_info, "enrich_files_with_session_names", Mock())
    monkeypatch.setattr(session_info, "enrich_running_unnamed_sessions", Mock())
    monkeypatch.setattr(formatting, "print_table", Mock())
    monkeypatch.setattr(process, "cleanup_children", Mock())
    monkeypatch.setattr(streaming, "stream_file", stream)
    monkeypatch.setattr(session_meta, "print_workspace_meta", output)
    inputs = iter(["/meta 2", "q"])
    monkeypatch.setattr(core, "_read_input_with_prompt", lambda _: next(inputs))
    core.main([])
    output.assert_called_once_with(str(tmp_path), rows[1])
    assert output.call_args.args[1] is rows[1]
    assert discover.call_count == 1
    assert state.current_scope == "workspace"
    stream.assert_not_called()
