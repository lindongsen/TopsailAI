"""Unit coverage for workspace driver log and metadata readers."""

import json

import pytest

from cli_topsailai.session_driver import metadata_path
from cli_topsailai.session_driver_logs import read_driver_log, bind_driver_row
from cli_topsailai.session_driver_meta import read_driver_meta


def row(session="team", pid=123):
    """Return an eligible session stdout row."""
    return {"session_id": session, "pid": pid, "session_pid": pid,
            "filename": f"{session}.{pid}.session.stdout"}


def setup_files(tmp_path):
    """Create driver-owned records under the test temporary root."""
    meta = metadata_path(tmp_path, "team")
    meta.parent.mkdir(parents=True)
    meta.with_suffix(".log").write_text("one\ntwo\nthree\n", encoding="utf-8")
    meta.write_text(json.dumps({"version": 1, "session_id": "team", "pid": 456,
                                "run_id": "a" * 32, "status": "running"}), encoding="utf-8")
    return meta


def test_log_reads_last_lines(tmp_path):
    """Read the active log without selecting rotated siblings."""
    setup_files(tmp_path)
    result = read_driver_log(tmp_path, "team", lines=2)
    assert result.lines == ("two", "three")


def test_meta_preserves_valid_json(tmp_path):
    """Validate driver identity while preserving the original JSON text."""
    setup_files(tmp_path)
    path, text, value = read_driver_meta(tmp_path, "team")
    assert path.name == "team.meta"
    assert value["pid"] == 456
    assert text.endswith("}")


@pytest.mark.parametrize("suffix", [".log", ".meta"])
def test_missing_record_is_explicit(tmp_path, suffix):
    """Missing active records do not fall back to other files."""
    metadata_path(tmp_path, "team").parent.mkdir(parents=True)
    reader = read_driver_log if suffix == ".log" else read_driver_meta
    with pytest.raises(ValueError, match="missing"):
        reader(tmp_path, "team")


def test_row_binding_rejects_changed_identity(tmp_path):
    """A refreshed list cannot silently reinterpret the selected row."""
    with pytest.raises(ValueError, match="changed"):
        bind_driver_row([row()], 1, tmp_path, lambda: [row("other")])


def test_log_uses_default_twenty_line_tail(tmp_path):
    """The reader returns the bounded default tail in chronological order."""
    meta = metadata_path(tmp_path, "team")
    meta.parent.mkdir(parents=True)
    meta.with_suffix(".log").write_text("".join(f"line-{i}\n" for i in range(25)), encoding="utf-8")
    result = read_driver_log(tmp_path, "team")
    assert result.lines == tuple(f"line-{i}" for i in range(5, 25))


def test_log_rejects_intermediate_symlink(tmp_path):
    """The secure reader rejects a symlinked driver-record directory."""
    target = tmp_path / "outside"
    target.mkdir()
    root = tmp_path / "workspace" / "task"
    root.mkdir(parents=True)
    (root / "session_agent_driver").symlink_to(target, target_is_directory=True)
    with pytest.raises(ValueError, match="log_unsafe_path"):
        read_driver_log(tmp_path, "team")


def test_log_closes_exact_leaf_and_directories_when_stream_adoption_fails(tmp_path, monkeypatch):
    """A failed fd-to-stream handoff closes each acquisition owner exactly once."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver as driver
    import cli_topsailai.session_driver_logs as readers
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    acquisitions = []
    live = {}

    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        token = object()
        acquisitions.append((token, descriptor))
        live[descriptor] = token
        return descriptor

    def tracked_close(descriptor):
        token = live.pop(descriptor)
        assert any(item == (token, descriptor) for item in acquisitions)
        return real_os.close(descriptor)

    fake_os.open = tracked_open
    fake_os.close = tracked_close
    fake_os.fdopen = lambda *args: (_ for _ in ()).throw(OSError("fdopen"))
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(readers, "os", fake_os)
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(OSError, match="fdopen"):
        readers._open_regular(metadata_path(tmp_path, "team").with_suffix(".log"))
    assert acquisitions
    assert not live
    for _, descriptor in acquisitions:
        with pytest.raises(OSError):
            real_os.fstat(descriptor)


def test_log_scan_budget_is_reported_at_real_boundary(tmp_path, monkeypatch):
    """The real scanner reports its byte budget boundary."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_logs as readers
    monkeypatch.setattr(readers, "SCAN_BUDGET", 8)
    log = metadata_path(tmp_path, "team").with_suffix(".log")
    log.write_bytes(b"0123456789abcdef\n")
    result = readers.read_driver_log(tmp_path, "team", lines=20)
    assert result.scan_limited is True
    assert result.bytes_read == 8


@pytest.mark.parametrize("payload", [b"", b"{", b"[]", b"{\"version\": 1}"])
def test_meta_rejects_invalid_bodies(tmp_path, payload):
    """Empty, malformed, and incomplete metadata never gets displayed."""
    meta = setup_files(tmp_path)
    meta.write_bytes(payload)
    with pytest.raises((ValueError, json.JSONDecodeError, UnicodeError)):
        read_driver_meta(tmp_path, "team")


def test_meta_rejects_oversized_body(tmp_path):
    """Metadata is bounded before validation."""
    meta = setup_files(tmp_path)
    meta.write_bytes(b"{" + b"a" * 65536 + b"}")
    with pytest.raises(ValueError, match="too_large"):
        read_driver_meta(tmp_path, "team")


def test_meta_rejects_excessive_depth(tmp_path):
    """Valid JSON beyond the configured nesting boundary is rejected specifically."""
    meta = setup_files(tmp_path)
    meta.write_text("[" * 65 + "0" + "]" * 65, encoding="utf-8")
    with pytest.raises(ValueError, match="metadata_too_deep"):
        read_driver_meta(tmp_path, "team")


def test_reader_does_not_mutate_records(tmp_path):
    """Read-only helpers leave record bytes and metadata timestamps unchanged."""
    meta = setup_files(tmp_path)
    log = meta.with_suffix(".log")
    before = (log.read_bytes(), log.stat().st_mtime_ns, meta.read_bytes(), meta.stat().st_mtime_ns)
    read_driver_log(tmp_path, "team")
    read_driver_meta(tmp_path, "team")
    after = (log.read_bytes(), log.stat().st_mtime_ns, meta.read_bytes(), meta.stat().st_mtime_ns)
    assert after == before


def test_log_leaf_descriptor_is_closed_without_shared_os_mutation(tmp_path, monkeypatch):
    """The exact adopted leaf descriptor is closed by the returned stream."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver_logs as readers
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    opened = []
    closed = []

    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_os.close(descriptor)

    fake_os.open = tracked_open
    fake_os.close = tracked_close
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(readers, "os", fake_os)
    stream = readers._open_regular(metadata_path(tmp_path, "team").with_suffix(".log"))
    leaf = stream.fileno()
    assert leaf in opened
    stream.close()
    assert stream.closed
    assert all(descriptor in closed for descriptor in opened if descriptor != leaf)
    with pytest.raises(OSError):
        real_os.fstat(leaf)

def test_print_log_reports_identity_and_limits(tmp_path, capsys):
    """Log presentation includes selection, path, and partial-output warnings."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_logs as readers
    monkey_result = readers.LogTail("/safe/team.log", ("last",), 20, 1, None, True, True, 8, 8)
    original = readers.read_driver_log
    readers.read_driver_log = lambda *args, **kwargs: monkey_result
    try:
        assert readers.print_driver_log(tmp_path, [row()], 1, lambda: [row()]) is True
    finally:
        readers.read_driver_log = original
    output = capsys.readouterr().out
    assert "session=team" in output
    assert "truncated" in output
    assert "scan budget" in output


def test_print_log_missing_reports_cleanup(tmp_path, capsys):
    """Missing logs explain cleanup without exposing content."""
    metadata_path(tmp_path, "team").parent.mkdir(parents=True)
    import cli_topsailai.session_driver_logs as readers
    assert readers.print_driver_log(tmp_path, [row()], 1, lambda: [row()]) is False
    output = capsys.readouterr().out
    assert "may have been cleaned up" in output
    assert str(metadata_path(tmp_path, "team").with_suffix(".log")) in output


def test_print_meta_reports_identity_and_driver_pid(tmp_path, capsys):
    """Metadata presentation distinguishes session and driver identities."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_meta as readers
    assert readers.print_driver_meta(tmp_path, [row()], 1, lambda: [row()]) is True
    output = capsys.readouterr().out
    assert "latest-run" in output
    assert "driver PID" in output
    assert '"pid": 456' in output


def test_print_meta_missing_reports_cleanup(tmp_path, capsys):
    """Missing metadata explains cleanup without printing a substitute."""
    metadata_path(tmp_path, "team").parent.mkdir(parents=True)
    import cli_topsailai.session_driver_meta as readers
    assert readers.print_driver_meta(tmp_path, [row()], 1, lambda: [row()]) is False
    output = capsys.readouterr().out
    assert "may have been cleaned up" in output
    assert str(metadata_path(tmp_path, "team")) in output


def test_meta_rejects_invalid_utf8(tmp_path):
    """Invalid metadata encoding is rejected before JSON output."""
    meta = setup_files(tmp_path)
    meta.write_bytes(b"\xff")
    with pytest.raises(UnicodeDecodeError):
        read_driver_meta(tmp_path, "team")


def test_log_rejects_unsupported_safe_open(tmp_path, monkeypatch):
    """The log reader fails closed when no-follow support is unavailable."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_logs as readers
    fake = type("SafeOpenUnavailable", (), {"open": readers.os.open, "supports_dir_fd": readers.os.supports_dir_fd,
        "O_DIRECTORY": readers.os.O_DIRECTORY, "O_NONBLOCK": readers.os.O_NONBLOCK})()
    monkeypatch.setattr(readers, "os", fake)
    with pytest.raises(ValueError, match="safe_open_unsupported"):
        readers.read_driver_log(tmp_path, "team")


def test_log_rejects_nonregular_and_changed_file(tmp_path, monkeypatch):
    """Unsafe leaf types and identity replacement are rejected."""
    meta = setup_files(tmp_path)
    log = meta.with_suffix(".log")
    log.unlink()
    log.mkdir()
    with pytest.raises(ValueError, match="log_not_regular"):
        read_driver_log(tmp_path, "team")
    log.rmdir()
    log.write_text("one\n", encoding="utf-8")
    import os
    import types
    import cli_topsailai.session_driver as driver
    import cli_topsailai.session_driver_logs as readers
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    original_stat = real_os.stat

    def changed_stat(*args, **kwargs):
        value = original_stat(*args, **kwargs)
        values = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
        values["st_ino"] = value.st_ino + 1
        return type("Stat", (), values)()

    fake_os.stat = changed_stat
    monkeypatch.setattr(readers, "os", fake_os)
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(ValueError, match="log_changed"):
        read_driver_log(tmp_path, "team")

def test_meta_rejects_non_object_body(tmp_path):
    """Valid JSON with the wrong top-level shape is rejected."""
    meta = setup_files(tmp_path)
    meta.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_metadata_shape"):
        read_driver_meta(tmp_path, "team")


def test_meta_reports_unreadable_reader_error(tmp_path, monkeypatch):
    """Metadata reader translates ordinary I/O failure explicitly."""
    import cli_topsailai.session_driver_meta as readers
    monkeypatch.setattr(readers, "_read_metadata", lambda path: (_ for _ in ()).throw(OSError("denied")))
    with pytest.raises(ValueError, match="metadata_unreadable"):
        readers.read_driver_meta(tmp_path, "team")


def test_leaf_descriptor_and_directories_are_closed(tmp_path, monkeypatch):
    """The adopted leaf is closed by its stream and traversal dirs are closed."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver_logs as readers
    real_open, real_close = os.open, os.close
    opened = []
    closed = []
    fake_os = types.SimpleNamespace(**vars(os))
    def tracked_open(*args, **kwargs):
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    fake_os.open = tracked_open
    fake_os.supports_dir_fd = {tracked_open}
    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_close(descriptor)
    fake_os.close = tracked_close
    monkeypatch.setattr(readers, "os", fake_os)
    stream = readers._open_regular(metadata_path(tmp_path, "team").with_suffix(".log"))
    leaf = stream.fileno()
    assert leaf in opened
    stream.close()
    with pytest.raises(OSError):
        os.fstat(leaf)
    assert all(descriptor in closed for descriptor in opened if descriptor != leaf)



def test_bind_driver_row_rejects_invalid_index(tmp_path):
    """Invalid row positions fail before discovery or file access."""
    with pytest.raises(ValueError, match="invalid_row_index"):
        bind_driver_row([row()], 0, tmp_path, lambda: [row()])


def test_log_reports_directory_cleanup_failure(tmp_path, monkeypatch):
    """A one-shot directory-close failure closes the stream and is cleaned up."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver as driver
    import cli_topsailai.session_driver_logs as readers
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    opened = []
    closed = []
    directory_descriptors = set()
    target = {"fd": None, "failed": False}
    stream_holder = {}

    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        opened.append(descriptor)
        if args[1] & real_os.O_DIRECTORY:
            directory_descriptors.add(descriptor)
            target["fd"] = descriptor
        return descriptor

    def one_shot_close(descriptor):
        closed.append(descriptor)
        if descriptor == target["fd"] and not target["failed"]:
            target["failed"] = True
            raise OSError("directory close")
        return real_os.close(descriptor)

    def tracked_fdopen(descriptor, mode):
        stream = real_os.fdopen(descriptor, mode)
        stream_holder["stream"] = stream
        stream_holder["leaf"] = descriptor
        return stream

    fake_os.open = tracked_open
    fake_os.close = one_shot_close
    fake_os.fdopen = tracked_fdopen
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(readers, "os", fake_os)
    monkeypatch.setattr(driver, "os", fake_os)
    try:
        with pytest.raises(OSError, match="directory close"):
            readers._open_regular(metadata_path(tmp_path, "team").with_suffix(".log"))
        stream = stream_holder["stream"]
        leaf = stream_holder["leaf"]
        assert stream.closed
        with pytest.raises(OSError):
            real_os.fstat(leaf)
        assert target["failed"]
        assert target["fd"] in closed
        assert target["fd"] not in (leaf,)
        assert all(descriptor in closed for descriptor in directory_descriptors)
    finally:
        if target["fd"] is not None:
            try:
                real_os.close(target["fd"])
            except OSError:
                pass

def test_log_rejects_shrink_during_read(tmp_path, monkeypatch):
    """A log that shrinks between snapshots is rejected without partial output."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver_logs as readers
    real_fstat = os.fstat
    calls = {"count": 0}
    fake_os = types.SimpleNamespace(**vars(os))

    def shrinking_fstat(descriptor):
        calls["count"] += 1
        value = real_fstat(descriptor)
        if calls["count"] == 3:
            values = {name: getattr(value, name) for name in dir(value) if name.startswith("st_")}
            values["st_size"] = 0
            return type("Stat", (), values)()
        return value

    fake_os.fstat = shrinking_fstat
    monkeypatch.setattr(readers, "os", fake_os)
    with pytest.raises(ValueError, match="log_read_failed"):
        readers.read_driver_log(tmp_path, "team")


def test_log_translates_scan_failure(tmp_path, monkeypatch):
    """Scanner I/O failures are translated into a bounded reader error."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_logs as readers
    monkeypatch.setattr(readers, "_scan", lambda *args: (_ for _ in ()).throw(OSError("read")))
    with pytest.raises(ValueError, match="log_read_failed"):
        readers.read_driver_log(tmp_path, "team")
def test_log_translates_unreadable_path(tmp_path, monkeypatch):
    """Unexpected open failures are reported as unreadable records."""
    import errno
    import cli_topsailai.session_driver_logs as readers
    error = OSError(errno.EACCES, "denied")
    monkeypatch.setattr(readers, "_open_regular", lambda path: (_ for _ in ()).throw(error))
    with pytest.raises(ValueError, match="log_unreadable"):
        readers.read_driver_log(tmp_path, "team")


def test_print_log_reports_empty_snapshot(tmp_path, monkeypatch, capsys):
    """Empty snapshots produce an explicit diagnostic."""
    import cli_topsailai.session_driver_logs as readers
    empty = readers.LogTail("/safe/team.log", (), 20, 0, 0, False, False, 0, 0)
    monkeypatch.setattr(readers, "read_driver_log", lambda *args, **kwargs: empty)
    assert readers.print_driver_log(tmp_path, [row()], 1, lambda: [row()]) is True
    assert "Driver log is empty" in capsys.readouterr().out


def test_meta_translates_missing_file_error(tmp_path, monkeypatch):
    """Direct missing-file errors are classified as missing metadata."""
    import cli_topsailai.session_driver_meta as readers
    monkeypatch.setattr(readers, "_read_metadata", lambda path: (_ for _ in ()).throw(FileNotFoundError("gone")))
    with pytest.raises(ValueError, match="metadata_missing"):
        readers.read_driver_meta(tmp_path, "team")


def test_meta_checks_decoded_top_level_shape(tmp_path, monkeypatch):
    """The reader rejects a decoded JSON value that is not an object."""
    setup_files(tmp_path)
    import cli_topsailai.session_driver_meta as readers
    monkeypatch.setattr(readers, "_parse_metadata", lambda data, session: None)
    meta = metadata_path(tmp_path, "team")
    meta.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="invalid_metadata_shape"):
        readers.read_driver_meta(tmp_path, "team")



def test_log_preserves_close_failure_and_stream_cleanup_error(tmp_path, monkeypatch):
    """A directory-close failure preserves its identity and records stream cleanup."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver as driver
    import cli_topsailai.session_driver_logs as readers
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    target = {"directory": None}

    class FailingStream:
        """Expose a real leaf descriptor while making cleanup observable."""

        def __init__(self, descriptor):
            self.descriptor = descriptor
            self.closed = False

        def fileno(self):
            return self.descriptor

        def close(self):
            self.closed = True
            real_os.close(self.descriptor)
            raise RuntimeError("stream close")

    stream_holder = {}

    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        if args[1] & real_os.O_DIRECTORY:
            target["directory"] = descriptor
        return descriptor

    def failing_close(descriptor):
        if descriptor == target["directory"]:
            raise KeyboardInterrupt("directory close")
        return real_os.close(descriptor)

    def tracked_fdopen(descriptor, mode):
        stream_holder["stream"] = FailingStream(descriptor)
        return stream_holder["stream"]

    fake_os.open = tracked_open
    fake_os.close = failing_close
    fake_os.fdopen = tracked_fdopen
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(readers, "os", fake_os)
    monkeypatch.setattr(driver, "os", fake_os)
    try:
        with pytest.raises(KeyboardInterrupt, match="directory close") as raised:
            readers._open_regular(metadata_path(tmp_path, "team").with_suffix(".log"))
        assert raised.value.__notes__ == ["log stream cleanup failed: RuntimeError('stream close')"]
        stream = stream_holder["stream"]
        assert stream.closed is True
        with pytest.raises(OSError):
            real_os.fstat(stream.descriptor)
    finally:
        descriptor = stream_holder.get("stream")
        if descriptor is not None:
            try:
                real_os.close(descriptor.descriptor)
            except OSError:
                pass
        if target["directory"] is not None:
            try:
                real_os.close(target["directory"])
            except OSError:
                pass
def test_metadata_handoff_interrupt_closes_child_and_preserves_error(monkeypatch):
    """Directory handoff closes the child without replacing an interrupt."""
    import types
    import cli_topsailai.session_driver as driver
    closed = []
    def interrupting_close(descriptor):
        closed.append(descriptor)
        if descriptor == 101:
            raise KeyboardInterrupt("interrupt")
    fake_os = types.SimpleNamespace(close=interrupting_close)
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(KeyboardInterrupt, match="interrupt"):
        driver._handoff_directory(101, 102)
    assert closed == [101, 102]
def test_metadata_handoff_interrupt_through_reader_preserves_original(monkeypatch, tmp_path):
    """The metadata reader preserves a handoff interrupt and closes only the child."""
    import os
    import types
    import cli_topsailai.session_driver as driver
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    opened = []
    attempts = []
    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    original_error = KeyboardInterrupt("handoff interrupt")
    def interrupting_close(descriptor):
        attempts.append(descriptor)
        if descriptor == opened[0]:
            raise original_error
        return real_os.close(descriptor)
    fake_os.open = tracked_open
    fake_os.close = interrupting_close
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(driver, "os", fake_os)
    metadata = metadata_path(tmp_path, "team")
    metadata.parent.mkdir(parents=True)
    metadata.write_text("{}", encoding="utf-8")
    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            driver._read_metadata(metadata)
        assert raised.value is original_error
        assert attempts == opened[:2]
        assert None not in attempts
        with pytest.raises(OSError):
            real_os.fstat(opened[1])
        real_os.fstat(opened[0])
    finally:
        if opened:
            try:
                real_os.close(opened[0])
            except OSError:
                pass
def test_metadata_fstat_failure_closes_owned_stream(tmp_path, monkeypatch):
    """Metadata fstat failure still closes the adopted stream and directory."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver as driver
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    opened = []
    closed = []
    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_os.close(descriptor)
    def failing_fstat(descriptor):
        raise OSError("fstat")
    fake_os.open = tracked_open
    fake_os.close = tracked_close
    fake_os.fstat = failing_fstat
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(OSError, match="fstat"):
        driver._read_metadata(metadata_path(tmp_path, "team"))
    assert opened
    assert all(descriptor in closed for descriptor in opened)
    for descriptor in opened:
        with pytest.raises(OSError):
            real_os.fstat(descriptor)
def test_handoff_preserves_parent_failure_and_records_child_cleanup(monkeypatch):
    """Handoff keeps the parent failure while exposing child cleanup failure."""
    import types
    import cli_topsailai.session_driver as driver
    calls = []
    def failing_close(descriptor):
        calls.append(descriptor)
        if descriptor == 101:
            raise KeyboardInterrupt("parent interrupt")
        raise OSError("child close")
    fake_os = types.SimpleNamespace(close=failing_close)
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(KeyboardInterrupt, match="parent interrupt") as raised:
        driver._handoff_directory(101, 102)
    assert calls == [101, 102]
    assert "child directory cleanup failed" in raised.value.__notes__[0]
def test_metadata_fstat_failure_closes_leaf_and_directory_exactly(tmp_path, monkeypatch):
    """Metadata fstat failure closes the adopted leaf stream and traversal directory."""
    setup_files(tmp_path)
    import os
    import types
    import cli_topsailai.session_driver as driver
    real_os = os
    fake_os = types.SimpleNamespace(**vars(real_os))
    opened = []
    closed = []
    def tracked_open(*args, **kwargs):
        descriptor = real_os.open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor
    def tracked_close(descriptor):
        closed.append(descriptor)
        return real_os.close(descriptor)
    fake_os.open = tracked_open
    fake_os.close = tracked_close
    fake_os.fstat = lambda descriptor: (_ for _ in ()).throw(OSError("fstat"))
    fake_os.supports_dir_fd = {tracked_open}
    monkeypatch.setattr(driver, "os", fake_os)
    with pytest.raises(OSError, match="fstat"):
        driver._read_metadata(metadata_path(tmp_path, "team"))
    assert len(opened) >= 2
    assert set(opened).issubset(set(closed))
    for descriptor in opened:
        with pytest.raises(OSError):
            real_os.fstat(descriptor)
def test_record_dispatch_does_not_enter_lifecycle_paths(monkeypatch, tmp_path):
    """Reader actions invoke only their reader and never launch, stop, or observe drivers."""
    from unittest.mock import patch
    from cli_topsailai.core import _handle_driver_action
    import cli_topsailai.session_driver_logs as logs
    import cli_topsailai.session_driver_meta as meta
    rows = [row()]
    discover = lambda: [row()]
    for action, module, function in (("driver_log", logs, "print_driver_log"),
                                    ("driver_meta", meta, "print_driver_meta")):
        with patch.object(module, function, return_value=False) as reader:
            with patch("cli_topsailai.session_driver_launcher.launch_driver", side_effect=AssertionError("launch called")) as launch:
                with patch("cli_topsailai.session_driver_stopper.stop_driver", side_effect=AssertionError("stop called")) as stop:
                    with patch("cli_topsailai.core._enrich_driver_rows", side_effect=AssertionError("status observed")):
                        assert _handle_driver_action(action, 1, rows, tmp_path, None, {}, discover) is None
            reader.assert_called_once()
            launch.assert_not_called()
            stop.assert_not_called()
