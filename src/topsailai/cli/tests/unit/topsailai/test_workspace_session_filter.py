"""Verify the ``workspace list -s`` session filter.

Author: DawsonLin
"""

import json
from argparse import Namespace
from unittest.mock import Mock

import pytest

from cli_topsailai import core, log_files, paths, session_meta


@pytest.fixture
def task_dir(tmp_path):
    """Create two sessions, one task row, and one identity-less log file."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    for name in (
        "alpha.111.session.stdout",
        "alpha.222.child.task.stdout",
        "beta.333.session.stdout",
        "generic.stdout",
    ):
        (directory / name).touch()
    for session_id, pid in (("alpha", 111), ("beta", 333)):
        (directory / f"{session_id}.{pid}.session.meta").write_text(json.dumps({
            "session_id": session_id, "pid": pid, "status": "running",
            "session_name": f"{session_id} name", "hostname": "host-a",
            "project_workspace": f"/work/{session_id}",
        }))
    return directory


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Point the one-shot printers at the isolated task directory."""
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    return tmp_path


def test_parse_selector_absent_means_no_filter():
    """A missing selector must stay ``None`` so no filtering happens."""
    assert log_files.parse_session_selector(None) is None


@pytest.mark.parametrize("value", ["", "   ", " , , "])
def test_parse_selector_rejects_empty_values(value):
    """An empty selector must never be read as "select everything"."""
    with pytest.raises(log_files.SessionSelectorError):
        log_files.parse_session_selector(value)


def test_parse_selector_rejects_non_string():
    """A non-string selector is a programming error, not a silent no-filter."""
    with pytest.raises(log_files.SessionSelectorError):
        log_files.parse_session_selector(123)


def test_parse_selector_strips_whitespace_and_drops_empty_segments():
    """Surrounding whitespace and trailing commas must not create empty IDs."""
    assert log_files.parse_session_selector(" alpha , beta , ") == ["alpha", "beta"]


def test_parse_selector_removes_duplicates_in_first_seen_order():
    """Duplicates collapse while the caller's order is preserved."""
    assert log_files.parse_session_selector("beta,alpha,beta") == ["beta", "alpha"]


@pytest.mark.parametrize("value", ["topsailai", "(temp)"])
def test_parse_selector_normalizes_the_temporary_identity(value):
    """Both the on-disk identity and the display label select the same rows."""
    assert log_files.parse_session_selector(value) == ["(temp)"]


def test_filter_disabled_returns_the_input_unchanged():
    """``None`` must be a true passthrough, including object identity."""
    rows = [{"session_id": "alpha"}, {"session_id": None}]

    assert log_files.filter_log_files_by_session(rows, None) is rows


def test_filter_keeps_the_session_and_its_task_rows(task_dir):
    """A task row shares its parent session ID and must never be split off."""
    rows = log_files.discover_log_files(str(task_dir))

    kept = log_files.filter_log_files_by_session(rows, ["alpha"])

    assert {row["filename"] for row in kept} == {
        "alpha.111.session.stdout", "alpha.222.child.task.stdout",
    }


def test_filter_excludes_rows_without_a_session_identity():
    """A generic log file cannot be selected by session ID."""
    rows = [{"session_id": None, "filename": "generic.stdout"}]

    assert log_files.filter_log_files_by_session(rows, ["alpha"]) == []




def test_discovery_selects_a_temporary_session_by_either_spelling(tmp_path):
    """A temp session is stored as ``topsailai`` but displayed as ``(temp)``."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / "topsailai.444.session.stdout").touch()
    (directory / "alpha.111.session.stdout").touch()

    for spelling in ("topsailai", "(temp)"):
        rows = log_files.discover_workspace_log_files(
            str(directory), session_ids=log_files.parse_session_selector(spelling),
        )
        assert [row["filename"] for row in rows] == ["topsailai.444.session.stdout"]


def test_discovery_applies_the_session_filter(task_dir):
    """Discovery must return only the selected session's rows."""
    rows = log_files.discover_workspace_log_files(str(task_dir), session_ids=["beta"])

    assert {row["session_id"] for row in rows} == {"beta"}


def test_discovery_without_a_selector_keeps_every_row(task_dir):
    """Omitting the selector must preserve the previous behavior exactly."""
    rows = log_files.discover_workspace_log_files(str(task_dir))

    assert {row["filename"] for row in rows} == {
        "alpha.111.session.stdout", "alpha.222.child.task.stdout",
        "beta.333.session.stdout", "generic.stdout",
    }


def test_unselected_rows_cost_no_metadata_read(task_dir, monkeypatch):
    """The filter must run before metadata reads, not after them."""
    spy = Mock(wraps=session_meta.read_session_meta)
    monkeypatch.setattr(session_meta, "read_session_meta", spy)

    log_files.discover_workspace_log_files(str(task_dir), session_ids=["alpha"])

    assert [call.args[1] for call in spy.call_args_list] == ["alpha"]


def test_include_completed_still_applies_inside_the_subset(task_dir):
    """``-a`` keeps its meaning, but only within the selected sessions."""
    (task_dir / "alpha.111.session.meta").write_text(json.dumps({
        "session_id": "alpha", "pid": 111, "status": "completed",
    }))

    hidden = log_files.discover_workspace_log_files(str(task_dir), session_ids=["alpha"])
    shown = log_files.discover_workspace_log_files(
        str(task_dir), include_completed=True, session_ids=["alpha"],
    )

    assert hidden == []
    assert {row["session_id"] for row in shown} == {"alpha"}


def test_handler_forwards_the_selector_to_the_table(monkeypatch):
    """The non-interactive handler must pass the parsed IDs to the table."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    code = core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, session="alpha,beta"),
    )

    assert code == 0
    table.assert_called_once_with(include_completed=False, session_ids=["alpha", "beta"], local_only=False)


def test_handler_forwards_the_selector_to_json(monkeypatch):
    """The JSON path must receive the same parsed selector."""
    printer = Mock()
    monkeypatch.setattr(core, "_print_workspace_json", printer)

    code = core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, json=True, session="alpha"),
    )

    assert code == 0
    printer.assert_called_once_with(include_completed=False, session_ids=["alpha"], local_only=False)


def test_handler_keeps_all_flag_with_a_selector(monkeypatch):
    """``-a`` and ``-s`` must compose instead of overriding each other."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, all=True, session="alpha"),
    )

    table.assert_called_once_with(include_completed=True, session_ids=["alpha"], local_only=False)


def test_handler_rejects_an_empty_selector(monkeypatch, capsys):
    """An empty selector must fail with a usage error instead of listing all."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    code = core._handle_workspace_subcommand(
        Namespace(workspace_command="list", format=None, session=""),
    )

    assert code == 2
    assert "Invalid session selector" in capsys.readouterr().err
    table.assert_not_called()


def test_cli_registers_the_short_and_long_option(monkeypatch):
    """Both spellings must reach the handler through the real parser."""
    table = Mock()
    monkeypatch.setattr(core, "_print_workspace_table", table)

    with pytest.raises(SystemExit) as short:
        core.main(["workspace", "list", "-s", "alpha"])
    with pytest.raises(SystemExit) as long:
        core.main(["workspace", "list", "--session", "alpha"])

    assert short.value.code == 0
    assert long.value.code == 0
    assert table.call_args_list == [
        ((), {"include_completed": False, "session_ids": ["alpha"], "local_only": False}),
        ((), {"include_completed": False, "session_ids": ["alpha"], "local_only": False}),
    ]


def test_cli_rejects_an_empty_selector_with_exit_two(monkeypatch, capsys):
    """The real parser path must exit 2 for an empty selector."""
    monkeypatch.setattr(core, "_print_workspace_table", Mock())

    with pytest.raises(SystemExit) as raised:
        core.main(["workspace", "list", "-s", ""])

    assert raised.value.code == 2
    assert "Invalid session selector" in capsys.readouterr().err


def test_json_total_describes_the_filtered_subset(task_dir, capsys):
    """``items`` and ``total`` must describe the same filtered subset."""
    core._print_workspace_json(session_ids=["alpha"])

    payload = json.loads(capsys.readouterr().out)

    assert payload["total"] == len(payload["items"]) == 2
    assert {item["session_id"] for item in payload["items"]} == {"alpha"}


def test_json_unknown_selector_yields_an_empty_document(task_dir, capsys):
    """A selector naming no session is an empty result, not an error."""
    core._print_workspace_json(session_ids=["missing"])

    payload = json.loads(capsys.readouterr().out)

    assert payload["items"] == []
    assert payload["total"] == 0


def test_table_warns_with_the_requested_ids_when_nothing_matches(task_dir, capsys):
    """The filtered-empty message must name the requested sessions."""
    core._print_workspace_table(session_ids=["missing"])

    out = capsys.readouterr().out

    assert "No log files found for the selected sessions: missing" in out
    assert "No .stdout log files found in:" not in out


def test_table_keeps_the_generic_warning_without_a_selector(tmp_path, monkeypatch, capsys):
    """Without a selector the original empty-directory message must remain."""
    empty = tmp_path / "empty" / "workspace" / "task"
    empty.mkdir(parents=True)
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path / "empty"))

    core._print_workspace_table()

    assert "No .stdout log files found in:" in capsys.readouterr().out
