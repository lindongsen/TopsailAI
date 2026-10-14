"""Prepared Script membership boundaries. Author: DawsonLin."""

import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from topsailai.hooks.configured_preparation import _Operation, _PreparationBudget, _PreparationRejected
from topsailai.hooks.configured_script_sources import discover_prepared_script_entries
from topsailai.hooks.hook_script_discovery import ExecutablePlatformPolicy

POLICY = ExecutablePlatformPolicy("posix", (str(Path(sys.executable).resolve()),))


def script(path):
    """Write one admitted executable without invoking it."""
    path.write_text(f"#!{POLICY.allowed_interpreters[0]}\nprint('ok')\n")
    path.chmod(0o700)
    return path


def discover(path, *, scans=100, candidates=100, size=100000):
    """Inject bounded counters and one absolute preparation deadline."""
    budget = _PreparationBudget(max_scanned_entries=scans,
        max_candidates=candidates, max_artifact_bytes=size)
    return discover_prepared_script_entries(path, POLICY,
        operation=_Operation(10000, None), budget=budget)


@pytest.mark.parametrize("names", [(), ("z",), ("z.py", "A", "a", "2")])
def test_complete_ordered_inventory(tmp_path, names):
    """Publish every direct member in exact final-name order."""
    for name in names:
        script(tmp_path / name)
    (tmp_path / "nested").mkdir()
    script(tmp_path / "nested" / "hidden")
    result = discover(tmp_path)
    assert result.accepted
    assert [entry.final_registered_name for entry in result.entries] == sorted(names)


def test_single_file(tmp_path):
    """Keep existing absolute file targets compatible."""
    path = script(tmp_path / "audit")
    assert discover(path).entries[0].source_path == path


@pytest.mark.parametrize("kind", ["link", "directory_link", "fifo", "bad_header", "nonexecuting", "hardlink"])
def test_invalid_member_rejects_whole_inventory(tmp_path, kind):
    """A bad member never publishes its valid sibling as a partial plan."""
    good = script(tmp_path / "good")
    bad = tmp_path / "bad"
    if kind == "link":
        bad.symlink_to(good)
    elif kind == "directory_link":
        bad.symlink_to(tmp_path, target_is_directory=True)
    elif kind == "fifo":
        os.mkfifo(bad)
    elif kind == "hardlink":
        os.link(good, bad)
    else:
        script(bad)
        if kind == "bad_header":
            bad.write_text("not executable content")
        else:
            bad.chmod(0o600)
    result = discover(tmp_path)
    assert not result.accepted and not result.entries


@pytest.mark.parametrize("limit", ["scans", "candidates", "size"])
def test_capacity_before_capture(tmp_path, limit):
    """Reject under the shared counters without acquiring artifacts."""
    script(tmp_path / "one")
    with pytest.raises(_PreparationRejected, match="capacity_exceeded"):
        discover(tmp_path, **{limit: 0})


@pytest.mark.parametrize("kind", ["missing", "relative", "ancestry", "target_link", "special"])
def test_invalid_target(tmp_path, kind):
    """Missing targets and link ancestry are not successful empty plans."""
    path = tmp_path / "missing"
    if kind == "relative":
        path = Path("relative")
    elif kind == "ancestry":
        folder = tmp_path / "folder"
        folder.mkdir()
        path = tmp_path / "alias"
        path.symlink_to(folder, target_is_directory=True)
        path = path / "script"
        script(folder / "script")
    elif kind == "target_link":
        path.symlink_to(script(tmp_path / "actual"))
    elif kind == "special":
        os.mkfifo(path)
    assert not discover(path).accepted


def test_deadline_and_cancellation(tmp_path):
    """Observe stop facts before any filesystem boundary."""
    import threading
    event = threading.Event()
    event.set()
    budget = _PreparationBudget(max_scanned_entries=2, max_candidates=2, max_artifact_bytes=100)
    for operation, token in [(_Operation(0, None), "prepare_timeout"),
                             (_Operation(1000, event), "cancelled")]:
        with pytest.raises(_PreparationRejected, match=token):
            discover_prepared_script_entries(tmp_path, POLICY, operation=operation, budget=budget)


def test_invalid_policy(tmp_path):
    """Reject malformed static admission policies without discovery."""
    assert not discover_prepared_script_entries(tmp_path, None,
        operation=_Operation(1000, None), budget=None).accepted


@pytest.mark.parametrize("kind", ["escape", "replacement", "late_success", "late_error"])
def test_observation_boundaries(tmp_path, monkeypatch, kind):
    """Reject escaped/replaced members and observe stops after admission or error."""
    from topsailai.hooks import configured_script_sources as sources
    from topsailai.hooks.hook_script_discovery import HookScriptDiscoveryResult, HookScriptEntry
    path = script(tmp_path / "audit")
    budget = _PreparationBudget(max_scanned_entries=10, max_candidates=10, max_artifact_bytes=10000)
    class Operation:
        """Expose a one-way stop fact without altering the process clock."""
        stopped = False
        def checkpoint(self):
            """Reject all subsequent work after the injected low-level boundary."""
            if self.stopped:
                raise _PreparationRejected("prepare_timeout")
    operation = Operation()
    if kind == "escape":
        original = sources._canonical
        def canonical(candidate, checkpoint):
            """Return an out-of-root member without touching another tree."""
            return tmp_path.parent / "outside" if candidate == path else original(candidate, checkpoint)
        monkeypatch.setattr(sources, "_canonical", canonical)
    else:
        def admit(*args, checkpoint=None):
            """Simulate identity replacement or a stop arriving during admission."""
            if kind == "replacement":
                return HookScriptDiscoveryResult(True, (HookScriptEntry(tmp_path / "other", "audit"),))
            operation.stopped = True
            if kind == "late_error":
                checkpoint()
                raise OSError("injected admission read failure")
            return HookScriptDiscoveryResult(True, (HookScriptEntry(path, "audit"),))
        monkeypatch.setattr(sources, "discover_hook_script_entries", admit)
    if kind.startswith("late"):
        with pytest.raises(_PreparationRejected, match="prepare_timeout"):
            sources.discover_prepared_script_entries(tmp_path, POLICY, operation=operation, budget=budget)
    else:
        result = sources.discover_prepared_script_entries(tmp_path, POLICY, operation=operation, budget=budget)
        assert not result.accepted and not result.entries


class StopOperation:
    """Expose an exact primary exception after a low-level observation."""

    def __init__(self, error):
        """Keep stop identity independently of exception type."""
        self.error, self.stopped = error, False

    def checkpoint(self):
        """Propagate the original stop rather than reclassifying it."""
        if self.stopped:
            raise self.error


@pytest.mark.parametrize("token", ["prepare_timeout", "cancelled"])
@pytest.mark.parametrize("boundary", ["open", "read", "lstat", "stat", "resolve"])
@pytest.mark.parametrize("io_error", [False, True])
def test_low_level_stop(tmp_path, monkeypatch, token, boundary, io_error):
    """A late low-level result or failure cannot authorize the next I/O."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    primary = _PreparationRejected(token)
    operation = StopOperation(primary)
    calls = []

    class Stream:
        """Record owned closure and the first non-ELF prefix read."""
        def read(self, limit):
            """Stop at the actual read, before shebang fallback can open."""
            calls.append(("read", limit))
            if boundary == "read":
                operation.stopped = True
                if io_error:
                    raise OSError("late read")
            return b"#!xx"

        def close(self):
            """Record exactly one required close."""
            calls.append("close")

    def opener(self, *args, **kwargs):
        """Stop immediately after acquisition or a failed acquisition."""
        calls.append("open")
        if boundary == "open":
            operation.stopped = True
            if io_error:
                raise OSError("late open")
        return Stream()

    monkeypatch.setattr(Path, "open", opener)
    if boundary in ("lstat", "stat", "resolve"):
        original = getattr(Path, boundary)
        def metadata(self, *args, **kwargs):
            """Inject stopping at a metadata operation, not its composite wrapper."""
            calls.append(boundary)
            operation.stopped = True
            if io_error:
                raise OSError("late metadata")
            return original(self, *args, **kwargs)
        monkeypatch.setattr(Path, boundary, metadata)
    with pytest.raises(_PreparationRejected) as caught:
        shared.discover_hook_script_entries(path, POLICY, checkpoint=operation.checkpoint)
    assert caught.value is primary
    assert calls.count("open") == int(boundary in ("open", "read"))
    assert sum(isinstance(call, tuple) for call in calls) == int(boundary == "read")
    assert calls.count("close") == int(boundary == "read" or (boundary == "open" and not io_error))


@pytest.mark.parametrize("primary", [OSError("stop"), ValueError("stop"), RuntimeError("stop"), KeyboardInterrupt()])
@pytest.mark.parametrize("close_error", [False, True])
def test_primary_and_close(tmp_path, monkeypatch, primary, close_error):
    """Checkpoint types and host interrupts survive exactly one failed close."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    operation = StopOperation(primary)
    closes = []
    class Stream:
        """Raise from read or checkpoint while cleanup remains owned."""
        def read(self, limit):
            """Observe host interruption at the real read boundary."""
            operation.stopped = True
            if isinstance(primary, KeyboardInterrupt):
                raise primary
            return b"text"
        def close(self):
            """Fail once without replacing or retrying the primary."""
            closes.append(True)
            if close_error:
                raise OSError("close uncertain")
    monkeypatch.setattr(Path, "open", lambda *args, **kwargs: Stream())
    with pytest.raises(type(primary)) as caught:
        shared.discover_hook_script_entries(path, POLICY, checkpoint=operation.checkpoint)
    assert caught.value is primary and closes == [True]


@pytest.mark.parametrize("late_error", [False, True])
def test_prepared_iterator_stop(tmp_path, monkeypatch, late_error):
    """Close the owned scanner without inspecting a late entry."""
    from topsailai.hooks import configured_script_sources as sources
    operation = StopOperation(_PreparationRejected("cancelled"))
    closes = []
    class Scanner:
        """Expose a late advance and required cleanup."""
        def __next__(self):
            """Stop before candidate metadata can start."""
            operation.stopped = True
            if late_error:
                raise OSError("late scan")
            return type("Entry", (), {"name": "never-inspected"})()
        def close(self):
            """Release owned iteration once."""
            closes.append(True)
    monkeypatch.setattr(sources, "os", SimpleNamespace(scandir=lambda *args: Scanner()))
    budget = _PreparationBudget(max_scanned_entries=10, max_candidates=10, max_artifact_bytes=1000)
    with pytest.raises(_PreparationRejected) as caught:
        sources.discover_prepared_script_entries(tmp_path, POLICY, operation=operation, budget=budget)
    assert caught.value is operation.error and closes == [True]


@pytest.mark.parametrize("directory", [False, True])
@pytest.mark.parametrize("kind", ["shebang", "elf", "pe", "bad", "permission"])
def test_default_format_compatibility(tmp_path, directory, kind):
    """Optional checkpoint preserves inert POSIX/Windows formats and skip policy."""
    from topsailai.hooks import hook_script_discovery as shared
    from tests.unit.test_topsailai_hooks.hook_script_discovery_helpers import write_native
    policy = POLICY
    if kind in ("elf", "pe"):
        path = write_native(tmp_path, "audit.exe", file_format=kind)
        if kind == "pe":
            policy = ExecutablePlatformPolicy("windows", native_suffixes=(".EXE",))
    else:
        path = script(tmp_path / "audit")
        if kind == "bad":
            path.write_bytes(b"not a header")
        elif kind == "permission":
            path.chmod(0o600)
    target = tmp_path if directory else path
    expected = shared.discover_hook_script_entries(target, policy)
    assert shared.discover_hook_script_entries(target, policy, checkpoint=None) == expected
    assert shared.discover_hook_script_entries(target, policy, checkpoint=lambda: None) == expected
    assert len(expected.entries) == int(kind not in ("bad", "permission"))
    assert expected.accepted == (directory or kind not in ("bad", "permission"))


@pytest.mark.parametrize("boundary", ["create", "advance", "resolve", "lstat"])
@pytest.mark.parametrize("late_error", [False, True])
def test_shared_directory_stops(tmp_path, monkeypatch, boundary, late_error):
    """Direct-directory discovery observes creation, iteration and member I/O."""
    from topsailai.hooks import hook_script_discovery as shared
    child = script(tmp_path / "audit")
    operation = StopOperation(_PreparationRejected("prepare_timeout"))
    closes, reads = [], []
    class Iterator:
        """Own a single controlled directory iteration."""
        def __next__(self):
            """Expose one child or a late failed advance."""
            if boundary == "advance":
                operation.stopped = True
                if late_error:
                    raise OSError("late advance")
            return SimpleNamespace(path=str(child))
        def close(self):
            """Record terminal iterator cleanup."""
            closes.append(True)
    def iterdir(self):
        """Stop at iterator creation before any advance."""
        if boundary == "create":
            operation.stopped = True
            if late_error:
                raise OSError("late create")
        return Iterator()
    def resolver(path):
        """Stop at the injected canonicalization boundary."""
        operation.stopped = True
        if late_error:
            raise OSError("late resolve")
        return path
    original = Path.lstat
    def lstat(path, *args, **kwargs):
        """Stop only on member metadata, leaving root admission reachable."""
        if path == child and boundary == "lstat":
            operation.stopped = True
            if late_error:
                raise OSError("late metadata")
        return original(path, *args, **kwargs)
    monkeypatch.setattr(shared, "_scandir", iterdir)
    monkeypatch.setattr(Path, "lstat", lstat)
    monkeypatch.setattr(Path, "open", lambda *args: reads.append(True))
    kwargs = {"resolve_path": resolver} if boundary == "resolve" else {}
    with pytest.raises(_PreparationRejected) as caught:
        shared.discover_hook_script_entries(tmp_path, POLICY, checkpoint=operation.checkpoint, **kwargs)
    assert caught.value is operation.error and reads == []
    assert len(closes) == int(not (boundary == "create" and late_error))


@pytest.mark.parametrize("boundary", ["open", "read", "close", "stat"])
def test_nonlate_errors_keep_tokens(tmp_path, monkeypatch, boundary):
    """Ordinary I/O errors retain rejection tokens without swallowing stop facts."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    class Stream:
        """Supply normal read and cleanup error variants."""
        def read(self, limit):
            """Fail only the selected bounded read."""
            if boundary == "read":
                raise OSError("read")
            return b"\x7fELF"
        def close(self):
            """Fail only the selected single close."""
            if boundary == "close":
                raise OSError("close")
    def opener(*args, **kwargs):
        """Fail before any owned stream exists."""
        if boundary == "open":
            raise OSError("open")
        return Stream()
    monkeypatch.setattr(Path, "open", opener)
    if boundary == "stat":
        original_stat = Path.stat
        def permission_stat(candidate, *args, **kwargs):
            """Leave lstat intact while rejecting the permission observation."""
            if kwargs.get("follow_symlinks") is False:
                return original_stat(candidate, *args, **kwargs)
            raise OSError("stat")
        monkeypatch.setattr(Path, "stat", permission_stat)
    for checkpoint in (None, lambda: None):
        result = shared.discover_hook_script_entries(path, POLICY, checkpoint=checkpoint)
        assert result.errors == ("configured hook_script file is not executable",)


@pytest.mark.parametrize("kind", ["lstat", "resolver", "relative", "escape", "iteration"])
def test_directory_nonlate_error_compatibility(tmp_path, monkeypatch, kind):
    """Generic directory skip/error rules remain independent of prepared policy."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    original = Path.lstat
    def lstat(candidate, *args, **kwargs):
        """Leave root metadata intact and fail only a member."""
        if candidate == path:
            raise OSError("member metadata")
        return original(candidate, *args, **kwargs)
    def resolver(candidate):
        """Expose the preexisting injected resolution cases."""
        if kind == "resolver":
            raise ValueError("invalid resolver")
        if kind == "relative":
            return Path("/unavailable/member").relative_to("/")
        return tmp_path.parent / "outside"
    if kind == "lstat":
        monkeypatch.setattr(Path, "lstat", lstat)
    if kind == "iteration":
        def iterator(candidate):
            """Fail during ordinary directory materialization."""
            raise OSError("iteration")
        monkeypatch.setattr(shared, "_scandir", iterator)
    kwargs = {"resolve_path": resolver} if kind in ("resolver", "relative", "escape") else {}
    for checkpoint in (None, lambda: None):
        result = shared.discover_hook_script_entries(tmp_path, POLICY, checkpoint=checkpoint, **kwargs)
        assert not result.entries
        assert result.accepted == (kind not in ("escape", "iteration"))


@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("boundary", ["read", "iterator"])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_close_interrupt_after_ordinary_error(tmp_path, monkeypatch, callback, boundary, interrupt_type):
    """New cleanup interruption must escape ordinary discovery error conversion."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    interrupt = interrupt_type("host close interruption")
    calls = []

    class Resource:
        """Fail business I/O once and interrupt its single owned close."""
        def read(self, limit):
            """Expose an ordinary prefix error before cleanup interruption."""
            calls.append("read")
            raise OSError("prefix failed")

        def __next__(self):
            """Expose an ordinary iterator error before cleanup interruption."""
            calls.append("advance")
            raise OSError("iteration failed")

        def close(self):
            """Raise the exact new host interruption without retry authority."""
            calls.append("close")
            raise interrupt

    def acquire(*args, **kwargs):
        """Record each resource acquisition to detect unsafe continuation."""
        calls.append("acquire")
        return Resource()

    target = path
    if boundary == "read":
        monkeypatch.setattr(Path, "open", acquire)
    else:
        target = tmp_path
        monkeypatch.setattr(shared, "_scandir", acquire)
    checkpoint = (lambda: None) if callback else None
    with pytest.raises(interrupt_type) as caught:
        shared.discover_hook_script_entries(target, POLICY, checkpoint=checkpoint)
    assert caught.value is interrupt
    assert calls == ["acquire", "read" if boundary == "read" else "advance", "close"]


@pytest.mark.parametrize("callback", [False, True])
@pytest.mark.parametrize("boundary", ["read", "iterator"])
@pytest.mark.parametrize("interrupt_type", [KeyboardInterrupt, SystemExit])
def test_primary_interrupt_before_ordinary_close_error(tmp_path, monkeypatch, callback, boundary, interrupt_type):
    """An ordinary cleanup error must retain the existing host interruption."""
    from topsailai.hooks import hook_script_discovery as shared
    path = script(tmp_path / "audit")
    primary = interrupt_type("host business interruption")
    calls = []

    class Resource:
        """Interrupt business I/O and fail one cleanup attempt ordinarily."""
        def read(self, limit):
            """Raise the original host interruption at prefix reading."""
            calls.append("read")
            raise primary

        def __next__(self):
            """Raise the original host interruption at directory advance."""
            calls.append("advance")
            raise primary

        def close(self):
            """Fail once without replacing or retrying the primary."""
            calls.append("close")
            raise OSError("close uncertain")

    def acquire(*args, **kwargs):
        """Record acquisition to exclude any subsequent business I/O."""
        calls.append("acquire")
        return Resource()

    target = path
    if boundary == "read":
        monkeypatch.setattr(Path, "open", acquire)
    else:
        target = tmp_path
        monkeypatch.setattr(shared, "_scandir", acquire)
    checkpoint = (lambda: None) if callback else None
    with pytest.raises(interrupt_type) as caught:
        shared.discover_hook_script_entries(target, POLICY, checkpoint=checkpoint)
    assert caught.value is primary
    assert calls == ["acquire", "read" if boundary == "read" else "advance", "close"]


@pytest.mark.parametrize("mode", ["omitted", "none", "callback"])
@pytest.mark.parametrize("invalid", ["none", "integer", OSError, RuntimeError, TypeError, ValueError])
def test_resolver_return_conversion_skips_only_invalid_member(tmp_path, mode, invalid):
    """Invalid resolver results skip a member, not its valid sibling."""
    from topsailai.hooks import hook_script_discovery as shared
    bad = script(tmp_path / "bad")
    good = script(tmp_path / "good")
    calls = []

    class InvalidPath:
        """Fail only the returned PathLike conversion, not the resolver call."""
        def __fspath__(self):
            """Raise one of the original narrowly handled conversion errors."""
            raise invalid("invalid returned path")

    def resolver(candidate):
        """Return normally for both members and preserve the good sibling."""
        calls.append(candidate.name)
        if candidate == bad:
            if invalid == "none":
                return None
            if invalid == "integer":
                return 123
            return InvalidPath()
        return candidate

    kwargs = {} if mode == "omitted" else {"checkpoint": None if mode == "none" else lambda: None}
    result = shared.discover_hook_script_entries(tmp_path, POLICY, resolve_path=resolver, **kwargs)
    assert result.accepted and result.errors == ()
    assert [(entry.basename, entry.source_path) for entry in result.entries] == [("good", good)]
    assert sorted(calls) == ["bad", "good"]


@pytest.mark.parametrize("error_type", [OSError, RuntimeError, TypeError, ValueError, KeyboardInterrupt, SystemExit])
def test_resolver_post_checkpoint_exception_is_not_conversion_error(tmp_path, monkeypatch, error_type):
    """A stop after normal resolution propagates exactly, without later I/O."""
    from topsailai.hooks import hook_script_discovery as shared
    child = script(tmp_path / "audit")
    primary = error_type("checkpoint stop")
    operation = StopOperation(primary)
    calls = []

    class Iterator:
        """Own one member and expose any unsafe subsequent advance."""
        def __next__(self):
            """Record each advance before returning the candidate."""
            calls.append("advance")
            return SimpleNamespace(path=str(child))

        def close(self):
            """Close exactly once on the propagated checkpoint exception."""
            calls.append("close")

    def resolver(candidate):
        """Arm stopping only after returning the normal resolver result."""
        calls.append("resolve")
        operation.stopped = True
        return candidate

    monkeypatch.setattr(shared, "_scandir", lambda *args: Iterator())
    monkeypatch.setattr(shared, "_has_execute_permission", lambda *args: calls.append("permission"))
    with pytest.raises(error_type) as caught:
        shared.discover_hook_script_entries(tmp_path, POLICY, resolve_path=resolver, checkpoint=operation.checkpoint)
    assert caught.value is primary
    assert calls == ["advance", "resolve", "close"]


@pytest.mark.parametrize("token", ["prepare_timeout", "cancelled"])
@pytest.mark.parametrize("boundary", ["create", "advance", "end"])
@pytest.mark.parametrize("io_error", [False, True])
def test_real_scanner_stop_boundaries(tmp_path, monkeypatch, token, boundary, io_error):
    """Observe stops at real scanner acquisition/advancement, not pathlib maps."""
    from topsailai.hooks import hook_script_discovery as shared
    script(tmp_path / "audit")
    operation = StopOperation(_PreparationRejected(token))
    calls = []
    real_scandir = os.scandir

    class Scanner:
        """Own the real scanner while recording its exact low-level advances."""
        def __init__(self, scanner):
            """Retain exclusive close responsibility for the underlying scanner."""
            self.scanner = scanner

        def __next__(self):
            """Arm a stop after a real advance, including an exhausted scanner."""
            calls.append("advance")
            if boundary == "end":
                operation.stopped = True
                if io_error:
                    raise OSError("late scan end")
                return next(self.scanner)
            entry = next(self.scanner)
            operation.stopped = True
            if io_error:
                raise OSError("late scan advance")
            return entry

        def close(self):
            """Close exactly the owned real scanner without retry."""
            calls.append("close")
            self.scanner.close()

    def acquire(path):
        """Expose acquisition outcomes without transferring unowned resources."""
        calls.append("acquire")
        if boundary == "create" and io_error:
            operation.stopped = True
            raise OSError("late scan create")
        scanner = Scanner(real_scandir(path))
        if boundary == "create":
            operation.stopped = True
        return scanner

    if boundary == "end":
        # Use an empty real directory so next reports actual exhaustion.
        target = tmp_path / "empty"
        target.mkdir()
    else:
        target = tmp_path
    monkeypatch.setattr(shared, "_scandir", acquire)
    monkeypatch.setattr(shared, "_has_execute_permission", lambda *args: calls.append("permission"))
    with pytest.raises(_PreparationRejected) as caught:
        shared.discover_hook_script_entries(target, POLICY, checkpoint=operation.checkpoint)
    assert caught.value is operation.error
    assert calls == (["acquire"] if boundary == "create" and io_error else
                     ["acquire", "close"] if boundary == "create" else
                     ["acquire", "advance", "close"])


@pytest.mark.parametrize("boundary", ["stream", "directory"])
@pytest.mark.parametrize("mode", ["prepare_timeout", "cancelled", "omitted", "none", "callback", OSError, RuntimeError, ValueError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_error", [False, True])
def test_final_close_observes_new_stop(tmp_path, monkeypatch, boundary, mode, close_error):
    """Observe stops first arising during final cleanup without retrying close."""
    from topsailai.hooks import hook_script_discovery as shared
    path = tmp_path / "audit"
    path.write_bytes(b"\x7fELF")
    path.chmod(0o700)
    error = (_PreparationRejected(mode) if mode in ("prepare_timeout", "cancelled") else
             mode("checkpoint close stop") if isinstance(mode, type) else None)
    operation = StopOperation(error)
    calls = []
    original_open, original_scan = Path.open, shared._scandir

    class Resource:
        """Own the actual stream or scanner and arm stop only after its close."""
        def __init__(self, resource):
            """Retain exact ownership for one cleanup attempt."""
            self.resource = resource
        def read(self, limit):
            """Use the actual final ELF admission read."""
            calls.append("read")
            return self.resource.read(limit)
        def __next__(self):
            """Use real exhaustion of an empty directory."""
            calls.append("advance")
            return next(self.resource)
        def close(self):
            """Close once before exposing the new stop or ordinary close error."""
            calls.append("close")
            self.resource.close()
            operation.stopped = error is not None
            if close_error:
                raise OSError("final close failed")
    def acquire(target, *args, **kwargs):
        """Record actual acquisitions to exclude any subsequent business I/O."""
        calls.append("acquire")
        resource = (original_open(target, *args, **kwargs) if boundary == "stream" else
                    original_scan(target))
        return Resource(resource)

    target = path
    if boundary == "stream":
        monkeypatch.setattr(Path, "open", acquire)
    else:
        target = tmp_path / "empty"
        target.mkdir()
        monkeypatch.setattr(shared, "_scandir", acquire)
    kwargs = {} if mode == "omitted" else {"checkpoint": None if mode == "none" else operation.checkpoint}
    if error is not None:
        with pytest.raises(type(error)) as caught:
            shared.discover_hook_script_entries(target, POLICY, **kwargs)
        assert caught.value is error
    else:
        result = shared.discover_hook_script_entries(target, POLICY, **kwargs)
        assert result.accepted is (not close_error)
    assert calls == (["acquire", "read", "close"] * (2 if close_error and boundary == "stream" and error is None else 1)
                     if boundary == "stream" else ["acquire", "advance", "close"])
