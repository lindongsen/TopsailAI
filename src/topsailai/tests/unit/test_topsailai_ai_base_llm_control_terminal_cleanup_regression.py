"""Regression tests for terminal stream cleanup state initialization.

Author: DawsonLin
"""

import threading
import time
from unittest.mock import Mock
import pytest

from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget
from topsailai.ai_base.llm_control.first_byte_timeout import iter_with_first_byte_timeout
from topsailai.ai_base.llm_control.response_ownership import AttemptResponseOwner


@pytest.mark.parametrize("values", [(), ("first", "tail")])
def test_normal_terminal_cleanup_has_no_primary_error(values, monkeypatch):
    """Normal EOF and complete streams dispose with an explicit null primary."""
    owner = AttemptResponseOwner()
    owner.dispose = Mock(wraps=owner.dispose)
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.AttemptResponseOwner",
        lambda: owner,
    )
    pause = Mock()
    output = list(iter_with_first_byte_timeout(
        iter(values), 1, budget=FirstByteBudget.create(1),
        timing_ticket="ticket", pause=pause,
        on_timeout=Mock(), make_timeout_error=TimeoutError,
    ))
    assert output == list(values)
    pause.assert_called_once_with("ticket")
    owner.dispose.assert_called_once_with(primary=None, background=False)


def test_pause_error_is_not_masked_by_uninitialized_cleanup_state():
    """A pause failure after normal EOF retains its original exception identity."""
    error = OSError("pause failed")
    with pytest.raises(OSError) as caught:
        list(iter_with_first_byte_timeout(
            iter(()), 1, budget=FirstByteBudget.create(1),
            timing_ticket="ticket", pause=Mock(side_effect=error),
            on_timeout=Mock(), make_timeout_error=TimeoutError,
        ))
    assert caught.value is error


def test_tail_failure_remains_primary_when_pause_also_fails():
    """Cleanup diagnostics cannot replace a failure raised after the first item."""
    error = LookupError("tail failed")

    def stream():
        """Yield once before raising the exact provider failure."""
        yield "first"
        raise error

    with pytest.raises(LookupError) as caught:
        list(iter_with_first_byte_timeout(
            stream(), 1, budget=FirstByteBudget.create(1),
            timing_ticket="ticket", pause=Mock(side_effect=OSError("pause failed")),
            on_timeout=Mock(), make_timeout_error=TimeoutError,
        ))
    assert caught.value is error
    assert any("pause failed" in note for note in error.__notes__)



def test_early_worker_error_after_wait_timeout_disposes_local_stream(monkeypatch):
    """A completed worker error after an uncommitted wait closes local custody."""
    error = OSError("provider failure")
    clock_now = [0.0]

    class CloseAwareStream:
        def __init__(self):
            self.started = threading.Event()
            self.closed_count = 0

        def __iter__(self):
            return self

        def __next__(self):
            self.started.set()
            clock_now[0] = 2.0
            raise error

        def close(self):
            self.closed_count += 1

    class ReadyGate:
        def __init__(self, stream):
            self._stream = stream
            self.finished = threading.Event()
            self._set = False

        def set(self):
            self._set = True
            self.finished.set()

        def is_set(self):
            return self._set

        def wait(self, timeout=None):
            assert self._stream.started.wait(1)
            assert self.finished.wait(1)
            return False

    class ThreadingProxy:
        Thread = threading.Thread

        def __init__(self, ready_gate):
            self._ready_gate = ready_gate

        def Event(self):
            return self._ready_gate

    stream = CloseAwareStream()
    ready_gate = ReadyGate(stream)
    owner = AttemptResponseOwner()
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.AttemptResponseOwner",
        lambda: owner,
    )
    monkeypatch.setattr(
        "topsailai.ai_base.llm_control.first_byte_timeout.threading",
        ThreadingProxy(ready_gate),
    )

    budget = FirstByteBudget.create(1, clock=lambda: clock_now[0])
    with pytest.raises(OSError) as caught:
        list(iter_with_first_byte_timeout(
            stream, 1, raise_on_timeout=True, budget=budget,
            on_timeout=Mock(), make_timeout_error=TimeoutError,
        ))

    assert caught.value is error
    assert ready_gate.is_set()
    assert stream.closed_count == 1
