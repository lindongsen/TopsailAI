"""Cleanup-debt retry regressions for independent channel settlement."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord


class _Process:
    """Expose real owned streams with a controllable process-inspection result."""

    pid = 424242

    def __init__(self, stream: Any, failure: BaseException | None) -> None:
        self.stdin = stream
        self.stdout = None
        self.stderr = None
        self._failure = failure

    def poll(self) -> None:
        """Return a live result or raise the configured inspection failure."""
        if self._failure is not None:
            raise self._failure
        return None


def _debt_with_real_channels(
    backend: IsolatedProcessBackend,
    tmp_path: Path,
    failure: BaseException | None,
) -> tuple[_Process, LaunchRecord, int, Any]:
    """Register one debt owning a real stream and raw pipe descriptor."""
    stream_read, stream_write = os.pipe()
    os.close(stream_read)
    stream = os.fdopen(stream_write, "wb", buffering=0)
    result_read, result_write = os.pipe()
    os.close(result_write)
    process = _Process(stream, failure)
    record = LaunchRecord("retry-channel-debt", process=process, result_fd=result_read)
    backend._record_process_debt(record.debt_id, process, "fixture", record)
    return process, record, result_read, stream


def _assert_retry_cleanup_state(
    backend: IsolatedProcessBackend,
    record: LaunchRecord,
    result_fd: int,
    stream: Any,
) -> None:
    """Assert real closure, retained debt, and released exact execution lease."""
    assert stream.closed
    with pytest.raises(OSError):
        os.fstat(result_fd)
    assert record.result_fd is None
    assert all(channel.state == "closed" for channel in record.cleanup.channels.values())
    assert backend._debt_processes[record.debt_id].state == "pending"
    assert record.cleanup.execution_owner is None
    assert record.cleanup.execution_depth == 0
    assert not record.cleanup.termination_confirmed


def test_retry_poll_error_still_closes_real_channels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A process-inspection error must not bypass independent channel closure."""
    signals: list[tuple[int, int]] = []
    backend = IsolatedProcessBackend(temp_root=str(tmp_path))
    process, record, result_fd, stream = _debt_with_real_channels(
        backend, tmp_path, OSError("fixture poll failure")
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    assert not backend.retry_cleanup(record.debt_id)

    _assert_retry_cleanup_state(backend, record, result_fd, stream)
    assert process.stdin is None
    assert signals == []


@pytest.mark.parametrize("failure", [RuntimeError("termination failed"), KeyboardInterrupt()])
def test_retry_termination_failure_still_closes_real_channels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    """Termination failure or interruption must close channels before its outcome."""
    signals: list[tuple[int, int]] = []

    class FailingBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise failure

    backend = FailingBackend(temp_root=str(tmp_path))
    process, record, result_fd, stream = _debt_with_real_channels(
        backend, tmp_path, None
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    if isinstance(failure, Exception):
        assert not backend.retry_cleanup(record.debt_id)
    else:
        with pytest.raises(KeyboardInterrupt):
            backend.retry_cleanup(record.debt_id)

    _assert_retry_cleanup_state(backend, record, result_fd, stream)
    assert process.stdin is None
    assert signals == []
