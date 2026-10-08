"""Deterministic tests for hook-script concurrent transport boundaries."""

from __future__ import annotations

import selectors
import threading
from types import SimpleNamespace

import pytest

from topsailai.hooks.hook_script_contracts import HookScriptExecutionPolicy
from topsailai.hooks import process_transport
from topsailai.hooks.process_transport import ScriptTransportFacts


class _Stream:
    """Expose one inert descriptor for transport setup."""

    def __init__(self, descriptor: int) -> None:
        self._descriptor = descriptor

    def fileno(self) -> int:
        """Return the deterministic descriptor."""
        return self._descriptor


class _Process:
    """Model a child that has exited while output EOF is pending."""

    def __init__(self) -> None:
        self.stdin = _Stream(10)
        self.stdout = _Stream(11)
        self.stderr = _Stream(12)

    def poll(self) -> int:
        """Return a settled zero exit code."""
        return 0


class _BoundarySelector:
    """Advance a controlled clock while returning all final output EOF events."""

    def __init__(
        self,
        clock: list[float],
        returned_at: float,
        cancellation: threading.Event | None = None,
    ) -> None:
        self._clock = clock
        self._returned_at = returned_at
        self._cancellation = cancellation
        self._keys: dict[int, SimpleNamespace] = {}

    def register(self, descriptor: int, _: int, data: str) -> None:
        """Record one selector key."""
        self._keys[descriptor] = SimpleNamespace(fd=descriptor, data=data)

    def unregister(self, descriptor: int) -> None:
        """Remove one selector key after EOF."""
        self._keys.pop(descriptor, None)

    def select(self, _: float) -> list[tuple[SimpleNamespace, int]]:
        """Cross the controlled boundary and publish final readable channels."""
        self._clock[0] = self._returned_at
        if self._cancellation is not None:
            self._cancellation.set()
        return [
            (key, selectors.EVENT_READ)
            for key in tuple(self._keys.values())
            if key.data != "stdin"
        ]

    def close(self) -> None:
        """Close the inert selector."""


@pytest.mark.parametrize(
    ("returned_at", "cancel_during_select", "expected"),
    [
        (0.9, False, "settled"),
        (1.0, False, "deadline"),
        (0.9, True, "cancelled"),
    ],
)
def test_completion_after_select_observes_deadline_and_cancellation_first(
    monkeypatch: pytest.MonkeyPatch,
    returned_at: float,
    cancel_during_select: bool,
    expected: str,
) -> None:
    """Final EOF cannot outrun a deadline or cancellation observed during select."""
    clock = [0.5]
    cancellation = threading.Event()
    selector = _BoundarySelector(
        clock,
        returned_at,
        cancellation if cancel_during_select else None,
    )
    monkeypatch.setattr(process_transport.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(process_transport.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(process_transport.os, "set_blocking", lambda *_: None)
    monkeypatch.setattr(process_transport.os, "read", lambda *_: b"")

    facts = process_transport.drain_script_process(
        _Process(),
        13,
        b"request",
        HookScriptExecutionPolicy(),
        1.0,
        4096,
        cancellation,
        lambda: None,
    )

    assert facts.settled is (expected == "settled")
    assert facts.deadline is (expected == "deadline")
    assert facts.cancelled is (expected == "cancelled")


@pytest.mark.parametrize("error_fact", ["overflow", "invalid_result", "transport_error"])
@pytest.mark.parametrize(
    ("returned_at", "cancel_during_select", "expected_stop"),
    [(1.0, False, "deadline"), (0.9, True, "cancelled")],
)
def test_event_errors_cannot_bypass_deadline_or_cancellation_observation(
    monkeypatch: pytest.MonkeyPatch,
    error_fact: str,
    returned_at: float,
    cancel_during_select: bool,
    expected_stop: str,
) -> None:
    """Event errors remain recorded without hiding a concurrent stop condition."""
    clock = [0.5]
    cancellation = threading.Event()
    selector = _BoundarySelector(
        clock,
        returned_at,
        cancellation if cancel_during_select else None,
    )

    def record_error(*args: object, **kwargs: object) -> None:
        """Record the selected event-processing failure fact."""
        facts = args[3]
        setattr(facts, error_fact, True)

    monkeypatch.setattr(process_transport.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(process_transport.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(process_transport.os, "set_blocking", lambda *_: None)
    monkeypatch.setattr(process_transport, "_read_output", record_error)

    facts = process_transport.drain_script_process(
        _Process(),
        13,
        b"request",
        HookScriptExecutionPolicy(),
        1.0,
        4096,
        cancellation,
        lambda: None,
    )

    assert getattr(facts, error_fact)
    assert facts.deadline is (expected_stop == "deadline")
    assert facts.cancelled is (expected_stop == "cancelled")
    assert not facts.settled


class _ReadSelector:
    """Provide the unregister surface used by output reads."""

    def unregister(self, _: int) -> None:
        """Accept an EOF unregister operation."""


def test_mixed_channels_retain_only_aggregate_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Observed cap-plus-one bytes are counted but never retained past the batch cap."""
    chunks = iter((b"\x00\x00\x00\x01", b"abc", b"defg"))
    monkeypatch.setattr(process_transport.os, "read", lambda *_: next(chunks))
    facts = ScriptTransportFacts()
    policy = HookScriptExecutionPolicy(
        stdout_limit_bytes=16,
        stderr_limit_bytes=16,
        result_limit_bytes=16,
        output_total_limit_bytes=10,
    )
    selector = _ReadSelector()

    process_transport._read_output(selector, 20, "result", facts, policy, 10)
    process_transport._read_output(selector, 21, "stdout", facts, policy, 10)
    process_transport._read_output(selector, 22, "stderr", facts, policy, 10)

    assert facts.observed_bytes == 11
    assert facts.result_observed_bytes == 4
    assert len(facts.result) + len(facts.stdout) + len(facts.stderr) == 10
    assert facts.result == b"\x00\x00\x00\x01"
    assert facts.stdout == b"abc"
    assert facts.stderr == b"def"
    assert facts.stdout_dropped == 0
    assert facts.stderr_dropped == 1
    assert facts.overflow


class _ExceptionalSelector(_BoundarySelector):
    """Raise from select or EOF unregister after publishing a stop condition."""

    def __init__(
        self,
        clock: list[float],
        returned_at: float,
        cancellation: threading.Event | None,
        failure_site: str,
    ) -> None:
        super().__init__(clock, returned_at, cancellation)
        self._failure_site = failure_site

    def select(self, timeout: float) -> list[tuple[SimpleNamespace, int]]:
        """Publish the stop condition before the selected exceptional boundary."""
        events = super().select(timeout)
        if self._failure_site == "select":
            raise OSError("injected selector failure")
        return events

    def unregister(self, descriptor: int) -> None:
        """Raise while settling an output EOF when requested."""
        if self._failure_site == "unregister":
            raise OSError("injected unregister failure")
        super().unregister(descriptor)


@pytest.mark.parametrize("failure_site", ["select", "unregister"])
@pytest.mark.parametrize(
    ("returned_at", "cancel_during_select", "expected_stop"),
    [(1.0, False, "deadline"), (0.9, True, "cancelled")],
)
def test_oserror_exit_preserves_concurrent_stop_facts(
    monkeypatch: pytest.MonkeyPatch,
    failure_site: str,
    returned_at: float,
    cancel_during_select: bool,
    expected_stop: str,
) -> None:
    """Exceptional selector exits retain transport error and current stop facts."""
    clock = [0.5]
    cancellation = threading.Event()
    selector = _ExceptionalSelector(
        clock,
        returned_at,
        cancellation if cancel_during_select else None,
        failure_site,
    )
    monkeypatch.setattr(process_transport.selectors, "DefaultSelector", lambda: selector)
    monkeypatch.setattr(process_transport.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(process_transport.os, "set_blocking", lambda *_: None)
    monkeypatch.setattr(process_transport.os, "read", lambda *_: b"")

    facts = process_transport.drain_script_process(
        _Process(),
        13,
        b"request",
        HookScriptExecutionPolicy(),
        1.0,
        4096,
        cancellation,
        lambda: None,
    )

    assert facts.transport_error
    assert facts.deadline is (expected_stop == "deadline")
    assert facts.cancelled is (expected_stop == "cancelled")
    assert not facts.settled
