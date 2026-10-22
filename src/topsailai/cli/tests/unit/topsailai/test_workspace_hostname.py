"""Verify metadata-only hostname resolution and safe workspace rendering.

Author: DawsonLin
"""

import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import formatting, log_files, runtime_control, session_driver
from cli_topsailai import session_info, session_meta
from cli_topsailai.workspace_hostname import enrich_workspace_hostnames


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    """Disable unrelated observations and reject any control-channel work."""
    monkeypatch.setattr(formatting, "os", SimpleNamespace(kill=Mock()))
    monkeypatch.setattr(formatting, "is_session_pipe_open", Mock(return_value=False))
    monkeypatch.setattr(session_driver, "observe_driver", Mock(return_value=None))
    monkeypatch.setattr(session_info, "_SESSION_INFO_CACHE", session_info._SessionInfoCache())
    for name in ("send_to_control", "build_socket_path"):
        monkeypatch.setattr(runtime_control, name,
                            Mock(side_effect=AssertionError("control path invoked")))
    yield
    runtime_control.send_to_control.assert_not_called()
    runtime_control.build_socket_path.assert_not_called()


def row(pid=123, task=False, sid="sample"):
    """Build a standard session or task row without using the live process."""
    suffix = "child.task.stdout" if task else "session.stdout"
    return dict(filename=f"{sid}.{pid}.{suffix}", session_id=sid, pid=pid,
                session_pid=123 if task else pid, is_task=task, ctime=1)


def write_meta(home, pid=123, sid="sample", **fields):
    """Write an exact test-owned session record."""
    directory = home / "workspace" / "task"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{sid}.{pid}.session.meta"
    path.write_text(json.dumps(dict(session_id=sid, pid=pid, status="running") | fields))
    return path


def cells(rows):
    """Return plain rendered header and first data row cells."""
    output = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", formatting.format_file_table(rows))
    lines = output.splitlines()
    return ([cell.strip() for cell in lines[0].split("|")],
            [cell.strip() for cell in lines[2].split("|")])


@pytest.mark.parametrize("alive", [True, False])
def test_hostname_present_independent_of_pid(tmp_path, alive):
    """Read origin hostname for both living and exited sessions."""
    write_meta(tmp_path, hostname="origin-host")
    if not alive:
        formatting.os.kill.side_effect = ProcessLookupError()
    rows = [row()]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    header, rendered = cells(rows)
    assert header[3:6] == ["PID", "Hostname", "Status"]
    assert rendered[4] == "origin-host"


@pytest.mark.parametrize("fields", [{}, {"hostname": ""}, {"hostname": None},
                                    {"hostname": []}, {"hostname": 42}])
def test_absent_or_invalid_value_is_empty(tmp_path, fields):
    """Do not substitute a placeholder or local hostname."""
    write_meta(tmp_path, **fields)
    rows = [row()]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert cells(rows)[1][4] == ""


@pytest.mark.parametrize("content", [None, "{broken", "[]",
    '{"session_id":"wrong","pid":123,"hostname":"bad"}'])
def test_unavailable_meta_is_empty(tmp_path, caplog, content):
    """Missing or corrupt records never abort rendering; genuine errors log."""
    if content is not None:
        write_meta(tmp_path).write_text(content)
    rows = [row()]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert cells(rows)[1][4] == ""
    assert bool(caplog.records) == (content is not None)


@pytest.mark.parametrize("error", [PermissionError("denied"), ValueError("safe_read_unsupported")])
def test_reader_failure_logged_and_empty(tmp_path, monkeypatch, caplog, error):
    """Use hardened-reader diagnostics without exposing metadata contents."""
    monkeypatch.setattr(session_meta, "_read_metadata", Mock(side_effect=error))
    rows = [row()]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert cells(rows)[1][4] == ""
    assert "123" in caplog.text and str(error) in caplog.text


@pytest.mark.parametrize("parents", [[], [123], [123, 789]])
def test_task_owner_uniqueness(tmp_path, monkeypatch, parents):
    """Never use a child PID, and never choose among ambiguous parents."""
    write_meta(tmp_path, hostname="parent-host")
    write_meta(tmp_path, pid=456, hostname="wrong-child-host")
    reader = Mock(wraps=session_meta.read_session_meta)
    monkeypatch.setattr(session_meta, "read_session_meta", reader)
    rows = [row(pid) for pid in parents] + [row(456, task=True)]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert rows[-1]["hostname"] == ("parent-host" if len(parents) == 1 else "")
    assert all(call.args[2] != 456 for call in reader.call_args_list)


def test_discovery_snapshot_reused_and_refresh_rereads(tmp_path, monkeypatch):
    """Reuse metadata across stdout/stderr/tasks/status but refresh next scan."""
    path = write_meta(tmp_path, hostname="first")
    directory = path.parent
    for name in ("sample.123.session.stdout", "sample.123.session.stderr",
                 "sample.456.child.task.stdout"):
        (directory / name).touch()
    reader = Mock(wraps=session_meta.read_session_meta)
    monkeypatch.setattr(session_meta, "read_session_meta", reader)
    rows = log_files.discover_workspace_log_files(str(directory))
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert reader.call_count == 1
    assert [r["hostname"] for r in rows] == ["first"] * 3
    write_meta(tmp_path, hostname="second")
    rows = log_files.discover_workspace_log_files(str(directory))
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert reader.call_count == 2
    assert all(r["hostname"] == "second" for r in rows)


def test_complete_name_cache_does_not_suppress_hostname(tmp_path, monkeypatch):
    """A cached session name does not suppress a hostname read during enrichment."""
    path = write_meta(tmp_path, hostname="origin")
    (path.parent / "sample.123.session.stdout").touch()
    (path.parent / "sample.123.session.stderr").touch()
    session_info._SESSION_INFO_CACHE.set("sample", ("Name", "/project"))
    reader = Mock(wraps=session_meta.read_session_meta)
    monkeypatch.setattr(session_meta, "read_session_meta", reader)
    rows = log_files.discover_workspace_log_files(str(path.parent))
    assert reader.call_count == 0
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert reader.call_count == 1
    assert all(r["hostname"] == "origin" for r in rows)


def test_filtered_parent_cannot_remove_ambiguity(tmp_path):
    """Filtering an unnamed completed parent cannot authorize task inheritance."""
    path = write_meta(tmp_path, hostname="first")
    write_meta(tmp_path, pid=789, status="completed", hostname="second")
    for name in ("sample.123.session.stdout", "sample.789.session.stdout",
                 "sample.456.child.task.stdout"):
        (path.parent / name).touch()
    rows = log_files.discover_workspace_log_files(str(path.parent))
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert len(rows) == 2
    assert next(r for r in rows if r["is_task"])["hostname"] == ""


@pytest.mark.parametrize("value,expected", [
    ("host\n\r\t\x00\x1bname|x\u2028\u2029\u202e", "hostnamex"),
    ("x" * 1000, "x" * 29 + "..."),
    ("界" * 100, "界" * 14 + "..."),
    ("   ", ""),
])
def test_sanitized_bounded_display(tmp_path, value, expected):
    """Remove control and separator injection and truncate by terminal width."""
    write_meta(tmp_path, hostname=value)
    rows = [row()]
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    header, rendered = cells(rows)
    assert len(header) == len(rendered) == 9
    assert rendered[4] == expected
    assert sum(formatting._character_display_width(c) for c in rendered[4]) <= 32


def test_temporary_session_and_task(tmp_path):
    """Reserved temporary IDs remain empty under the hardened reader policy."""
    path = write_meta(tmp_path, sid="topsailai", hostname="temp-host")
    for name in ("topsailai.123.session.stdout", "topsailai.456.child.task.stdout"):
        (path.parent / name).touch()
    rows = log_files.discover_workspace_log_files(str(path.parent))
    formatting.enrich_workspace_rows(rows, str(tmp_path))
    assert [r["hostname"] for r in rows] == ["", ""]


def test_invalid_and_generic_rows_do_not_read_metadata(tmp_path, monkeypatch):
    """Do not reinterpret generic logs or invalid PIDs as session records."""
    reader = Mock(side_effect=AssertionError("unexpected metadata lookup"))
    monkeypatch.setattr(session_meta, "read_session_meta", reader)
    rows = [row(pid=None), row(sid=""), dict(row(), filename="sample.123.stdout")]
    enrich_workspace_hostnames(rows, str(tmp_path))
    assert all(r["hostname"] == "" for r in rows)
    reader.assert_not_called()
