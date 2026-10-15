"""Regression tests for deterministic first-byte terminal warnings.

Author: DawsonLin
"""

import threading
from unittest.mock import Mock

import pytest

from topsailai.ai_base.llm_control.first_byte_deadline import (
    FirstByteBudget,
    first_byte_budget_scope,
)
from topsailai.ai_base.llm_control.first_byte_timeout import (
    FirstByteTimeoutMixin,
    iter_with_first_byte_timeout,
)
from topsailai.ai_base.llm_control.response_ownership import (
    response_ownership_scope,
)


class CloseAwareEOF:
    """Produce one EOF and count the exact underlying close."""

    def __init__(self, now, release=None):
        """Initialize the injected clock and optional read gate."""
        self.now = now
        self.release = release
        self.reads = 0
        self.closed = 0

    def __iter__(self):
        """Return this iterator."""
        return self

    def __next__(self):
        """Perform exactly one read and publish late EOF."""
        self.reads += 1
        if self.release is not None:
            assert self.release.wait(1)
        self.now[0] = 2.0
        raise StopIteration

    def close(self):
        """Record local ownership cleanup."""
        self.closed += 1


def test_late_eof_warns_once_without_rereading_or_restarting():
    """A late EOF retains EOF semantics and emits exactly one warning."""
    now = [0.0]
    stream = CloseAwareEOF(now)
    warnings = []
    budget = FirstByteBudget.create(1.0, clock=lambda: now[0])

    assert list(iter_with_first_byte_timeout(
        stream, 1, budget=budget,
        on_timeout=lambda elapsed, timeout: warnings.append((elapsed, timeout)),
        make_timeout_error=TimeoutError,
    )) == []
    assert warnings == [(2.0, 1.0)]
    assert stream.reads == 1
    assert stream.closed == 1


def test_late_terminal_warning_is_protected_from_callback_failure():
    """A warning callback failure cannot change a committed EOF result."""
    now = [0.0]
    stream = CloseAwareEOF(now)
    warning = Mock(side_effect=RuntimeError("diagnostic failure"))
    assert list(iter_with_first_byte_timeout(
        stream, 1, budget=FirstByteBudget.create(1, clock=lambda: now[0]),
        on_timeout=warning, make_timeout_error=TimeoutError,
    )) == []
    warning.assert_called_once()
    assert stream.closed == 1


class _ReadyGate:
    """Control readiness so each scheduling order is deterministic."""

    def __init__(self, first_wait_result=None, clock=None, timeout_at=None):
        """Initialize a test-owned worker completion gate."""
        self.finished = threading.Event()
        self.first_wait_result = first_wait_result
        self.clock = clock
        self.timeout_at = timeout_at
        self.wait_calls = 0

    def set(self):
        """Publish worker completion."""
        self.finished.set()

    def is_set(self):
        """Expose readiness state."""
        return self.finished.is_set()

    def wait(self, timeout=None):
        """Return the configured first result, then await completion."""
        self.wait_calls += 1
        if self.wait_calls == 1 and self.first_wait_result is not None:
            if self.clock is not None and self.timeout_at is not None:
                self.clock[0] = self.timeout_at
            return self.first_wait_result
        return self.finished.wait(timeout)

class _ThreadingProxy:
    """Replace only the timeout module's Event and Thread seams."""

    def __init__(self, gate, *, join_on_start=False):
        """Store the test-owned readiness gate and scheduling mode."""
        self.gate = gate
        self.join_on_start = join_on_start
        self.threads = []

    def Event(self):
        """Return the test-owned gate."""
        return self.gate

    def Thread(self, *, target, daemon=True):
        """Return a real thread with optional deterministic completion."""
        thread = threading.Thread(target=target, daemon=daemon)
        if not self.join_on_start:
            self.threads.append(thread)
            return thread

        class JoinedThread:
            """Join the test-created worker before exposing readiness."""

            def __init__(self, wrapped):
                """Store the real worker."""
                self._wrapped = wrapped

            def start(self):
                """Start and join only this test-created worker."""
                self._wrapped.start()
                self._wrapped.join(1)
                assert not self._wrapped.is_alive()

            def is_alive(self):
                """Expose worker state for ownership diagnostics."""
                return self._wrapped.is_alive()

        joined = JoinedThread(thread)
        self.threads.append(thread)
        return joined

    def join_workers(self):
        """Settle all test-created workers and require completion."""
        for thread in self.threads:
            thread.join()
            assert not thread.is_alive()


class _ProductionWrapper(FirstByteTimeoutMixin):
    """Expose the production stream wrapper without provider SDK details."""

    def __init__(self, warning_callback):
        """Store the test-owned warning callback."""
        self.warning_callback = warning_callback

    def _get_llm_request_timing_ticket(self):
        """Use the production wrapper's no-duplicate-pause configuration."""
        return None

    def _log_first_byte_timeout(self, elapsed, timeout):
        """Route production warning diagnostics to the test observer."""
        self.warning_callback(elapsed, timeout)

    def _resume_llm_request(self, ticket):
        """Provide the production wrapper's timing seam."""

    def _pause_llm_request(self, ticket):
        """Provide the production wrapper's timing seam."""

    def _make_first_byte_timeout_error(self, timeout):
        """Construct the production wrapper's timeout exception."""
        return TimeoutError(timeout)


def test_production_owned_late_eof_forced_already_ready(monkeypatch):
    """The production-owned path catches an already-ready late EOF once."""
    now = [0.0]
    stream = CloseAwareEOF(now)
    warnings = []
    gate = _ReadyGate(True)
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.threading",
        _ThreadingProxy(gate, join_on_start=True),
    )
    budget = FirstByteBudget.create(1.0, clock=lambda: now[0])
    wrapper = _ProductionWrapper(lambda elapsed, timeout: warnings.append((elapsed, timeout)))
    with response_ownership_scope() as owner:
        owner.publish_response(stream)
        with first_byte_budget_scope(budget):
            result = list(wrapper.iter_stream_with_first_byte_timeout(stream, 1))
    assert result == []
    assert warnings == [(2.0, 1.0)]
    assert stream.reads == 1
    assert stream.closed == 1
    assert gate.wait_calls == 1

def test_production_owned_late_eof_forced_wait_timeout_first(monkeypatch):
    """The production-owned path also catches wait-timeout-first EOF once."""
    now = [0.0]
    stream = CloseAwareEOF(now)
    warnings = []
    gate = _ReadyGate(False, clock=now, timeout_at=1.0)
    release = threading.Event()
    stream.release = release
    proxy = _ThreadingProxy(gate)
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.threading",
        proxy,
    )
    budget = FirstByteBudget.create(1.0, clock=lambda: now[0])

    def warning(elapsed, timeout):
        """Release the same blocked original read after warning."""
        warnings.append((elapsed, timeout))
        release.set()

    wrapper = _ProductionWrapper(warning)
    try:
        with response_ownership_scope() as owner:
            owner.publish_response(stream)
            with first_byte_budget_scope(budget):
                result = list(wrapper.iter_stream_with_first_byte_timeout(stream, 1))
    finally:
        release.set()
        proxy.join_workers()
    assert result == []
    assert warnings == [(1.0, 1.0)]
    assert stream.reads == 1
    assert stream.closed == 1
    assert gate.wait_calls == 2



@pytest.mark.parametrize("published_at", [0.5, 1.0, 2.0])
def test_terminal_eof_boundary_warning_count(published_at):
    """EOF at each publication boundary warns zero or exactly once."""
    now = [0.0]
    warnings = []

    class BoundaryEOF(CloseAwareEOF):
        """Publish EOF at the selected boundary."""

        def __next__(self):
            """Perform one read and publish at the injected boundary."""
            self.reads += 1
            self.now[0] = published_at
            raise StopIteration

    stream = BoundaryEOF(now)
    assert list(iter_with_first_byte_timeout(
        stream, 1, budget=FirstByteBudget.create(1, clock=lambda: now[0]),
        on_timeout=lambda elapsed, timeout: warnings.append((elapsed, timeout)),
        make_timeout_error=TimeoutError,
    )) == []
    assert len(warnings) == (0 if published_at < 1 else 1)
    assert stream.reads == 1
    assert stream.closed == 1
