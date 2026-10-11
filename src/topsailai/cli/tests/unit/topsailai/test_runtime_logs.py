"""Bounded offline log reads using only fixture-owned evidence.

Author: DawsonLin
"""

import errno
import io
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from cli_topsailai import runtime_logs as logs


def target(folder, data=b"", name="session.x.123.session.stdout"):
    """Create one synthetic log and resolve its offline identity."""
    (folder / name).write_bytes(data)
    return logs.resolve_log_target(folder, pid=123)


@pytest.mark.parametrize("data,expected", [
    (b"", []), (b"a", ["a"]), (b"a\n", ["a"]),
    (b"\n", [""]), (b"a\n\n", ["a", ""]),
    (b"a\r\nb\r", ["a", "b\r"]), (b"a\rb\n", ["a\rb"]),
    ("雪\n☃\u2028x".encode(), ["雪", "☃\u2028x"]),
    (b"\xff\n", ["�"]),
])
@pytest.mark.parametrize("chunk", [1, 2, 65536])
def test_records(tmp_path, data, expected, chunk):
    """Physical records preserve lone CR, Unicode and empty lines."""
    result = logs.read_log_tail(target(tmp_path, data), 20, chunk_size=chunk)
    assert list(result.lines) == expected
    assert result.total_lines == len(expected)
    assert not result.truncated and not result.scan_limited
    assert result.bytes_read == len(data)
    assert result.response()["returned_lines"] == len(expected)


@pytest.mark.parametrize("data", [b"a\nb\nc", b"a\nb\nc\n"])
@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_counts(tmp_path, data, count):
    """Tail results stay chronological with accurate BOF completeness."""
    result = logs.read_log_tail(target(tmp_path, data), count, chunk_size=1)
    assert list(result.lines) == ["a", "b", "c"][-count:]
    assert result.truncated == (count < 3)
    assert result.total_lines in (None, 3)


@pytest.mark.parametrize("data,budget,expected", [
    (b"longprefix\nx\ny", 5, ["x", "y"]),
    (b"abcdefghijk", 4, []), (b"abcdefgh\n", 4, []),
])
def test_scan_limit(tmp_path, data, budget, expected):
    """Budget cuts drop incomplete fragments and explicitly mark partial output."""
    result = logs.read_log_tail(target(tmp_path, data), 20, chunk_size=2, budget=budget)
    assert list(result.lines) == expected
    assert result.scan_limited and result.truncated
    assert result.total_lines is None and result.bytes_read == budget


def test_large_bounded_scan():
    """Every read has an explicit bounded size and never exceeds snapshot EOF."""
    class Stream(io.BytesIO):
        """Record read sizes for a large in-memory fixture."""

        def read(self, size=-1):
            """Require bounded reads inside the captured snapshot."""
            assert 0 < size <= 65536
            assert self.tell() + size <= initial
            return super().read(size)

    initial = logs.SCAN_BUDGET + 1024
    stream = Stream(b"x" * initial + b"appended")
    lines, total, truncated, limited, amount = logs._scan(stream, initial, 20, 65536, logs.SCAN_BUDGET)
    assert lines == () and total is None and truncated and limited
    assert amount == logs.SCAN_BUDGET


@pytest.mark.parametrize("selectors", [{"session_id": "session.x"}, {"pid": 123},
                                       {"session_id": "session.x", "pid": 123}])
def test_offline_selection(tmp_path, selectors):
    """Dead or idle evidence is usable without process observation."""
    item = target(tmp_path)
    assert logs.resolve_log_target(tmp_path, **selectors) == item


@pytest.mark.parametrize("name,session", [("topsailai.123.session.stdout", "topsailai"),
                                         ("a.b.123.session.stdout", "a.b")])
def test_session_names(tmp_path, name, session):
    """Temporary and dotted identifiers remain literal."""
    assert target(tmp_path, name=name).session_id == session


@pytest.mark.parametrize("selectors,code", [
    ({}, "usage_error"), ({"pid": True}, "usage_error"), ({"pid": 0}, "usage_error"),
    ({"pid": "123"}, "usage_error"), ({"session_id": "../x"}, "usage_error"),
    ({"session_id": []}, "usage_error"), ({"session_id": ""}, "usage_error"),
    ({"session_id": "other", "pid": 123}, "target_mismatch"),
    ({"pid": 456}, "target_not_found"),
])
def test_invalid_selection(tmp_path, selectors, code):
    """Reject invalid selectors and strict intersection mismatches."""
    target(tmp_path)
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.resolve_log_target(tmp_path, **selectors)
    assert error.value.error_code == code


def test_ambiguous_and_no_task_fallback(tmp_path):
    """Historical matches stay ambiguous and task logs cannot substitute."""
    target(tmp_path)
    (tmp_path / "session.x.456.session.stdout").touch()
    with pytest.raises(logs.RuntimeTargetError, match="exact") as error:
        logs.resolve_log_target(tmp_path, session_id="session.x")
    assert error.value.error_code == "ambiguous_target"
    (tmp_path / "task.789.extra.task.stdout").touch()
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.resolve_log_target(tmp_path, pid=789)
    assert error.value.error_code == "target_not_found"


def test_directory_rules(tmp_path):
    """Reject missing, relative, traversal and final symlink directories."""
    for folder, code in [(tmp_path / "missing", "target_not_found"),
                         (Path("relative"), "usage_error"),
                         (tmp_path / ".." / "x", "usage_error")]:
        with pytest.raises(logs.RuntimeTargetError) as error:
            logs.resolve_log_target(folder, pid=123)
        assert error.value.error_code == code
    link = tmp_path / "link"
    link.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.resolve_log_target(link, pid=123)
    assert error.value.error_code == "endpoint_invalid"


@pytest.mark.parametrize("count", [True, 0, -1, 10001, "20", None])
def test_invalid_count(tmp_path, count):
    """True integers within the approved bounds are mandatory."""
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.read_log_tail(target(tmp_path), count)
    assert error.value.error_code == "usage_error"


def test_invalid_bounds(tmp_path):
    """Explicit helper bounds are validated before open."""
    with pytest.raises(logs.RuntimeTargetError):
        logs.read_log_tail(target(tmp_path), budget=0)


@pytest.mark.parametrize("kind", ["symlink", "directory", "missing"])
def test_replaced_endpoint(tmp_path, kind):
    """Selected paths are rechecked and never read through final symlinks."""
    item = target(tmp_path)
    replacement = tmp_path / "replacement"
    replacement.write_bytes(b"secret")
    path = Path(item.stdout_path)
    print(f"Delete fixture: {path}")
    path.unlink()
    if kind == "symlink":
        path.symlink_to(replacement)
    if kind == "directory":
        path.mkdir()
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.read_log_tail(item)
    assert error.value.error_code == ("endpoint_missing" if kind == "missing" else "endpoint_invalid")


@pytest.mark.parametrize("exc,code", [(PermissionError(), "permission_denied"),
    (FileNotFoundError(), "endpoint_missing"), (OSError(errno.ELOOP, "private"), "endpoint_invalid"),
    (OSError(errno.EIO, "private"), "log_read_failed")])
def test_open_errors(tmp_path, monkeypatch, exc, code):
    """Safe classifications retain cause privately and map exact exits."""
    item = target(tmp_path)
    monkeypatch.setattr(logs, "os", SimpleNamespace(**{name: getattr(os, name) for name in
        ("O_RDONLY", "O_BINARY", "O_NOFOLLOW", "O_NONBLOCK") if hasattr(os, name)},
        open=Mock(side_effect=exc)))
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.read_log_tail(item)
    assert error.value.error_code == code and error.value.__cause__ is exc
    assert error.value.exit_code == (5 if code == "log_read_failed" else 4)


@pytest.mark.parametrize("mode", ["short", "error", "interrupt", "shrink", "identity", "special", "append"])
def test_opened_resource(tmp_path, monkeypatch, mode):
    """Close file ownership on all outcomes; ignore appended bytes."""
    item = target(tmp_path, b"one\ntwo\n")
    real_fdopen, real_fstat = os.fdopen, os.fstat
    streams = []
    calls = 0

    def fdopen(fd, flags):
        """Capture owned handles and optionally inject a scan failure."""
        stream = real_fdopen(fd, flags)
        streams.append(stream)
        if mode == "short":
            stream.read = lambda size: b""
        if mode in ("error", "interrupt"):
            stream.read = Mock(side_effect=OSError("private") if mode == "error" else KeyboardInterrupt())
        return stream

    def fstat(fd):
        """Inject snapshot shrinkage or identity/type invalidation."""
        nonlocal calls
        calls += 1
        result = real_fstat(fd)
        if mode == "append" and calls == 1:
            with open(item.stdout_path, "ab") as writer:
                writer.write(b"new\n")
        fields = {name: getattr(result, name) for name in ("st_size", "st_ino", "st_dev", "st_mode")}
        if mode == "shrink" and calls == 2:
            fields["st_size"] = 0
        if mode == "identity":
            fields["st_ino"] += 1
        if mode == "special":
            fields["st_mode"] = 0
        return SimpleNamespace(**fields)

    monkeypatch.setattr(logs, "os", SimpleNamespace(**{name: getattr(os, name) for name in
        ("O_RDONLY", "O_BINARY", "O_NOFOLLOW", "O_NONBLOCK") if hasattr(os, name)},
        open=os.open, fdopen=fdopen, fstat=fstat, close=os.close))
    if mode == "append":
        assert logs.read_log_tail(item).lines == ("one", "two")
    else:
        with pytest.raises(KeyboardInterrupt if mode == "interrupt" else logs.RuntimeTargetError) as error:
            logs.read_log_tail(item)
        if mode != "interrupt":
            assert error.value.error_code == ("log_read_failed" if mode == "error" else
                                       "endpoint_invalid" if mode == "special" else "log_changed")
    assert streams and all(stream.closed for stream in streams)


def test_fdopen_failure_closes_descriptor(tmp_path, monkeypatch):
    """A failed file-object handoff closes the still-owned descriptor."""
    item = target(tmp_path)
    close = Mock(wraps=os.close)
    monkeypatch.setattr(logs, "os", SimpleNamespace(O_RDONLY=os.O_RDONLY,
        open=os.open, close=close, fdopen=Mock(side_effect=OSError("private"))))
    with pytest.raises(logs.RuntimeLogError):
        logs.read_log_tail(item)
    close.assert_called_once()


def test_discovery_skips_invalid_and_nonregular(tmp_path):
    """Malformed names, zero PIDs, directories and symlinks are not candidates."""
    target(tmp_path)
    (tmp_path / "s.x.session.stdout").touch()
    (tmp_path / "s.0.session.stdout").touch()
    (tmp_path / "s.456.session.stdout").mkdir()
    (tmp_path / "s.789.session.stdout").symlink_to(tmp_path / "session.x.123.session.stdout")
    assert logs.resolve_log_target(tmp_path, pid=123).pid == 123


def test_discovery_denied(tmp_path, monkeypatch):
    """Directory access denial preserves its exact permission classification."""
    monkeypatch.setattr(Path, "iterdir", Mock(side_effect=PermissionError()))
    with pytest.raises(logs.RuntimeTargetError) as error:
        logs.resolve_log_target(tmp_path, pid=123)
    assert error.value.error_code == "permission_denied"


def test_portable_without_open_flags(tmp_path, monkeypatch):
    """Regular file reads do not require POSIX flags or process probing."""
    item = target(tmp_path, b"portable\n")
    monkeypatch.setattr(logs, "os", SimpleNamespace(O_RDONLY=os.O_RDONLY,
        open=os.open, close=os.close, fdopen=os.fdopen, fstat=os.fstat))
    assert logs.read_log_tail(item).lines == ("portable",)


def test_rotation_retains_descriptor(tmp_path, monkeypatch):
    """Rotation after capture reads the original descriptor without reopening."""
    item = target(tmp_path, b"old\n")
    original = os.fstat
    calls = 0

    def rotate(fd):
        """Replace the pathname once after obtaining the snapshot metadata."""
        nonlocal calls
        result = original(fd)
        calls += 1
        if calls == 1:
            item.stdout_path.rename(tmp_path / "rotated")
            item.stdout_path.write_bytes(b"new\n")
        return result

    monkeypatch.setattr(logs, "os", SimpleNamespace(O_RDONLY=os.O_RDONLY,
        open=os.open, close=os.close, fdopen=os.fdopen, fstat=rotate))
    assert logs.read_log_tail(item).lines == ("old",)
