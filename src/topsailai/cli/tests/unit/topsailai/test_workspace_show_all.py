"""Verify the workspace "r all" opt-in that reveals completed rows.

Author: DawsonLin
"""

import json
from unittest.mock import Mock

import pytest

from cli_topsailai import core, formatting, log_files, session_driver, session_info, state
from cli_topsailai.colors import Colors
from cli_topsailai.process_liveness import ProcessState


@pytest.fixture
def task_dir(tmp_path):
    """Create one completed session and one running session in isolation."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    for name in ("done.123.session.stdout", "done.123.session.stderr",
                 "done.456.child.task.stdout", "live.789.session.stdout"):
        (directory / name).touch()
    (directory / "done.123.session.meta").write_text(json.dumps({
        "session_id": "done", "pid": 123, "status": "completed",
        "session_name": "Done Session", "hostname": "host-a",
        "project_workspace": "/done",
    }))
    (directory / "live.789.session.meta").write_text(json.dumps({
        "session_id": "live", "pid": 789, "status": "running",
        "session_name": "Live Session", "hostname": "host-b",
        "project_workspace": "/live",
    }))
    return directory


@pytest.fixture(autouse=True)
def isolated_state(monkeypatch):
    """Keep module-level view state and host probes from leaking between tests."""
    monkeypatch.setattr(state, "workspace_show_completed", False)
    monkeypatch.setattr(state, "workspace_showing_managed_projects", False)
    monkeypatch.setattr(state, "current_scope", "workspace")
    monkeypatch.setattr(state, "history_manager", None)
    monkeypatch.setattr(state, "yaml_commands", [])
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    monkeypatch.setattr(formatting, "pid_state", Mock(return_value=ProcessState.ALIVE))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    return state


def status_cell(line):
    """Return the Status column of one rendered table row."""
    return line.split("|")[5].strip()


def find_row(lines, session_id):
    """Return the rendered row whose Session ID column matches."""
    for line in lines:
        cells = line.split("|")
        if len(cells) > 5 and cells[2].strip() == session_id:
            return line
    raise AssertionError(f"no rendered row for session {session_id!r}")


def test_default_discovery_still_hides_completed_rows(task_dir):
    """The opt-in must not change the default hidden behavior."""
    callback = Mock()

    rows = log_files.discover_workspace_log_files(str(task_dir), callback)

    assert {row["session_id"] for row in rows} == {"live"}
    assert callback.call_count == len(rows)


def test_include_completed_returns_session_and_task_rows(task_dir):
    """Opting in reveals the completed session and its child task rows."""
    callback = Mock()

    rows = log_files.discover_workspace_log_files(
        str(task_dir), callback, include_completed=True,
    )

    assert {row["filename"] for row in rows} == {
        "done.123.session.stdout", "done.123.session.stderr",
        "done.456.child.task.stdout", "live.789.session.stdout",
    }
    assert callback.call_count == len(rows)


def test_retained_completed_rows_keep_metadata_snapshot(task_dir):
    """Retained rows must keep the snapshot used by hostname and name enrichment."""
    rows = log_files.discover_workspace_log_files(str(task_dir), include_completed=True)
    completed = next(row for row in rows if row["filename"] == "done.123.session.stdout")

    assert completed["_workspace_meta_snapshot"][3]["status"] == "completed"
    assert completed["_workspace_meta_pid"] == 123

    formatting.enrich_workspace_rows(rows, str(task_dir.parent.parent))

    assert completed["hostname"] == "host-a"
    assert completed["workspace_completed"] is True


def test_completed_row_renders_done_marker(task_dir, capsys):
    """A revealed completed row is visibly distinct from an ordinary idle row."""
    rows = log_files.discover_workspace_log_files(str(task_dir), include_completed=True)
    formatting.enrich_workspace_rows(rows, str(task_dir.parent.parent))

    formatting.print_table(rows)

    lines = capsys.readouterr().out.splitlines()
    done_line = find_row(lines, "done")
    assert status_cell(done_line) == "DONE"
    assert Colors.GRAY in done_line


def test_exited_completed_row_is_still_marked(task_dir, monkeypatch, capsys):
    """A completed row whose process exited must still show DONE, not idle."""
    monkeypatch.setattr(formatting, "pid_state", Mock(return_value=ProcessState.DEAD))
    rows = log_files.discover_workspace_log_files(str(task_dir), include_completed=True)
    formatting.enrich_workspace_rows(rows, str(task_dir.parent.parent))
    completed = next(row for row in rows if row["filename"] == "done.123.session.stdout")

    assert completed["workspace_pid"] is None
    assert completed["workspace_completed"] is True

    formatting.print_table(rows)

    lines = capsys.readouterr().out.splitlines()
    done_line = find_row(lines, "done")
    assert status_cell(done_line) == "DONE"


def test_task_rows_are_not_marked_completed(task_dir):
    """Task rows keep the existing identity rule and are never marked DONE."""
    rows = log_files.discover_workspace_log_files(str(task_dir), include_completed=True)
    formatting.enrich_workspace_rows(rows, str(task_dir.parent.parent))

    task = next(row for row in rows if row["is_task"])
    assert task["workspace_completed"] is False


def test_json_item_exposes_completed_without_changing_status(task_dir):
    """JSON keeps the existing status contract and adds a separate flag."""
    rows = log_files.discover_workspace_log_files(str(task_dir), include_completed=True)
    formatting.enrich_workspace_rows(rows, str(task_dir.parent.parent))
    completed = next(row for row in rows if row["filename"] == "done.123.session.stdout")

    item = core._workspace_json_item(completed, 1)

    assert item["completed"] is True
    assert item["status"] == "idle"


@pytest.mark.parametrize("command", ["r all", "/r all", "refresh all", "/refresh all"])
def test_prompt_selection_accepts_all_spellings(monkeypatch, command):
    """Every documented spelling opts in to completed rows."""
    monkeypatch.setattr(core, "_read_input_with_prompt", Mock(return_value=command))

    assert core.prompt_selection([], "/task") == ("refresh", "all")


@pytest.mark.parametrize("command", ["r", "/refresh", "refresh"])
def test_prompt_selection_plain_refresh_resets(monkeypatch, command):
    """A plain refresh keeps the existing return contract."""
    monkeypatch.setattr(core, "_read_input_with_prompt", Mock(return_value=command))

    assert core.prompt_selection([], "/task") == ("refresh", None)


def test_prompt_selection_rejects_all_in_project_scope(isolated_state, monkeypatch, capsys):
    """Project scope keeps its own r [limit] contract."""
    isolated_state.current_scope = "project"
    monkeypatch.setattr(core, "_read_input_with_prompt", Mock(side_effect=["r all", "q"]))

    assert core.prompt_selection([], "/task") == ("quit", None)
    assert "Invalid limit" in capsys.readouterr().out


def test_prompt_selection_rejects_all_in_managed_view(isolated_state, monkeypatch, capsys):
    """The managed project sub-view keeps its restricted command set."""
    isolated_state.workspace_showing_managed_projects = True
    monkeypatch.setattr(core, "_read_input_with_prompt", Mock(side_effect=["r all", "q"]))

    assert core.prompt_selection([], "/task") == ("quit", None)
    assert "In projects list" in capsys.readouterr().out


def test_refresh_dispatch_sets_and_resets_flag(tmp_path, monkeypatch):
    """The refresh action owns the sticky view flag and forwards it to discovery."""
    from cli_topsailai import completer, history, paths

    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "done.123.session.stdout").write_text("log")
    (directory / "done.123.session.meta").write_text(json.dumps({
        "session_id": "done", "pid": 123, "status": "completed",
    }))
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(formatting, "print_table", Mock())
    monkeypatch.setattr(formatting, "print_header", Mock())
    monkeypatch.setattr(completer, "setup_tab_completion", Mock())
    monkeypatch.setattr(history, "load_readline_history", Mock())
    monkeypatch.setattr(history, "HistoryManager", Mock())
    discover = Mock(wraps=log_files.discover_workspace_log_files)
    monkeypatch.setattr(log_files, "discover_workspace_log_files", discover)
    monkeypatch.setattr(core, "prompt_selection", Mock(side_effect=[
        ("refresh", "all"), ("refresh", None), ("quit", None),
    ]))

    core.main([])

    flags = [call.kwargs.get("include_completed") for call in discover.call_args_list]
    assert flags[0] is False
    assert True in flags
    assert flags[-1] is False


def test_workspace_table_forwards_include_completed(tmp_path, monkeypatch, capsys):
    """The one-shot table entry honours the same opt-in."""
    from cli_topsailai import paths

    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "done.123.session.stdout").write_text("log")
    (directory / "done.123.session.meta").write_text(json.dumps({
        "session_id": "done", "pid": 123, "status": "completed",
        "session_name": "Done Session",
    }))
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))

    core._print_workspace_table()
    assert "done" not in capsys.readouterr().out

    core._print_workspace_table(include_completed=True)
    assert "done" in capsys.readouterr().out


def test_workspace_json_forwards_include_completed(tmp_path, monkeypatch, capsys):
    """The one-shot JSON entry honours the same opt-in."""
    from cli_topsailai import paths

    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "done.123.session.stdout").write_text("log")
    (directory / "done.123.session.meta").write_text(json.dumps({
        "session_id": "done", "pid": 123, "status": "completed",
    }))
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))

    core._print_workspace_json()
    assert json.loads(capsys.readouterr().out)["items"] == []

    core._print_workspace_json(include_completed=True)
    items = json.loads(capsys.readouterr().out)["items"]
    assert [item["session_id"] for item in items] == ["done"]
    assert items[0]["completed"] is True


def test_workspace_subcommand_forwards_all_flag(monkeypatch):
    """The non-interactive workspace subcommand mirrors the interactive opt-in."""
    from argparse import Namespace

    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    core._handle_workspace_subcommand(Namespace(workspace_command=None, format=None, all=True))

    table.assert_called_once_with(include_completed=True, session_ids=None, local_only=False)


def test_workspace_subcommand_defaults_to_hidden(monkeypatch):
    """A missing --all attribute must not reveal completed rows."""
    from argparse import Namespace

    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    core._handle_workspace_subcommand(Namespace(workspace_command=None, format=None))

    table.assert_called_once_with(include_completed=False, session_ids=None, local_only=False)


def test_workspace_json_exposes_verified_process_generation(monkeypatch):
    """Expose generation only when the live process owns its session stdout."""
    from cli_topsailai import agent_launch_process

    row = {
        "filename": "sample.1234.session.stdout",
        "path": "/task/sample.1234.session.stdout",
        "session_id": "sample",
        "pid": 1234,
        "workspace_pid": 1234,
        "is_task": False,
    }
    relation = Mock(return_value=True)
    identity = Mock(return_value=(1234, 987654))
    monkeypatch.setattr(log_files, "is_process_holding_file", relation)
    monkeypatch.setattr(agent_launch_process, "_process_identity", identity)

    item = core._workspace_json_item(row, 1)

    assert item["process_generation"] == 987654
    relation.assert_called_once_with(1234, row["path"])
    identity.assert_called_once_with(1234)


@pytest.mark.parametrize("change", [
    {"is_task": True},
    {"path": None},
    {"filename": "sample.1234.session.stderr"},
    {"filename": "sample.1234.stdout"},
])
def test_workspace_json_omits_unverified_process_generation(monkeypatch, change):
    """Task rows and incomplete evidence cannot mint kill authorization."""
    from cli_topsailai import agent_launch_process

    row = {
        "filename": "sample.1234.session.stdout",
        "path": "/task/sample.1234.session.stdout",
        "session_id": "sample",
        "pid": 1234,
        "workspace_pid": 1234,
        "is_task": False,
    }
    row.update(change)
    identity = Mock(return_value=(1234, 987654))
    monkeypatch.setattr(agent_launch_process, "_process_identity", identity)

    assert core._workspace_json_item(row, 1)["process_generation"] is None
    identity.assert_not_called()


def test_workspace_json_omits_generation_when_file_ownership_is_unverified(monkeypatch):
    """A reused PID without the original stdout relation is not authorized."""
    from cli_topsailai import agent_launch_process

    row = {
        "filename": "sample.1234.session.stdout",
        "path": "/task/sample.1234.session.stdout",
        "session_id": "sample",
        "pid": 1234,
        "workspace_pid": 1234,
        "is_task": False,
    }
    identity = Mock(return_value=(1234, 987654))
    monkeypatch.setattr(log_files, "is_process_holding_file", Mock(return_value=False))
    monkeypatch.setattr(agent_launch_process, "_process_identity", identity)

    assert core._workspace_json_item(row, 1)["process_generation"] is None
    identity.assert_not_called()
