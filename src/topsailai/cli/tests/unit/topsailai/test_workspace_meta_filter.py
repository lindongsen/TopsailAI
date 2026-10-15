"""Verify metadata-only workspace filtering and unchanged session-info enrichment.

Author: DawsonLin
"""

import json
import os
from unittest.mock import Mock

import pytest

from cli_topsailai import log_files, session_info


@pytest.fixture
def task_dir(tmp_path):
    """Create session and child logs in an isolated task directory."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    for name in ("sample.123.session.stdout", "sample.123.session.stderr",
                 "sample.456.child.task.stdout"):
        (directory / name).touch()
    return directory


def write_meta(task_dir, **fields):
    """Write a matching session record with caller-provided fields."""
    data = dict(session_id="sample", pid=123, status="completed")
    data.update(fields)
    (task_dir / "sample.123.session.meta").write_text(json.dumps(data))


@pytest.mark.parametrize("fields", [{}, {"session_name": None},
                                     {"session_name": ""}, {"session_name": "  "}])
def test_completed_unnamed_hidden_before_callback(task_dir, fields):
    """Hide parent stdout/stderr and associated tasks before any display."""
    write_meta(task_dir, **fields)
    callback = Mock()
    assert log_files.discover_workspace_log_files(str(task_dir), callback) == []
    callback.assert_not_called()
    assert len(log_files.discover_log_files(str(task_dir))) == 3


@pytest.mark.parametrize("status,name", [("completed", " useful "),
                                        ("running", None), ("interrupted", ""),
                                        ("unknown", None)])
@pytest.mark.parametrize("workspace", [None, "/meta-project"])
def test_visible_meta_preserves_session_info_queries(task_dir, monkeypatch, status, name,
                                                    workspace):
    """Keep normal session-info enrichment for every visible metadata case."""
    write_meta(task_dir, status=status, session_name=name, project_workspace=workspace)
    query = Mock(return_value=session_info._LookupResult("queried", "/queried", True))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    callback = Mock()
    rows = log_files.discover_workspace_log_files(str(task_dir), callback)
    session_info.enrich_files_with_session_names(rows)
    assert len(rows) == callback.call_count == 3
    if status == "completed" and name:
        assert all(row["session_name"] == "useful" for row in rows)
        if workspace:
            assert query.call_count == 0
            assert all(row["project_workspace"] == "/meta-project" for row in rows)
        else:
            assert query.call_count == 1
            assert all(row["project_workspace"] == "/queried" for row in rows)
    else:
        assert query.call_count == 1
        assert all(row["session_name"] == "queried" for row in rows)
        assert all(row["project_workspace"] == "/queried" for row in rows)


def test_running_unnamed_meta_preserves_refresh_query(task_dir, monkeypatch):
    """Refresh a running unnamed session even after its first query was cached."""
    write_meta(task_dir, status="running", session_name=None)
    query = Mock(return_value=session_info._LookupResult("new name", "/queried", True))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    monkeypatch.setattr(session_info, "_is_pid_alive", Mock(return_value=True))
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    session_info._SESSION_INFO_CACHE.set("sample", (None, "/cached"))
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    rows = log_files.discover_workspace_log_files(str(task_dir))
    session_info.enrich_files_with_session_names(rows)
    query.assert_not_called()
    session_info.enrich_running_unnamed_sessions(rows)
    query.assert_called_once_with("sample")
    assert all(row["session_name"] == "new name" for row in rows)
    assert all(row["project_workspace"] == "/cached" for row in rows)


@pytest.mark.parametrize("content", [None, "{broken", "[]",
    '{"session_id":"other","pid":123,"status":"completed"}',
    '{"session_id":"sample","pid":999,"status":"completed"}'])
def test_unavailable_meta_keeps_rows_and_existing_fallback(task_dir, monkeypatch, content):
    """Do not hide entries without validated completion evidence."""
    if content is not None:
        (task_dir / "sample.123.session.meta").write_text(content)
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    query = Mock(return_value=session_info._LookupResult("fallback", "/fallback", True))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    monkeypatch.setattr(session_info, "load_project_workspace_lookup", Mock(return_value={}))
    rows = log_files.discover_workspace_log_files(str(task_dir))
    session_info.enrich_files_with_session_names(rows)
    assert len(rows) == 3
    assert all(row["session_name"] == "fallback" for row in rows)
    query.assert_called_once_with("sample")


def test_metadata_reread_each_refresh(task_dir):
    """A newly completed unnamed session disappears on the next refresh."""
    write_meta(task_dir, status="running")
    assert len(log_files.discover_workspace_log_files(str(task_dir))) == 3
    write_meta(task_dir)
    assert log_files.discover_workspace_log_files(str(task_dir)) == []


def test_orphan_and_temporary_rows_preserved(task_dir):
    """Do not infer parent metadata from an unrelated PID or temporary ID."""
    write_meta(task_dir)
    (task_dir / "other.789.child.task.stdout").touch()
    (task_dir / "topsailai.321.session.stdout").touch()
    rows = log_files.discover_workspace_log_files(str(task_dir))
    assert {row["session_id"] for row in rows} == {"other", "(temp)"}


@pytest.mark.parametrize("output", ["table", "json"])
def test_workspace_output_uses_filtered_rows(task_dir, monkeypatch, capsys, output):
    """Exercise both one-shot workspace entries without enrichment queries."""
    from cli_topsailai import core, paths

    write_meta(task_dir)
    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(task_dir.parent.parent))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(core, "_enrich_driver_rows", Mock())
    query = Mock(side_effect=AssertionError("unexpected session-info lookup"))
    monkeypatch.setattr(session_info, "_get_session_info", query)
    if output == "json":
        core._print_workspace_json()
        assert json.loads(capsys.readouterr().out)["items"] == []
    else:
        core._print_workspace_table()
        assert "sample" not in capsys.readouterr().out
    query.assert_not_called()


def test_refreshes_completed_snapshot_order_and_public_json(tmp_path, monkeypatch, capsys):
    """A fresh scan adopts changed metadata without changing order or JSON schema."""
    from cli_topsailai import core, paths

    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    first = directory / "first.101.session.stdout"
    second = directory / "second.202.session.stdout"
    first.write_text("log")
    second.write_text("log")
    times = {first.name: 10.0, second.name: 20.0}
    monkeypatch.setattr(
        log_files, "_get_birth_time",
        lambda path: times[os.path.basename(path)],
    )

    def write(session_id, pid, name):
        (directory / f"{session_id}.{pid}.session.meta").write_text(json.dumps({
            "session_id": session_id,
            "pid": pid,
            "status": "completed",
            "session_name": name,
            "project_workspace": f"/{session_id}",
        }))

    write("first", 101, "Old First")
    write("second", 202, "Second")
    rows = log_files.discover_workspace_log_files(str(directory))
    assert [row["filename"] for row in rows] == [first.name, second.name]
    assert [row["_completed_session_meta"][2] for row in rows] == ["Old First", "Second"]

    write("first", 101, "New First")
    refreshed = log_files.discover_workspace_log_files(str(directory))
    assert [row["filename"] for row in refreshed] == [first.name, second.name]
    assert [row["_completed_session_meta"][2] for row in refreshed] == ["New First", "Second"]

    monkeypatch.setattr(paths, "get_topsailai_home", lambda: str(tmp_path))
    monkeypatch.setattr(core, "_driver_authority", Mock(return_value=None))
    monkeypatch.setattr(core, "_enrich_driver_rows", Mock())
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    monkeypatch.setattr(
        session_info, "_get_session_info",
        Mock(side_effect=AssertionError("unexpected query")),
    )
    core._print_workspace_json()
    payload = json.loads(capsys.readouterr().out)
    assert [item["no"] for item in payload["items"]] == [1, 2]
    assert [item["filename"] for item in payload["items"]] == [first.name, second.name]
    assert "_completed_session_meta" not in json.dumps(payload)


@pytest.mark.parametrize("reverse", [False, True])
def test_ambiguous_task_parent_kept_in_both_directory_orders(task_dir, monkeypatch, reverse):
    """Keep ambiguous tasks regardless of conflicting parent metadata or scan order."""
    write_meta(task_dir, status="running")
    (task_dir / "sample.999.session.stdout").touch()
    (task_dir / "sample.999.session.meta").write_text(json.dumps({
        "session_id": "sample", "pid": 999, "status": "completed",
    }))
    entries = sorted(log_files.os.listdir(task_dir), reverse=reverse)
    isolated_os = Mock(wraps=log_files.os)
    isolated_os.listdir.return_value = entries
    monkeypatch.setattr(log_files, "os", isolated_os)
    callback = Mock()

    rows = log_files.discover_workspace_log_files(str(task_dir), callback)

    assert {row["filename"] for row in rows} == {
        "sample.123.session.stdout", "sample.123.session.stderr",
        "sample.456.child.task.stdout",
    }
    task = next(row for row in rows if row["is_task"])
    assert "session_meta_loaded" not in task
    assert "session_name" not in task
    assert "_completed_session_meta" not in task
    assert [call.args[0] for call in callback.call_args_list] == rows
