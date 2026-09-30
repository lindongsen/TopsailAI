"""Regressions for cleanup diagnostics that point back to the primary interruption."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord
from topsailai.tests.unit.test_topsailai_hooks.test_retry_independent_channels import (
    _assert_two_streams_closed,
    _exception_graph,
    _two_stream_record,
)


@pytest.mark.parametrize("operation", ["initial", "retry"])
def test_primary_backreference_uses_explicit_acyclic_representation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Detach a contradictory back edge while retaining each original exception object."""
    signals: list[tuple[int, int]] = []
    interruption = KeyboardInterrupt("fixture channel interruption")
    process_error = RuntimeError("fixture process failure")
    process_error.__cause__ = interruption
    channel_error = ValueError("fixture ordinary channel failure")

    class BackreferenceBackend(IsolatedProcessBackend):
        """Raise the fixed exception objects at deterministic cleanup seams."""

        def _terminate_owned(self, process: Any) -> bool:
            """Raise a process diagnostic whose cause points to the future primary."""
            raise process_error

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            """Raise an ordinary channel error followed by the primary interruption."""
            if name == "stdin":
                raise channel_error
            if name == "stdout":
                raise interruption

    backend = BackreferenceBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"primary-backreference-{operation}-debt"
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
        assert process_error.__cause__ is None
        assert process_error.__notes__ == [
            "cleanup diagnostic backreference to the primary interruption "
            "was detached from cause to preserve an acyclic graph"
        ]
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
def test_group_member_primary_backreference_uses_acyclic_representation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """Detach an edge to a group containing primary while retaining every object."""
    signals: list[tuple[int, int]] = []
    interruption = KeyboardInterrupt("fixture channel interruption")
    original_group = BaseExceptionGroup(
        "fixture primary group",
        [interruption],
    )
    process_error = RuntimeError("fixture process failure")
    process_error.__cause__ = original_group
    channel_error = ValueError("fixture ordinary channel failure")

    class GroupBackreferenceBackend(IsolatedProcessBackend):
        """Raise a diagnostic whose cause group contains the future primary."""

        def _terminate_owned(self, process: Any) -> bool:
            """Raise the process diagnostic with its original group cause."""
            raise process_error

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            """Raise an ordinary channel error followed by the primary interruption."""
            if name == "stdin":
                raise channel_error
            if name == "stdout":
                raise interruption

    backend = GroupBackreferenceBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"group-backreference-{operation}-debt"
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
        assert process_error.__cause__ is None
        assert process_error.__cleanup_detached_diagnostics__ == (original_group,)
        assert original_group.exceptions[0] is interruption
        assert process_error.__notes__ == [
            "cleanup diagnostic backreference to the primary interruption "
            "was detached from cause to preserve an acyclic graph"
        ]
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
@pytest.mark.parametrize("nested", [False, True], ids=["direct", "nested"])
def test_diagnostic_group_containing_primary_uses_sidecar(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    nested: bool,
) -> None:
    """Retain an immutable diagnostic group outside the acyclic exception graph."""
    signals: list[tuple[int, int]] = []
    interruption = KeyboardInterrupt("fixture process interruption")
    channel_error = ValueError("fixture grouped channel failure")
    inner_group = BaseExceptionGroup(
        "fixture inner diagnostic group", [interruption, channel_error]
    )
    diagnostic_group = (
        BaseExceptionGroup("fixture outer diagnostic group", [inner_group])
        if nested
        else inner_group
    )

    class DiagnosticGroupBackend(IsolatedProcessBackend):
        """Raise primary first and its immutable diagnostic group from a channel."""

        def _terminate_owned(self, process: Any) -> bool:
            """Raise the primary process interruption."""
            raise interruption

        def _after_channel_close(
            self, record: LaunchRecord, name: str, descriptor: int
        ) -> None:
            """Raise the direct or nested group after closing the first stream."""
            if name == "stdin":
                raise diagnostic_group

    backend = DiagnosticGroupBackend(temp_root=str(tmp_path))
    process, record, result_fd, stdin, stdout = _two_stream_record(
        f"diagnostic-group-{operation}-{nested}-debt"
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
        assert any(node is outer_error for node in nodes)
        assert all(node is not diagnostic_group for node in nodes)
        assert all(node is not channel_error for node in nodes)
        assert not has_cycle
        assert interruption.__cleanup_detached_diagnostics__ == (diagnostic_group,)
        assert diagnostic_group.exceptions[0] is (
            inner_group if nested else interruption
        )
        assert inner_group.exceptions == (interruption, channel_error)
        assert interruption.__notes__ == [
            "cleanup diagnostic with an immutable group-member backreference "
            "to the primary interruption was retained outside the exception graph"
        ]
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
