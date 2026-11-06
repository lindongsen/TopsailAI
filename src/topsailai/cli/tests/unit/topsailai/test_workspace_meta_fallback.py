"""Verify the workspace-scope fallback to exact session .meta records.

Author: DawsonLin
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import (
    agent_launch_process,
    core,
    formatting,
    log_files,
    session_driver,
    session_info,
    session_meta,
)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Keep liveness, driver and cache state isolated from the live host."""
    monkeypatch.setattr(formatting, "os", SimpleNamespace(kill=Mock()))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))


def write_meta(home, pid=123, sid="sample", **fields):
    """Write one exact test-owned session record."""
    directory = home / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sid}.{pid}.session.meta"
    path.write_text(json.dumps(dict(session_id=sid, pid=pid, status="running") | fields))
    return path


def make_rows(home, names):
    """Discover rows from a test-owned task directory."""
    directory = home / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    for name in names:
        (directory / name).touch()
    return log_files.discover_workspace_log_files(str(directory))


def fail_lookup(monkeypatch):
    """Make the primary session-info lookup fail like a timeout."""
    query = Mock(return_value=session_info._LookupResult(None, None, False))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    return query


def pid_cell(rows):
    """Return the rendered PID column of the first data row."""
    output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", formatting.format_file_table(rows))
    return output.splitlines()[2].split("|")[3].strip()


def test_missing_name_falls_back_to_exact_meta_record(tmp_path, monkeypatch):
    """A failed primary lookup still renders the recorded session name."""
    fail_lookup(monkeypatch)
    write_meta(tmp_path, session_name="Recorded Name")
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    session_info.enrich_files_with_session_names(rows)

    assert rows[0]["session_name"] == "Recorded Name"


def test_failed_lookup_renders_name_and_project_workspace(tmp_path, monkeypatch):
    """Both fallback fields come from the same exact record."""
    fail_lookup(monkeypatch)
    write_meta(tmp_path, session_name="Recorded Name", project_workspace="/recorded/project")
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    session_info.enrich_files_with_session_names(rows)

    assert rows[0]["session_name"] == "Recorded Name"
    assert rows[0]["project_workspace"] == "/recorded/project"


def test_primary_lookup_wins_over_meta(tmp_path, monkeypatch):
    """The fallback never replaces a successful primary resolution."""
    query = Mock(return_value=session_info._LookupResult("Primary Name", "/primary", True))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    write_meta(tmp_path, session_name="Recorded Name", project_workspace="/recorded/project")
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    session_info.enrich_files_with_session_names(rows)

    assert rows[0]["session_name"] == "Primary Name"
    assert rows[0]["project_workspace"] == "/primary"


@pytest.mark.parametrize("fields,name,workspace", [
    ({"pid": 999}, None, None),
    ({"session_id": "other"}, None, None),
    ({"session_name": "   "}, None, "/recorded/project"),
    ({"project_workspace": "relative/path"}, "Recorded Name", None),
])
def test_mismatched_or_unusable_record_is_rejected(tmp_path, monkeypatch, fields,
                                                   name, workspace):
    """A record for another identity is never reused; each field is independent."""
    fail_lookup(monkeypatch)
    record = {"session_name": "Recorded Name", "project_workspace": "/recorded/project"}
    record.update(fields)
    write_meta(tmp_path, **record)
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    session_info.enrich_files_with_session_names(rows)

    assert rows[0]["session_name"] == name
    assert rows[0]["project_workspace"] == workspace


def test_exited_session_renders_meta_pid(tmp_path, monkeypatch):
    """An exited session shows the PID recorded in its exact record."""
    formatting.os.kill.side_effect = ProcessLookupError()
    write_meta(tmp_path)
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    formatting.enrich_workspace_rows(rows, str(tmp_path))

    assert rows[0]["workspace_pid"] is None
    assert rows[0]["workspace_display_pid"] == 123
    assert pid_cell(rows) == "123"
    assert core._workspace_json_item(rows[0], 1)["pid"] == 123


def test_exited_session_keeps_no_signal_authority(tmp_path, monkeypatch):
    """The display PID never grants kill authority or a process generation."""
    formatting.os.kill.side_effect = ProcessLookupError()
    # A dead process cannot hold its session stdout file, so the relation probe
    # reports the truth and no generation can be minted from the display PID.
    relation = Mock(return_value=False)
    identity = Mock(return_value=(123, 987654))
    monkeypatch.setattr(log_files, "is_process_holding_file", relation)
    monkeypatch.setattr(agent_launch_process, "_process_identity", identity)
    write_meta(tmp_path)
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    formatting.enrich_workspace_rows(rows, str(tmp_path))
    item = core._workspace_json_item(rows[0], 1)

    assert rows[0]["workspace_pid"] is None
    assert item["pid"] == 123
    assert item["process_generation"] is None
    identity.assert_not_called()


def test_live_session_keeps_verified_pid_and_generation(tmp_path, monkeypatch):
    """A live session keeps its liveness-verified PID and generation."""
    relation = Mock(return_value=True)
    identity = Mock(return_value=(123, 987654))
    monkeypatch.setattr(log_files, "is_process_holding_file", relation)
    monkeypatch.setattr(agent_launch_process, "_process_identity", identity)
    write_meta(tmp_path)
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    formatting.enrich_workspace_rows(rows, str(tmp_path))
    item = core._workspace_json_item(rows[0], 1)

    assert rows[0]["workspace_pid"] == 123
    assert rows[0]["workspace_display_pid"] == 123
    assert item["pid"] == 123
    assert item["process_generation"] == 987654


def test_temporary_row_reads_reserved_prefix_record(tmp_path):
    """A temporary row resolves its hostname through the reserved prefix."""
    write_meta(tmp_path, sid="topsailai", hostname="temp-host")
    rows = make_rows(tmp_path, ["topsailai.123.session.stdout"])

    formatting.enrich_workspace_rows(rows, str(tmp_path))

    assert rows[0]["session_id"] == "(temp)"
    assert rows[0]["hostname"] == "temp-host"


@pytest.mark.parametrize("content", [None, "{broken", "[]"])
def test_absent_or_corrupt_record_renders_empty(tmp_path, monkeypatch, content):
    """Missing or corrupt records never abort the table."""
    fail_lookup(monkeypatch)
    formatting.os.kill.side_effect = ProcessLookupError()
    if content is not None:
        write_meta(tmp_path).write_text(content)
    rows = make_rows(tmp_path, ["sample.123.session.stdout"])

    session_info.enrich_files_with_session_names(rows)
    formatting.enrich_workspace_rows(rows, str(tmp_path))

    assert rows[0]["session_name"] is None
    assert rows[0]["workspace_display_pid"] is None
    assert pid_cell(rows) == "-"


def test_completed_filter_and_json_fields_are_unchanged(tmp_path, monkeypatch):
    """Completed filtering, the DONE marker and the JSON field set stay stable."""
    fail_lookup(monkeypatch)
    formatting.os.kill.side_effect = ProcessLookupError()
    write_meta(tmp_path, status="completed", session_name="Done Session")
    write_meta(tmp_path, pid=789, sid="live", session_name="Live Session")
    rows = make_rows(tmp_path, ["sample.123.session.stdout", "live.789.session.stdout"])

    assert [row["session_id"] for row in rows] == ["live"]

    rows = log_files.discover_workspace_log_files(
        str(tmp_path / "workspace" / "task"), include_completed=True,
    )
    session_info.enrich_files_with_session_names(rows)
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    completed = next(row for row in rows if row["session_id"] == "sample")

    assert completed["workspace_completed"] is True
    assert completed["session_name"] == "Done Session"
    assert set(core._workspace_json_item(completed, 1)) == {
        "no", "filename", "session_name", "session_id", "is_task", "pid",
        "process_generation", "status", "completed", "driver", "created_at",
        "project_workspace",
    }
