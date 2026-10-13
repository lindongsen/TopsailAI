"""Test bounded exact-session snapshots and workspace display.

Author: DawsonLin
"""

import json
import os
from unittest.mock import Mock

import pytest

from cli_topsailai import session_meta as meta


@pytest.fixture
def source(tmp_path):
    """Create a test-owned session record and its exact row."""
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    path = directory / "sample.123.session.meta"
    path.write_text('{ "session_id": "sample", "pid": 123, "status": "unknown", "extra": [1] }')
    row = dict(session_id="sample", pid=123, session_pid=123,
               filename="sample.123.session.stdout", workspace_pid=None)
    return tmp_path, path, row


@pytest.mark.parametrize("suffix", ["stdout", "stderr"])
@pytest.mark.parametrize("newline", ["", "\n"])
def test_original_text_and_output(source, capsys, suffix, newline):
    """Preserve unknown fields, raw formatting, exited identity and newline."""
    home, path, row = source
    row["filename"] = f"sample.123.session.{suffix}"
    text = path.read_text() + newline
    path.write_text(text)
    result = meta.read_session_meta(str(home), "sample", 123)
    assert result.path == path and result.text == text
    assert result.data["extra"] == [1]
    before = dict(row)
    assert meta.print_workspace_meta(str(home), row)
    output = capsys.readouterr().out
    assert output.split("\n", 1)[1] == text.rstrip("\n") + "\n"
    assert row == before and path.read_text() == text


@pytest.mark.parametrize("content,category", [
    ('{"session_id":"other","pid":123}', "identity_mismatch"),
    ('{"session_id":"sample","pid":124}', "identity_mismatch"),
    ('{"session_id":"sample","pid":"123"}', "identity_mismatch"),
    ('{"session_id":"sample","pid":true}', "identity_mismatch"),
    ('{}', "identity_mismatch"), ('[]', "invalid_object"),
    ('null', "invalid_object"), ('', "JSONDecodeError"),
    ('{"secret":"body-hidden",broken', "JSONDecodeError"),
    ('[' * 2000, "metadata_too_deep"),
])
def test_invalid_body_hidden(source, capsys, caplog, content, category):
    """Reject invalid JSON or identity without printing/logging its contents."""
    home, path, row = source
    path.write_text(content)
    assert not meta.print_workspace_meta(str(home), row)
    assert category in capsys.readouterr().out
    assert "body-hidden" not in caplog.text


def test_encoding(source):
    """Invalid UTF-8 is diagnosed as encoding rather than JSON."""
    home, path, _ = source
    path.write_bytes(b"\xff")
    with pytest.raises(meta.SessionMetaError, match="UnicodeDecodeError"):
        meta.read_session_meta(str(home), "sample", 123)


@pytest.mark.parametrize("delta", [0, 1])
def test_size_boundary(source, delta):
    """Read exactly 64 KiB but reject limit plus one without truncation."""
    home, path, _ = source
    body = path.read_bytes()
    path.write_bytes(body + b" " * (65536 + delta - len(body)))
    if delta:
        with pytest.raises(meta.SessionMetaError, match="metadata_too_large"):
            meta.read_session_meta(str(home), "sample", 123)
    else:
        assert len(meta.read_session_meta(str(home), "sample", 123).text) == 65536


@pytest.mark.parametrize("pid", [True, "123", 0, -1, None])
def test_invalid_pid(source, pid):
    """Only strict positive integers authorize a read."""
    home, _, _ = source
    with pytest.raises(meta.SessionMetaError, match="invalid_pid"):
        meta.read_session_meta(str(home), "sample", pid)


@pytest.mark.parametrize("session", ["../x", "a/b", "a\\b", "a..b", "topsailai", "(temp)", "bad!", None])
def test_invalid_session(source, session):
    """Reject unsafe and temporary identities before opening any file."""
    home, _, _ = source
    with pytest.raises(meta.SessionMetaError, match="unsafe_session_id"):
        meta.read_session_meta(str(home), session, 123)


@pytest.mark.parametrize("changes", [
    {"is_task": True}, {"pid": True}, {"pid": "123"}, {"pid": 0},
    {"session_pid": True}, {"session_pid": 124}, {"filename": "sample.123.stdout"},
    {"session_id": "topsailai", "filename": "topsailai.123.session.stdout"},
])
def test_unsupported_row(source, capsys, changes):
    """Task/legacy/temporary rows cannot cause parent or fallback reads."""
    home, _, row = source
    row.update(changes)
    assert not meta.print_workspace_meta(str(home), row)
    output = capsys.readouterr().out
    assert "[ERROR]" in output
    if changes.get("is_task"):
        assert "select the corresponding session row" in output


def test_absent_session_pid_allowed(source):
    """An exact standard filename needs no synthetic parent PID."""
    home, _, row = source
    row.pop("session_pid")
    assert meta.print_workspace_meta(str(home), row)


def test_missing_does_not_fallback(source):
    """Another existing PID cannot substitute for the requested record."""
    home, _, _ = source
    with pytest.raises(meta.SessionMetaError, match="missing"):
        meta.read_session_meta(str(home), "sample", 124)


@pytest.mark.parametrize("error", [PermissionError("denied"), FileNotFoundError("gone")])
def test_io_failure(source, monkeypatch, error):
    """Disappearance and permission errors are classified without a traceback."""
    home, _, _ = source
    monkeypatch.setattr(meta, "_read_metadata", Mock(side_effect=error))
    with pytest.raises(meta.SessionMetaError, match="missing|PermissionError"):
        meta.read_session_meta(str(home), "sample", 123)


def test_missing_directory(tmp_path):
    """Absent directory custody is also a missing record."""
    with pytest.raises(meta.SessionMetaError, match="missing"):
        meta.read_session_meta(str(tmp_path), "sample", 123)


def test_invalid_home(source):
    """Reject an untrusted nonabsolute deployment root."""
    with pytest.raises(meta.SessionMetaError, match="invalid_home"):
        meta.read_session_meta("relative", "sample", 123)


def test_symlink(source):
    """Metadata symlinks are never followed."""
    home, path, _ = source
    alias = path.with_name("sample.124.session.meta")
    alias.symlink_to(path)
    with pytest.raises(meta.SessionMetaError, match="metadata_not_regular"):
        meta.read_session_meta(str(home), "sample", 124)


def test_fifo(source):
    """Nonregular file rejection happens before any potentially blocking read."""
    home, path, _ = source
    fifo = path.with_name("sample.124.session.meta")
    os.mkfifo(fifo)
    with pytest.raises(meta.SessionMetaError, match="metadata_not_regular"):
        meta.read_session_meta(str(home), "sample", 124)


def test_directory_symlink(source, tmp_path):
    """A workspace alias below the trusted root cannot redirect the reader."""
    home, _, _ = source
    alias = tmp_path / "alias"
    alias.mkdir()
    (alias / "workspace").symlink_to(home / "workspace", target_is_directory=True)
    with pytest.raises(meta.SessionMetaError, match="OSError|NotADirectoryError"):
        meta.read_session_meta(str(alias), "sample", 123)


def test_trusted_home_alias(source, tmp_path):
    """Only the explicitly trusted home may be a resolved alias."""
    home, _, _ = source
    alias = tmp_path / "home-alias"
    alias.symlink_to(home, target_is_directory=True)
    assert meta.read_session_meta(str(alias), "sample", 123).data["pid"] == 123


def test_string_brackets_and_escapes(source):
    """Do not count quoted brackets or escaped quotes as structural depth."""
    home, path, _ = source
    path.write_text(json.dumps(dict(session_id="sample", pid=123,
                                   text='[' * 100 + '\"\\]')))
    assert meta.read_session_meta(str(home), "sample", 123).data["pid"] == 123


def test_parser_recursion_failure(source, monkeypatch):
    """Unexpected decoder recursion errors still produce a safe category."""
    home, _, _ = source
    monkeypatch.setattr(meta, "json", type("Parser", (), {
        "loads": Mock(side_effect=RecursionError()), "JSONDecodeError": json.JSONDecodeError}))
    with pytest.raises(meta.SessionMetaError, match="RecursionError"):
        meta.read_session_meta(str(home), "sample", 123)


def test_unsupported_safe_reader(source, monkeypatch):
    """Fail closed when the platform cannot provide safe directory reads."""
    from types import SimpleNamespace
    from cli_topsailai import session_driver
    home, _, _ = source
    monkeypatch.setattr(session_driver, "os", SimpleNamespace())
    with pytest.raises(meta.SessionMetaError, match="safe_read_unsupported"):
        meta.read_session_meta(str(home), "sample", 123)


@pytest.mark.parametrize("depth", [64, 65])
def test_depth_boundary(source, depth):
    """The outer object counts as one level of the deterministic limit."""
    home, path, _ = source
    path.write_text('{"session_id":"sample","pid":123,"x":' +
                    '[' * (depth - 1) + '0' + ']' * (depth - 1) + '}')
    if depth == 65:
        with pytest.raises(meta.SessionMetaError, match="metadata_too_deep"):
            meta.read_session_meta(str(home), "sample", 123)
    else:
        assert meta.read_session_meta(str(home), "sample", 123).data["pid"] == 123


@pytest.mark.parametrize("session", ["sample", "sample.with.dots"])
@pytest.mark.parametrize("suffix", ["stdout", "stderr"])
def test_discovered_session_row(tmp_path, capsys, session, suffix):
    """Read exact metadata from real discovered standard session rows."""
    from cli_topsailai.log_files import discover_log_files
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / f"{session}.123.session.{suffix}").write_text("log")
    body = json.dumps(dict(session_id=session, pid=123, status="completed"))
    path = directory / f"{session}.123.session.meta"
    path.write_text(body)
    rows = discover_log_files(str(directory))
    assert len(rows) == 1
    assert rows[0]["session_id"] == session
    assert rows[0]["pid"] == rows[0]["session_pid"] == 123
    assert not rows[0]["is_task"]
    assert meta.print_workspace_meta(str(tmp_path), rows[0])
    assert capsys.readouterr().out.split("\n", 1)[1] == body + "\n"
    assert path.read_text() == body


@pytest.mark.parametrize("filename", ["topsailai.123.session.stderr", "legacy.123.stderr",
                                      "sample.123.task.stdout"])
def test_discovery_preserves_unsupported_boundaries(tmp_path, capsys, filename):
    """Discovery does not authorize legacy, temporary or task metadata reads."""
    from cli_topsailai.log_files import discover_log_files
    directory = tmp_path / "workspace" / "task"
    directory.mkdir(parents=True)
    (directory / filename).write_text("log")
    row, = discover_log_files(str(directory))
    assert row["pid"] == 123
    assert not meta.print_workspace_meta(str(tmp_path), row)
    assert "[ERROR]" in capsys.readouterr().out


def test_discovery_skips_invalid_entries_and_preserves_time(tmp_path, monkeypatch):
    """Skip nonfiles and malformed standard names without losing valid stderr."""
    from cli_topsailai import log_files
    (tmp_path / "folder.stdout").mkdir()
    (tmp_path / "sample.bad.session.stderr").write_text("invalid")
    (tmp_path / "sample.123.session.stderr").write_text("valid")
    monkeypatch.setattr(log_files, "_get_birth_time", lambda _: None)
    rows = log_files.discover_log_files(str(tmp_path))
    assert len(rows) == 1 and rows[0]["pid"] == 123
    assert rows[0]["ctime"] == (tmp_path / rows[0]["filename"]).stat().st_ctime
    assert log_files._parse_stdout_filename(".stderr") == (None, None)
