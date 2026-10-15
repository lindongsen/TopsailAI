"""Regression tests for explicit first-item ticket handoff.

Author: DawsonLin
"""

from unittest.mock import Mock

import pytest

from topsailai.ai_base.llm_control.first_byte_deadline import FirstByteBudget
from topsailai.ai_base.llm_control.first_byte_timeout import iter_with_first_byte_timeout


def test_value_pauses_before_delivery_and_only_once():
    """The explicit ticket pauses before the first value reaches the caller."""
    events = []
    stream = iter(("first", "tail"))

    def pause(ticket):
        events.append(("pause", ticket))

    output = iter_with_first_byte_timeout(
        stream, 1, budget=FirstByteBudget.create(1), timing_ticket="ticket",
        resume=lambda ticket: events.append(("resume", ticket)), pause=pause,
        on_timeout=Mock(), make_timeout_error=TimeoutError,
    )
    assert next(output) == "first"
    assert events == [("resume", "ticket"), ("pause", "ticket")]
    output.close()
    assert events == [("resume", "ticket"), ("pause", "ticket")]


def test_pause_failure_prevents_value_and_tail_delivery():
    """The first pause failure remains primary and prevents stream reads."""
    reads = []
    pause_error = OSError("pause failed")
    closed = []

    def stream():
        reads.append("first")
        yield "first"
        reads.append("tail")
        yield "tail"

    class CloseAware:
        """Count closure while delegating the test stream."""
        def __iter__(self):
            """Return the delegated iterator."""
            return self

        def __next__(self):
            """Read from the delegated stream."""
            return next(source)

        def close(self):
            """Record exactly one local close."""
            closed.append(1)

    source = iter(stream())
    wrapped = CloseAware()
    output = []
    generator = iter_with_first_byte_timeout(
        wrapped, 1, budget=FirstByteBudget.create(1),
        timing_ticket="ticket", pause=Mock(side_effect=pause_error),
        on_timeout=Mock(), make_timeout_error=TimeoutError,
    )
    try:
        with pytest.raises(OSError) as caught:
            output.append(next(generator))
    finally:
        generator.close()
    assert caught.value is pause_error
    assert output == []
    assert reads == ["first"]
    assert closed == [1]


def test_error_identity_is_primary_when_pause_fails():
    """A first-item provider error remains primary with a pause note."""
    provider_error = LookupError("provider failed")
    pause_error = OSError("pause failed")

    def stream():
        raise provider_error
        yield

    with pytest.raises(LookupError) as caught:
        list(iter_with_first_byte_timeout(
            stream(), 1, budget=FirstByteBudget.create(1),
            timing_ticket="ticket", pause=Mock(side_effect=pause_error),
            on_timeout=Mock(), make_timeout_error=TimeoutError,
        ))
    assert caught.value is provider_error
    assert any("pause failed" in note for note in provider_error.__notes__)


@pytest.mark.parametrize(
    ("kind", "published_at", "expected_warning"),
    [("VALUE", 0.5, False), ("VALUE", 1.0, True), ("VALUE", 2.0, True),
     ("EOF", 0.5, False), ("EOF", 1.0, True), ("EOF", 2.0, True),
     ("ERROR", 0.5, False), ("ERROR", 1.0, True), ("ERROR", 2.0, True)],
)
def test_terminal_handoff_boundary_matrix(kind, published_at, expected_warning):
    """VALUE, EOF, and ERROR honor boundaries and terminal handoff ordering."""
    now = [0.0]
    warnings = []
    events = []
    reads = []
    closed = []
    error = LookupError("provider failed")

    class ClockedStream:
        """Return one selected first terminal outcome and count close."""
        def __iter__(self):
            """Return this iterator."""
            return self

        def __next__(self):
            """Publish the selected outcome at the injected clock value."""
            if reads:
                raise StopIteration
            reads.append("first")
            now[0] = published_at
            if kind == "EOF":
                raise StopIteration
            if kind == "ERROR":
                raise error
            return "value"

        def close(self):
            """Record local-owner cleanup."""
            closed.append(1)

    def pause(ticket):
        """Record pause before the consumer observes the terminal result."""
        events.append(("pause", ticket))

    generator = iter_with_first_byte_timeout(
        ClockedStream(), 1, budget=FirstByteBudget.create(1, clock=lambda: now[0]),
        timing_ticket="ticket", pause=pause,
        on_timeout=lambda elapsed, timeout: warnings.append((elapsed, timeout)),
        make_timeout_error=TimeoutError,
    )
    if kind == "ERROR":
        with pytest.raises(LookupError) as caught:
            next(generator)
        assert caught.value is error
        assert events == [("pause", "ticket")]
    elif kind == "EOF":
        with pytest.raises(StopIteration):
            next(generator)
        assert events == [("pause", "ticket")]
    else:
        assert next(generator) == "value"
        assert events == [("pause", "ticket")]
    generator.close()
    assert len(warnings) == (0 if not expected_warning else 1)
    assert reads == ["first"]
    assert closed == [1]


def test_pause_crossing_deadline_does_not_retroactively_timeout():
    """A committed value remains valid while first-result pause is held."""
    now = [0.0]
    warnings = []
    events = []
    closed = []

    def pause(ticket):
        """Advance time only after the first item is committed."""
        events.append(("pause", ticket))
        now[0] = 2.0

    class CloseAwareValue:
        """Provide one value and count cleanup."""
        def __iter__(self):
            """Return this iterator."""
            return self

        def __next__(self):
            """Return exactly one committed value."""
            if getattr(self, "returned", False):
                raise StopIteration
            self.returned = True
            return "value"

        def close(self):
            """Record local cleanup."""
            closed.append(1)

    stream = CloseAwareValue()
    output = list(iter_with_first_byte_timeout(
        stream, 1, budget=FirstByteBudget.create(1, clock=lambda: now[0]),
        timing_ticket="ticket", pause=pause,
        on_timeout=lambda elapsed, timeout: warnings.append((elapsed, timeout)),
        make_timeout_error=TimeoutError,
    ))
    assert output == ["value"]
    assert events == [("pause", "ticket")]
    assert warnings == []
    assert closed == [1]


def test_successful_first_pause_precedes_tail_failure_and_closes_once():
    """A successful handoff precedes and preserves the original tail error."""
    tail_error = LookupError("tail failed")
    events = []
    reads = []
    closed = []

    class CloseAwareStream:
        """Track handoff, tail failure, and local close."""
        def __iter__(self):
            """Return this iterator."""
            return self

        def __next__(self):
            """Yield once, then raise the exact tail error."""
            if not reads:
                reads.append("first")
                return "first"
            reads.append("tail")
            raise tail_error

        def close(self):
            """Record local cleanup."""
            closed.append(1)

    def pause(ticket):
        """Prove pause occurs before the tail can be read."""
        events.append(("pause", ticket, list(reads)))

    stream = CloseAwareStream()
    with pytest.raises(LookupError) as caught:
        list(iter_with_first_byte_timeout(
            stream, 1, budget=FirstByteBudget.create(1),
            timing_ticket="ticket", pause=pause,
            on_timeout=Mock(), make_timeout_error=TimeoutError,
        ))
    assert caught.value is tail_error
    assert events == [("pause", "ticket", ["first"])]
    assert reads == ["first", "tail"]
    assert closed == [1]
