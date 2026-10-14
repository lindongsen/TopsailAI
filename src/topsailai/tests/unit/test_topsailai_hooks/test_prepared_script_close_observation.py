"""Exceptional discovery cleanup stop boundaries. Author: DawsonLin."""

from pathlib import Path

import pytest

from topsailai.hooks import hook_script_discovery as shared
from topsailai.hooks.configured_preparation import _PreparationRejected


@pytest.mark.parametrize("boundary", ["stream", "directory"])
@pytest.mark.parametrize("close_error", [False, True])
@pytest.mark.parametrize("mode", ["prepare_timeout", "cancelled", "omitted", "none",
                                 "callback", OSError, RuntimeError, ValueError,
                                 KeyboardInterrupt, SystemExit])
def test_io_failure_close_observes_first_stop(tmp_path, monkeypatch, boundary, close_error, mode):
    """Observe a stop first arising in close after an ordinary read/advance error."""
    error = (_PreparationRejected(mode) if mode in ("prepare_timeout", "cancelled") else
             mode("checkpoint stop") if isinstance(mode, type) else None)
    stopped = False
    calls = []
    original_open, original_scan = Path.open, shared._scandir

    def checkpoint():
        """Raise the exact injected stop only after owned cleanup has completed."""
        if stopped and error is not None:
            raise error

    class Resource:
        """Own one actual stream/scanner and expose the exceptional cleanup boundary."""

        def __init__(self, resource):
            """Retain exclusive resource ownership until one close attempt."""
            self.resource = resource

        def read(self, limit):
            """Perform the actual bounded read before reporting ordinary failure."""
            calls.append("read")
            self.resource.read(limit)
            raise OSError("read failed")

        def __next__(self):
            """Advance the actual scanner once before reporting ordinary failure."""
            calls.append("advance")
            next(self.resource)
            raise OSError("advance failed")

        def close(self):
            """Close once, then arm stop even if ordinary cleanup failure follows."""
            nonlocal stopped
            calls.append("close")
            self.resource.close()
            stopped = True
            if close_error:
                raise OSError("close failed")

    def acquire(target, *args, **kwargs):
        """Record each acquisition without replacing the shared os singleton."""
        calls.append("acquire")
        resource = (original_open(target, *args, **kwargs) if boundary == "stream" else
                    original_scan(target))
        return Resource(resource)

    path = tmp_path / "audit.exe"
    path.write_bytes(b"MZ")
    path.chmod(0o700)
    policy = shared.ExecutablePlatformPolicy("windows", native_suffixes=(".exe",))
    target = path
    if boundary == "stream":
        monkeypatch.setattr(Path, "open", acquire)
    else:
        target = tmp_path
        monkeypatch.setattr(shared, "_scandir", acquire)
    kwargs = {} if mode == "omitted" else {"checkpoint": None if mode == "none" else checkpoint}
    if error is not None:
        with pytest.raises(type(error)) as caught:
            shared.discover_hook_script_entries(target, policy, **kwargs)
        assert caught.value is error
    else:
        result = shared.discover_hook_script_entries(target, policy, **kwargs)
        assert not result.accepted and not result.entries
        assert result.errors == (("configured hook_script file is not executable",) if
                                 boundary == "stream" else ("hook_script target is invalid",))
    assert stopped
    assert calls == ["acquire", "read" if boundary == "stream" else "advance", "close"]


@pytest.mark.parametrize("primary_type", [OSError, RuntimeError, ValueError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("close_type", [None, OSError, KeyboardInterrupt, SystemExit])
def test_active_primary_cleanup_priority(primary_type, close_type):
    """Do not recheck over active checkpoint errors; retain new host interruption."""
    primary = primary_type("active checkpoint")
    close_error = close_type("close error") if close_type is not None else None
    calls = []

    class Resource:
        """Expose exactly one close without any filesystem observation wrapper."""

        def close(self):
            """Record cleanup and raise the specified close outcome."""
            calls.append("close")
            if close_error is not None:
                raise close_error

    def checkpoint():
        """Fail if cleanup incorrectly overwrites a previously observed primary."""
        calls.append("checkpoint")
        raise AssertionError("unexpected checkpoint")

    expected = close_error if close_type in (KeyboardInterrupt, SystemExit) else primary
    with pytest.raises(type(expected)) as caught:
        with shared._owned(Resource(), checkpoint):
            raise primary
    assert caught.value is expected
    assert calls == ["close"]


@pytest.mark.parametrize("boundary", ["advance_error", "exhaustion", "invalid_child"])
@pytest.mark.parametrize("close_type", [None, OSError, KeyboardInterrupt, SystemExit])
@pytest.mark.parametrize("mode", ["prepare_timeout", "cancelled", "callback", "active"])
def test_prepared_scanner_close_checkpoint(tmp_path, monkeypatch, boundary, close_type, mode):
    """Wire prepared scanner cleanup to the same stop callback on every exit path."""
    from types import SimpleNamespace

    from topsailai.hooks import configured_script_sources as prepared
    from topsailai.hooks.configured_preparation import _PreparationBudget

    error = (_PreparationRejected(mode) if mode in ("prepare_timeout", "cancelled") else
             OSError("active checkpoint") if mode == "active" else None)
    close_error = close_type("close failure") if close_type is not None else None
    stopped, active = False, False
    calls = []
    original_scan, original_status, original_members = prepared.os.scandir, prepared._status, prepared._members

    def checkpoint():
        """Keep one callback, arming its stop only at the designated boundary."""
        if error is not None and (stopped or active):
            raise error

    class Scanner:
        """Own a real directory scanner without changing the global os module."""

        def __init__(self, target):
            """Acquire one scanner and retain exclusive close responsibility."""
            calls.append("acquire")
            self.resource = original_scan(target)

        def __next__(self):
            """Perform one actual advance before injecting the selected outcome."""
            nonlocal active
            calls.append("advance")
            child = next(self.resource, None)
            active = mode == "active"
            if boundary == "advance_error":
                raise OSError("advance failed")
            if child is None:
                raise StopIteration
            return child

        def close(self):
            """Always close exactly once before arming the newly arising stop."""
            nonlocal stopped
            calls.append("close")
            self.resource.close()
            stopped = True
            if close_error is not None:
                raise close_error

    def status(path, supplied):
        """Record metadata observations and verify unchanged callback identity."""
        assert supplied is checkpoint
        calls.append("status")
        return original_status(path, supplied)

    def members(*args, **kwargs):
        """Detect any admission after stopping while retaining compatible results."""
        calls.append("members")
        assert error is None and close_error is None and boundary == "exhaustion"
        return original_members(*args, **kwargs)

    if boundary == "advance_error":
        (tmp_path / "audit").write_bytes(b"inert")
    elif boundary == "invalid_child":
        (tmp_path / "alias").symlink_to(tmp_path / "missing")
    monkeypatch.setattr(prepared, "os", SimpleNamespace(scandir=Scanner))
    monkeypatch.setattr(prepared, "_status", status)
    monkeypatch.setattr(prepared, "_members", members)
    policy = shared.ExecutablePlatformPolicy("posix")
    expected = close_error if close_type in (KeyboardInterrupt, SystemExit) else error
    if expected is not None:
        with pytest.raises(type(expected)) as caught:
            prepared.discover_prepared_script_entries(
                tmp_path, policy, operation=SimpleNamespace(checkpoint=checkpoint),
                budget=_PreparationBudget(max_scanned_entries=100, max_candidates=100, max_artifact_bytes=100000))
        assert caught.value is expected
    else:
        result = prepared.discover_prepared_script_entries(
            tmp_path, policy, operation=SimpleNamespace(checkpoint=checkpoint),
            budget=_PreparationBudget(max_scanned_entries=100, max_candidates=100, max_artifact_bytes=100000))
        assert result.accepted == (boundary == "exhaustion" and close_error is None)
        assert not result.entries
        if not result.accepted:
            assert result.errors == ("trust_rejected",)
    assert stopped
    assert calls.count("acquire") == calls.count("advance") == calls.count("close") == 1
    after_close = calls[calls.index("close") + 1:]
    assert after_close == (["members"] if boundary == "exhaustion" and
                           mode == "callback" and close_error is None else [])
