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

    with pytest.raises(OSError, match="fixture poll failure"):
        backend.retry_cleanup(record.debt_id)

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
        with pytest.raises(type(failure), match=str(failure)):
            backend.retry_cleanup(record.debt_id)
    else:
        with pytest.raises(KeyboardInterrupt):
            backend.retry_cleanup(record.debt_id)

    _assert_retry_cleanup_state(backend, record, result_fd, stream)
    assert process.stdin is None
    assert signals == []


def test_retry_later_channel_interrupt_outweighs_ordinary_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A later channel interruption must retain and outrank an ordinary close error."""
    signals: list[tuple[int, int]] = []

    class MixedFailureBackend(IsolatedProcessBackend):
        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise RuntimeError("fixture ordinary channel failure")
            if name == "stdout":
                raise KeyboardInterrupt("fixture channel interruption")

    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    result_read, result_write = os.pipe()
    os.close(stdin_read)
    os.close(stdout_write)
    os.close(result_write)
    stdin = os.fdopen(stdin_write, "wb", buffering=0)
    stdout = os.fdopen(stdout_read, "rb", buffering=0)
    backend = MixedFailureBackend(temp_root=str(tmp_path))
    process = _Process(stdin, None)
    process.stdout = stdout
    record = LaunchRecord("mixed-retry-debt", process=process, result_fd=result_read)
    record.cleanup.termination_confirmed = True
    backend._record_process_debt(record.debt_id, process, "fixture", record)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            backend.retry_cleanup(record.debt_id)
        assert isinstance(raised.value.__cause__, RuntimeError)
        assert str(raised.value.__cause__) == "fixture ordinary channel failure"
        assert stdin.closed and stdout.closed
        with pytest.raises(OSError):
            os.fstat(result_read)
        assert process.stdin is None and process.stdout is None
        assert record.result_fd is None
        assert all(
            channel.state == "closed" for channel in record.cleanup.channels.values()
        )
        assert backend.cleanup_debts() == ()
        assert record.cleanup.execution_owner is None
        assert record.cleanup.execution_depth == 0
        assert signals == []
    finally:
        stdin.close()
        stdout.close()
        for descriptor in (result_read,):
            try:
                os.close(descriptor)
            except OSError:
                pass


def test_initial_finalization_channel_interrupt_outweighs_process_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Initial cleanup must propagate channel interruption after process failure."""
    signals: list[tuple[int, int]] = []

    class MixedFailureBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise RuntimeError("fixture termination failure")

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise KeyboardInterrupt("fixture channel interruption")

    stream_read, stream_write = os.pipe()
    result_read, result_write = os.pipe()
    os.close(stream_read)
    os.close(result_write)
    stream = os.fdopen(stream_write, "wb", buffering=0)
    backend = MixedFailureBackend(temp_root=str(tmp_path))
    process = _Process(stream, None)
    record = LaunchRecord("mixed-finalization-debt", process=process, result_fd=result_read)
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            backend._finish_record(
                record,
                "worker_lost",
                {"stdout": bytearray(), "stderr": bytearray()},
                {"stdout": 0, "stderr": 0},
                "transport_error",
            )
        assert isinstance(raised.value.__cause__, RuntimeError)
        assert str(raised.value.__cause__) == "fixture termination failure"
        assert stream.closed
        with pytest.raises(OSError):
            os.fstat(result_read)
        assert process.stdin is None
        assert record.result_fd is None
        assert all(
            channel.state == "closed" for channel in record.cleanup.channels.values()
        )
        debts = backend.cleanup_debts()
        assert [debt.debt_id for debt in debts] == [record.debt_id]
        assert backend._debt_processes[record.debt_id].state == "pending"
        assert record.cleanup.execution_owner is None
        assert record.cleanup.execution_depth == 0
        assert not record.cleanup.termination_confirmed
        assert signals == []
    finally:
        stream.close()
        for descriptor in (result_read,):
            try:
                os.close(descriptor)
            except OSError:
                pass


def _exception_graph(error: BaseException) -> tuple[list[BaseException], bool]:
    """Return identity-unique graph nodes and whether any active path contains a cycle."""
    nodes: list[BaseException] = []
    visited: set[int] = set()
    active: set[int] = set()
    has_cycle = False

    def visit(current: BaseException) -> None:
        """Visit cause, context, and exception-group edges by object identity."""
        nonlocal has_cycle
        identity = id(current)
        if identity in active:
            has_cycle = True
            return
        if identity in visited:
            return
        visited.add(identity)
        active.add(identity)
        nodes.append(current)
        edges: list[BaseException] = []
        if current.__cause__ is not None:
            edges.append(current.__cause__)
        if current.__context__ is not None:
            edges.append(current.__context__)
        if isinstance(current, BaseExceptionGroup):
            edges.extend(current.exceptions)
        for nested in edges:
            visit(nested)
        active.remove(identity)

    visit(error)
    return nodes, has_cycle


def _exception_messages(error: BaseException) -> list[str]:
    """Return messages from the complete identity-unique exception graph."""
    nodes, _ = _exception_graph(error)
    return [str(node) for node in nodes]


def _two_stream_record(debt_id: str) -> tuple[_Process, LaunchRecord, int, Any, Any]:
    """Create one launch record owning two real streams and one raw descriptor."""
    stdin_read, stdin_write = os.pipe()
    stdout_read, stdout_write = os.pipe()
    result_read, result_write = os.pipe()
    os.close(stdin_read)
    os.close(stdout_write)
    os.close(result_write)
    stdin = os.fdopen(stdin_write, "wb", buffering=0)
    stdout = os.fdopen(stdout_read, "rb", buffering=0)
    process = _Process(stdin, None)
    process.stdout = stdout
    return process, LaunchRecord(debt_id, process=process, result_fd=result_read), result_read, stdin, stdout


def _assert_two_streams_closed(
    record: LaunchRecord, result_fd: int, stdin: Any, stdout: Any
) -> None:
    """Assert every real channel is closed and the exact cleanup lease is released."""
    assert stdin.closed and stdout.closed
    with pytest.raises(OSError):
        os.fstat(result_fd)
    assert record.result_fd is None
    assert all(channel.state == "closed" for channel in record.cleanup.channels.values())
    assert record.cleanup.execution_owner is None
    assert record.cleanup.execution_depth == 0


@pytest.mark.parametrize("operation", ["initial", "retry"])
def test_nested_cleanup_interruptions_retain_every_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Process and channel interruptions must retain an intervening ordinary error."""
    signals: list[tuple[int, int]] = []

    class NestedFailureBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise KeyboardInterrupt("fixture process interruption")

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise RuntimeError("fixture ordinary channel failure")
            if name == "stdout":
                raise KeyboardInterrupt("fixture channel interruption")

    backend = NestedFailureBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"nested-{operation}-debt"
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    if operation == "retry":
        backend._record_process_debt(record.debt_id, process, "fixture", record)

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            if operation == "initial":
                backend._finish_record(
                    record,
                    "worker_lost",
                    {"stdout": bytearray(), "stderr": bytearray()},
                    {"stdout": 0, "stderr": 0},
                    "transport_error",
                )
            else:
                backend.retry_cleanup(record.debt_id)
        assert str(raised.value) == "fixture process interruption"
        messages = _exception_messages(raised.value)
        assert "fixture ordinary channel failure" in messages
        assert "fixture channel interruption" in messages
        _assert_two_streams_closed(record, result_fd, stdin, stdout)
        debts = backend.cleanup_debts()
        assert [debt.debt_id for debt in debts] == [record.debt_id]
        assert backend._debt_processes[record.debt_id].state == "pending"
        assert not record.cleanup.termination_confirmed
        assert signals == []
    finally:
        stdin.close()
        stdout.close()
        try:
            os.close(result_fd)
        except OSError:
            pass


@pytest.mark.parametrize("operation", ["initial", "retry"])
def test_outer_cleanup_diagnostics_preserve_existing_interruption_cause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Outer process errors must not replace a channel interruption's diagnostics."""
    signals: list[tuple[int, int]] = []

    class NestedCauseBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise RuntimeError("fixture ordinary process failure")

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise ValueError("fixture ordinary channel failure")
            if name == "stdout":
                raise KeyboardInterrupt("fixture channel interruption")

    backend = NestedCauseBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"nested-cause-{operation}-debt"
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    if operation == "retry":
        backend._record_process_debt(record.debt_id, process, "fixture", record)

    try:
        with pytest.raises(KeyboardInterrupt) as raised:
            if operation == "initial":
                backend._finish_record(
                    record,
                    "worker_lost",
                    {"stdout": bytearray(), "stderr": bytearray()},
                    {"stdout": 0, "stderr": 0},
                    "transport_error",
                )
            else:
                backend.retry_cleanup(record.debt_id)
        assert str(raised.value) == "fixture channel interruption"
        messages = _exception_messages(raised.value)
        assert "fixture ordinary process failure" in messages
        assert "fixture ordinary channel failure" in messages
        assert len(messages) == len(set(messages))
        _assert_two_streams_closed(record, result_fd, stdin, stdout)
        debts = backend.cleanup_debts()
        assert [debt.debt_id for debt in debts] == [record.debt_id]
        assert backend._debt_processes[record.debt_id].state == "pending"
        assert not record.cleanup.termination_confirmed
        assert signals == []
    finally:
        stdin.close()
        stdout.close()
        try:
            os.close(result_fd)
        except OSError:
            pass


@pytest.mark.parametrize("operation", ["initial", "retry"])
def test_cleanup_inside_outer_except_retains_shared_context_diagnostics(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Shared outer contexts must not discard independent cleanup diagnostics."""
    signals: list[tuple[int, int]] = []
    process_error = RuntimeError("fixture ordinary process failure")
    channel_error = ValueError("fixture ordinary channel failure")
    interruption = KeyboardInterrupt("fixture channel interruption")

    class SharedContextBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise process_error

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise channel_error
            if name == "stdout":
                raise interruption

    backend = SharedContextBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"shared-context-{operation}-debt"
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    if operation == "retry":
        backend._record_process_debt(record.debt_id, process, "fixture", record)

    try:
        outer_error = LookupError("fixture active outer failure")
        try:
            raise outer_error
        except LookupError:
            with pytest.raises(KeyboardInterrupt) as raised:
                if operation == "initial":
                    backend._finish_record(
                        record,
                        "worker_lost",
                        {"stdout": bytearray(), "stderr": bytearray()},
                        {"stdout": 0, "stderr": 0},
                        "transport_error",
                    )
                else:
                    backend.retry_cleanup(record.debt_id)
        assert raised.value is interruption
        nodes, has_cycle = _exception_graph(raised.value)
        assert any(node is process_error for node in nodes)
        assert any(node is channel_error for node in nodes)
        assert any(node is outer_error for node in nodes)
        assert not has_cycle
        _assert_two_streams_closed(record, result_fd, stdin, stdout)
        debts = backend.cleanup_debts()
        assert [debt.debt_id for debt in debts] == [record.debt_id]
        assert backend._debt_processes[record.debt_id].state == "pending"
        assert not record.cleanup.termination_confirmed
        assert signals == []
    finally:
        stdin.close()
        stdout.close()
        try:
            os.close(result_fd)
        except OSError:
            pass

@pytest.mark.parametrize("operation", ["initial", "retry"])
def test_multiple_ordinary_cleanup_errors_remain_inspectable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Ordinary process and channel failures must all remain inspectable."""
    signals: list[tuple[int, int]] = []

    class OrdinaryFailureBackend(IsolatedProcessBackend):
        def _terminate_owned(self, process: Any) -> bool:
            raise RuntimeError("fixture ordinary termination failure")

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            if name == "stdin":
                raise ValueError("fixture first ordinary channel failure")
            if name == "stdout":
                raise OSError("fixture second ordinary channel failure")

    backend = OrdinaryFailureBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"multiple-ordinary-{operation}-debt"
    )
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signals.append((pgid, sig)))
    if operation == "retry":
        backend._record_process_debt(record.debt_id, process, "fixture", record)

    try:
        with pytest.raises(ExceptionGroup) as raised:
            if operation == "initial":
                backend._finish_record(
                    record,
                    "worker_lost",
                    {"stdout": bytearray(), "stderr": bytearray()},
                    {"stdout": 0, "stderr": 0},
                    "transport_error",
                )
            else:
                backend.retry_cleanup(record.debt_id)
        messages = _exception_messages(raised.value)
        assert "fixture ordinary termination failure" in messages
        assert "fixture first ordinary channel failure" in messages
        assert "fixture second ordinary channel failure" in messages
        _assert_two_streams_closed(record, result_fd, stdin, stdout)
        debts = backend.cleanup_debts()
        assert [debt.debt_id for debt in debts] == [record.debt_id]
        assert backend._debt_processes[record.debt_id].state == "pending"
        assert not record.cleanup.termination_confirmed
        assert signals == []
    finally:
        stdin.close()
        stdout.close()
        try:
            os.close(result_fd)
        except OSError:
            pass
