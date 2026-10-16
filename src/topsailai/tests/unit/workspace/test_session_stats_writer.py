"""Unit B storage evidence; fixture files are owned below the configured basetemp."""

import json
import logging
import os
from pathlib import Path
from unittest.mock import Mock

import pytest

from topsailai.workspace import session_stats_writer as storage
from topsailai.workspace.session_stats_retention import (
    FileIdentity, ProcessState, StatsRetention, observe_process,
)


@pytest.fixture
def events():
    """Provide an independent acknowledged diagnostic sink, not a shared logger."""
    return []


def sink(events):
    """Return a recording sink with an explicit successful acknowledgement."""
    def emit(category, name):
        """Keep only bounded safe categories and fixture names."""
        events.append((category, name))
        return True
    return emit


def writer(tmp_path, events, **kwargs):
    """Create storage with isolated primitives and no thread or Agent context."""
    return storage.StatsWriter("example", directory=tmp_path, diagnostic=sink(events), **kwargs)


def record(size=40):
    """Construct strict JSON fixtures by encoded byte length including the LF."""
    prefix = b'{"schema_version":1,"x":"'
    return prefix + b"x" * (size - len(prefix) - 3) + b'"}\n'


def test_path_config(tmp_path):
    """Validate naming, fallback, absolute roots and independent config defaults."""
    assert storage.stats_path("", directory=tmp_path, pid=12).name == "topsailai.12.session.stats.jsonl"
    assert storage.stats_path("a", pid=12).parent == Path(storage.FOLDER_WORKSPACE_TASK)
    for value in ("../bad", "a" * 65, 3, 0, False, None):
        with pytest.raises(ValueError):
            storage.stats_path(value, directory=tmp_path)
    for value in (0, True, -1, 2**64):
        with pytest.raises(ValueError):
            storage.stats_path("a", directory=tmp_path, pid=value)
    with pytest.raises(ValueError):
        storage.stats_path("a", directory="relative")
    config = storage.StorageConfig(3, -1, float("nan"), True, "false")
    assert config == storage.StorageConfig()
    assert storage.StorageConfig(retention_days=0, max_groups=0).retention_days == 0
    assert storage.StorageConfig(retention_days=10**1000).retention_days == 7


@pytest.mark.parametrize("line", [record(4097), b"", b"\n", b"{}", b"{}\n{}\n", b"{}\r\n", {}, bytearray(b"{}\n"), memoryview(b"{}\n")])
def test_reject_before_any_mutation(tmp_path, events, line):
    """Even an existing full active file is untouched by malformed input."""
    target = tmp_path / "not-created"
    owner = storage.StatsWriter("a", directory=target, diagnostic=sink(events))
    assert owner.append(line) == storage.WriteResult(False, "invalid_record")
    assert not target.exists()
    owner = writer(tmp_path, events)
    owner.path.write_bytes(record(4096))
    before = {path.name: path.read_bytes() for path in tmp_path.iterdir()}
    assert not owner.append(line).ok
    assert before == {path.name: path.read_bytes() for path in tmp_path.iterdir()}


def test_exact_cap_and_multibyte(tmp_path, events):
    """Payload bytes, not Python character count, define the accepted boundary."""
    owner = writer(tmp_path, events)
    assert owner.append(record(4096)).ok
    prefix = b'{"schema_version":1,"x":"'
    line = prefix + "界".encode() * 1356 + b"x" * (4096 - len(prefix) - 4068 - 3) + b'"}\n'
    assert len(line) == 4096
    assert owner.append(line).ok
    assert not owner.append(line[:-1] + b"x\n").ok
    assert len(list(storage.read_records(owner.path, diagnostic=sink(events)))) == 2


def test_schema_is_not_revalidated_on_append(tmp_path, events):
    """Storage framing intentionally does not duplicate C's semantic validator."""
    owner = writer(tmp_path, events)
    assert owner.append(b"not JSON\n").ok
    assert list(storage.read_records(owner.path, diagnostic=sink(events))) == []


@pytest.mark.parametrize("tail", [b"partial", b"\xe7\x95", b"\npartial"])
def test_corrupt_tail_isolated(tmp_path, events, tail):
    """Never concatenate a new observation to a damaged prior line."""
    owner = writer(tmp_path, events)
    old = record() + tail
    owner.path.write_bytes(old)
    assert owner.append(record()).ok
    assert owner.backup(1).read_bytes() == old
    assert owner.path.read_bytes() == record()


def test_corrupt_zero_backup_and_long_tail_refuse(tmp_path, events):
    """No .1 or truncation is permitted when damaged active cannot be retained."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_backups=0))
    owner.path.write_bytes(b"partial")
    assert not owner.append(record()).ok
    assert owner.path.read_bytes() == b"partial"
    assert not owner.backup(1).exists()
    owner.path.write_bytes(b"x" * 4097)
    assert not owner.append(record()).ok
    assert not owner.backup(1).exists()


def test_rotation_and_preexisting_oversize(tmp_path, events):
    """Normal rotation bounds generated files but does not shrink legacy oversized data."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096))
    for _ in range(6):
        assert owner.append(record(4096)).ok
    assert len(list(tmp_path.iterdir())) == 4
    assert all(path.stat().st_size == 4096 for path in tmp_path.iterdir())
    owner.path.write_bytes(record(8192))
    assert owner.append(record()).ok
    assert owner.backup(1).stat().st_size == 8192
    assert any(category == "deleted" for category, _ in events)


def test_zero_backups_and_deletion_diagnostic_failure(tmp_path, events):
    """Healthy zero-backup active is retired only with independent deletion logging."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096, max_backups=0))
    assert owner.append(record(4096)).ok
    owner.diagnostic = lambda *_: False
    assert not owner.append(record()).ok
    assert owner.path.stat().st_size == 4096
    owner.diagnostic = sink(events)
    assert owner.append(record()).ok
    assert not owner.backup(1).exists()
    assert owner.path.read_bytes() == record()


@pytest.mark.parametrize("boundary", [1, 2, 3])
def test_every_rename_failure_recovers_from_actual_names(tmp_path, events, monkeypatch, boundary):
    """A failed shift cannot grow active; re-enumeration handles intermediate gaps."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096))
    for index in (1, 2, 3):
        owner.backup(index).write_bytes(record())
    owner.path.write_bytes(record(4096))
    rename = Path.rename
    calls = []
    def fail_selected(path, target):
        """Fail one exact rename boundary without mutating unrelated operations."""
        calls.append((path, target))
        if len(calls) == boundary:
            raise OSError("injected rename")
        return rename(path, target)
    monkeypatch.setattr(Path, "rename", fail_selected)
    assert not owner.append(record()).ok
    assert owner.path.stat().st_size == 4096
    monkeypatch.setattr(Path, "rename", rename)
    assert owner.append(record()).ok
    assert owner.path.read_bytes() == record()
    assert owner.backup(1).read_bytes() == record(4096)
    assert not owner.backup(4).exists()


def test_gaps_and_existing_target_retirement(tmp_path, events):
    """Backup-only gaps continue deterministically; occupied moves never silently overwrite."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096))
    owner.backup(2).write_bytes(record())
    owner.path.write_bytes(record(4096))
    assert owner.append(record()).ok
    assert owner.backup(3).exists() and not owner.backup(2).exists()
    owner._move(owner.backup(3), owner.backup(1))
    assert any(category == "delete_attempt" for category, _ in events)
    owner._move(owner.backup(3), owner.backup(2))
    owner._delete(owner.backup(3))


def test_reader_skips_invalid_complete_lines_and_ignores_tail(tmp_path, events):
    """Resume after oversized/invalid complete lines and keep only supported objects."""
    owner = writer(tmp_path, events)
    owner.path.write_bytes(b"\xff\nnot-json\n[]\n{}\n" +
                          b'{"schema_version":true}\n{"schema_version":2}\n' +
                          b'{"schema_version":1,"n":NaN}\n' +
                          b'{"schema_version":1,"n":1e999}\n' +
                          record(9000) + record() + b"incomplete")
    assert list(storage.read_records(owner.path, diagnostic=sink(events))) == [json.loads(record())]
    assert storage._finite_tree([1, {"x": [1.5, None]}])
    assert any(category == "overlong_line" for category, _ in events)


class FakeFile:
    """Own a real stream while injecting exact write/close failure boundaries."""

    def __init__(self, stream, mode):
        """Track all closure paths and injected operation counts."""
        self.stream = stream
        self.mode = mode
        self.calls = 0
        self.closed = False

    def __enter__(self):
        """Retain this wrapper as the managed owner."""
        return self

    def __exit__(self, *args):
        """Close the real handle even when exit itself reports failure."""
        self.stream.close()
        self.closed = True
        if self.mode == "close":
            raise OSError("close failure")

    def write(self, data):
        """Inject positive, zero or interrupted writes without changing read paths."""
        self.calls += 1
        if self.mode == "zero":
            return 0
        if self.mode == "partial_failure" and self.calls > 1:
            raise OSError("partial failure")
        return self.stream.write(data[:3] if self.mode in ("short", "partial_failure") else data)

    def fileno(self):
        """Delegate descriptor lookup for fsync verification."""
        return self.stream.fileno()


@pytest.mark.parametrize("mode", ["short", "zero", "partial_failure", "close", "open", "sync"])
def test_io_failures_close_and_never_claim_success(tmp_path, events, monkeypatch, mode):
    """Positive short writes complete, all ambiguous failures return explicit failure."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(fsync=True))
    original_open = Path.open
    wrappers = []
    def opened(path, *args, **kwargs):
        """Instrument only append streams, not unrelated libraries or read inspection."""
        if (args[0] if args else kwargs.get("mode", "r")) != "ab":
            return original_open(path, *args, **kwargs)
        if mode == "open":
            raise OSError("open failure")
        wrapped = FakeFile(original_open(path, *args, **kwargs), mode)
        wrappers.append(wrapped)
        return wrapped
    def synced(fd):
        """Represent success or failure of the optional worker-only fsync."""
        if mode == "sync":
            raise OSError("sync failure")
    monkeypatch.setattr(Path, "open", opened)
    monkeypatch.setattr(storage, "os", type("OS", (), {"getpid": staticmethod(os.getpid), "fstat": staticmethod(os.fstat), "fsync": staticmethod(synced)}))
    result = owner.append(record())
    assert result.ok is (mode == "short")
    assert all(wrapped.closed for wrapped in wrappers)
    if mode == "zero":
        assert wrappers[0].calls == 1
    if mode == "partial_failure":
        assert owner.path.read_bytes() == record()[:3]


def test_fork_guard_symlink_and_independent_diagnostics(tmp_path, events, monkeypatch):
    """Storage never calls application/root logging, even when diagnostics fail."""
    monkeypatch.setattr(logging.Logger, "_log", Mock(side_effect=AssertionError("shared logger")))
    owner = writer(tmp_path, events)
    owner.pid += 1
    assert owner.append(record()).reason == "foreign_process"
    owner.pid = os.getpid()
    target = tmp_path / "unrelated.meta"
    target.write_bytes(b"keep")
    owner.path.symlink_to(target)
    def fail(*args):
        """Diagnostic failures must not invoke any fallback logger."""
        raise OSError("diagnostic failed")
    owner.diagnostic = fail
    assert not owner.append(record()).ok
    assert target.read_bytes() == b"keep"


def group(tmp_path, pid, *, session="session", backup="", mtime=1):
    """Create one exact foreign group member with deterministic age."""
    path = tmp_path / f"{session}.{pid}.session.stats{backup}.jsonl"
    path.write_bytes(record())
    os.utime(path, (mtime, mtime))
    return path


def fixture_delete(events):
    """Provide fixture-exclusive deletion; not a production cross-process adapter."""
    def delete(path, identity):
        """Fixture has no external mutators; assert the injected custody token."""
        assert FileIdentity.read(path) == identity
        path.unlink()
        events.append(("fixture_deleted", path.name))
        return True
    return delete


@pytest.mark.parametrize("state", list(ProcessState))
@pytest.mark.parametrize("dimension", ["age", "count"])
def test_retention_states(tmp_path, events, state, dimension):
    """Both age and count require absence; neither age nor target grants authority."""
    first = group(tmp_path, 100000001, backup=".2")
    group(tmp_path, os.getpid(), session="protected", mtime=2)
    extra = tmp_path / "other.jsonl"
    extra.write_bytes(b"unrelated")
    config = storage.StorageConfig(retention_days=1 if dimension == "age" else 0,
                                   max_groups=1 if dimension == "count" else 0)
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events), config=config,
                             observer=lambda _: state, safe_delete=fixture_delete(events))
    assert cleaner.sweep(now=900000) == (1 if state is ProcessState.CONFIRMED_ABSENT else 0)
    assert first.exists() is (state is not ProcessState.CONFIRMED_ABSENT)
    assert extra.read_bytes() == b"unrelated"


def test_default_no_safe_delete_and_disabled_cleanup(tmp_path, events):
    """Proven absence without a safe adapter still never authorizes plain unlink."""
    path = group(tmp_path, 100000001)
    assert observe_process(os.getpid()) is ProcessState.ALIVE
    assert observe_process(100000001) is ProcessState.UNKNOWN
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events), observer=lambda _: ProcessState.CONFIRMED_ABSENT)
    assert cleaner.sweep(now=900000) == 0 and path.exists()
    cleaner.config = storage.StorageConfig(retention_days=0, max_groups=0)
    assert cleaner.sweep(now=900000) == 0
    with pytest.raises(ValueError):
        StatsRetention(Path("relative"), diagnostic=sink(events))


@pytest.mark.parametrize("failure", ["observer", "invalid_observer", "changed", "missing", "delete", "deny", "diagnostic", "reuse"])
def test_cleanup_uncertainty_and_races(tmp_path, events, failure):
    """Observer failures, identity replacement and reused PID cannot become authority."""
    path = group(tmp_path, 100000001)
    observations = []
    def observer(pid):
        """Inject observation and post-scan replacement at precise boundaries."""
        observations.append(pid)
        if failure == "observer":
            raise PermissionError("not observable")
        if failure == "invalid_observer":
            return "absent"
        if failure == "changed" and len(observations) == 1:
            path.write_bytes(b"replacement")
        if failure == "reuse" and len(observations) > 1:
            return ProcessState.ALIVE
        return ProcessState.CONFIRMED_ABSENT
    def deletion(path, identity):
        """Inject adapter dependency failures without removing the target."""
        if failure == "missing":
            raise FileNotFoundError("adapter coordination file missing")
        if failure == "delete":
            raise OSError("adapter failure")
        return False
    diagnostic = (lambda *_: False) if failure == "diagnostic" else sink(events)
    cleaner = StatsRetention(tmp_path, diagnostic=diagnostic, observer=observer, safe_delete=deletion)
    assert cleaner.sweep(now=900000) == 0
    assert path.exists()


def test_scan_missing_nonregular_and_failure(tmp_path, events, monkeypatch):
    """Exact patterns protect unrelated data; missing/symlink entries never enter custody."""
    group(tmp_path, 100000001)
    directory = tmp_path / "folder.100000002.session.stats.jsonl"
    directory.mkdir()
    (tmp_path / "invalid.99999999999999999999.session.stats.jsonl").write_bytes(record())
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events))
    assert cleaner.sweep(now=900000) == 0
    def failed(_):
        """Simulate a directory removed concurrently with maintenance."""
        raise FileNotFoundError("gone")
    monkeypatch.setattr(Path, "iterdir", failed)
    assert cleaner.sweep(now=900000) == 0


def test_owned_delete_and_rename_failures(tmp_path, events, monkeypatch):
    """Failed retirement blocks growth; unexpected missing target-parent errors propagate."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096, max_backups=0))
    owner.path.write_bytes(record(4096))
    unlink = Path.unlink
    def denied(path, *args, **kwargs):
        """Deny only the owned active deletion."""
        if path == owner.path:
            raise PermissionError("injected delete")
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, "unlink", denied)
    assert not owner.append(record()).ok
    assert owner.path.stat().st_size == 4096
    assert any(category == "delete_failed" for category, _ in events)
    def missing_target(path, target):
        """Represent missing target ancestry rather than a settled missing source."""
        raise FileNotFoundError("target gone")
    monkeypatch.setattr(Path, "rename", missing_target)
    with pytest.raises(FileNotFoundError):
        owner._move(owner.path, owner.backup(1))


def test_age_uses_each_member_and_count_oldest_group(tmp_path, events):
    """Age can remove one stale backup without discarding a newer group member."""
    old = group(tmp_path, 100000001, backup=".1", mtime=1)
    new = group(tmp_path, 100000001, mtime=899999)
    older_group = group(tmp_path, 100000002, mtime=800000)
    protected = group(tmp_path, os.getpid(), mtime=899999)
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events),
                             config=storage.StorageConfig(max_groups=2),
                             observer=lambda _: ProcessState.CONFIRMED_ABSENT,
                             safe_delete=fixture_delete(events))
    assert cleaner.sweep(now=900000) == 2
    assert not old.exists() and not older_group.exists()
    assert new.exists() and protected.exists()


def test_concurrent_cleaners_fixture_custody(tmp_path, events):
    """Two fixture-scoped cleaners tolerate disappearance under serialized custody."""
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier, Lock
    path = group(tmp_path, 100000001)
    gate = Barrier(2)
    custody = Lock()
    def observer(pid):
        """Allow both scanners to finish before either deletes."""
        return ProcessState.CONFIRMED_ABSENT
    def deletion(target, identity):
        """Fixture lock covers identity check AND deletion, unlike stat-then-unlink."""
        gate.wait()
        with custody:
            try:
                if FileIdentity.read(target) != identity:
                    return False
                target.unlink()
                events.append(("fixture_deleted", target.name))
                return True
            except FileNotFoundError:
                return True
    def sweep():
        """Run an independent scanner using the same fixture-only custody service."""
        cleaner = StatsRetention(tmp_path, diagnostic=sink(events), observer=observer, safe_delete=deletion)
        return cleaner.sweep(now=900000)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: sweep(), range(2)))
    assert results == [1, 1] and not path.exists()
    assert sum(category == "fixture_deleted" for category, _ in events) == 1


def test_live_rotation_scan_never_authorizes_delete(tmp_path, events):
    """Scanning while this process shifts names never grants foreign unlink authority."""
    owner = writer(tmp_path, events, config=storage.StorageConfig(max_size_bytes=4096))
    attempts = []
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events),
                             config=storage.StorageConfig(retention_days=1, max_groups=1),
                             observer=lambda _: ProcessState.CONFIRMED_ABSENT,
                             safe_delete=lambda *args: attempts.append(args))
    owner.path.write_bytes(record(4096))
    os.utime(owner.path, (1, 1))
    owner._move(owner.path, owner.backup(1))
    assert cleaner.sweep(now=900000) == 0
    assert owner.append(record()).ok
    assert not attempts and owner.backup(1).exists()


@pytest.mark.parametrize("dimension", ["age", "count", "combined"])
def test_adapter_missing_dependency_retains_group(tmp_path, events, dimension):
    """Unresolved members still count when age cleanup precedes count enforcement."""
    failed = group(tmp_path, 100000001, mtime=1)
    other = group(tmp_path, 100000002, mtime=899999)
    calls = []
    delete = fixture_delete(events)
    def deletion(path, identity):
        """Fail only the oldest group's coordination dependency, not its target."""
        calls.append(path)
        if path == failed:
            raise FileNotFoundError("adapter coordination file missing")
        return delete(path, identity)
    config = storage.StorageConfig(
        retention_days=0 if dimension == "count" else 1,
        max_groups=0 if dimension == "age" else 1)
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events), config=config,
                             observer=lambda _: ProcessState.CONFIRMED_ABSENT,
                             safe_delete=deletion)
    assert cleaner.sweep(now=900000) == (0 if dimension == "age" else 1)
    assert failed.exists()
    assert other.exists() is (dimension == "age")
    assert calls.count(failed) == (2 if dimension == "combined" else 1)
    assert ("delete_failed", failed.name) in events


@pytest.mark.parametrize("dimension", ["age", "count"])
def test_missing_target_identity_is_idempotent(tmp_path, events, dimension):
    """Another cleaner's actual removal can settle a previously scanned member."""
    target = group(tmp_path, 100000001)
    group(tmp_path, os.getpid(), session="protected", mtime=2)
    def observer(pid):
        """Remove the fixture after scan but before target identity revalidation."""
        target.unlink()
        events.append(("fixture_deleted", target.name))
        return ProcessState.CONFIRMED_ABSENT
    deletion = Mock(side_effect=AssertionError("already absent"))
    config = storage.StorageConfig(
        retention_days=1 if dimension == "age" else 0,
        max_groups=1 if dimension == "count" else 0)
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events), config=config,
                             observer=observer, safe_delete=deletion)
    assert cleaner.sweep(now=900000) == 1
    assert not target.exists()
    deletion.assert_not_called()


def test_target_identity_failure_retains_member(tmp_path, events, monkeypatch):
    """A failed target identity probe cannot settle a scanned member."""
    target = group(tmp_path, 100000001)
    def denied(path):
        """Reject only the post-scan identity lookup."""
        raise PermissionError("identity unavailable")
    def observer(pid):
        """Install the probe failure only after discovery has captured identity."""
        monkeypatch.setattr(FileIdentity, "read", denied)
        return ProcessState.CONFIRMED_ABSENT
    deletion = Mock(side_effect=AssertionError("unverified identity"))
    cleaner = StatsRetention(tmp_path, diagnostic=sink(events), observer=observer,
                             safe_delete=deletion)
    assert cleaner.sweep(now=900000) == 0
    assert target.exists()
    assert ("delete_failed", target.name) in events
    deletion.assert_not_called()
