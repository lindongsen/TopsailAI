"""Unit tests for provider-neutral LLM request tracking."""

import pytest

from topsailai.ai_base.llm_control.request_tracking import (
    iter_stream_for_request_timing,
    log_first_byte_timeout,
)


def test_log_first_byte_timeout_formats_and_emits_warning():
    """Format the exact timeout warning and pass it to the callback once."""
    warnings = []

    result = log_first_byte_timeout(
        1.26,
        0.5,
        warning_func=warnings.append,
        service_keyword="LLM Service",
    )

    assert result is None
    assert warnings == [
        "LLM Service: first byte timeout threshold reached/exceeded: "
        "elapsed 1.3s >= threshold 0.5s"
    ]


def test_iter_stream_times_normal_yields_and_terminal_read():
    """Resume and pause each successful and terminal iterator operation."""
    ticket = object()
    calls = []

    chunks = list(
        iter_stream_for_request_timing(
            ["first", "second"],
            ticket,
            resume=lambda value: calls.append(("resume", value)),
            pause=lambda value: calls.append(("pause", value)),
        )
    )

    assert chunks == ["first", "second"]
    assert calls == [
        ("resume", ticket),
        ("pause", ticket),
        ("resume", ticket),
        ("pause", ticket),
        ("resume", ticket),
        ("pause", ticket),
    ]


def test_iter_stream_pauses_and_reraises_identical_base_exception():
    """Pause once and propagate the identical provider BaseException instance."""
    class ProviderAbort(BaseException):
        """Represent a provider iterator abort outside Exception handling."""

    error = ProviderAbort("provider aborted")
    ticket = object()
    calls = []

    def failing_stream():
        """Raise the pre-created provider abort during the first iterator read."""
        raise error
        yield

    timed_stream = iter_stream_for_request_timing(
        failing_stream(),
        ticket,
        resume=lambda value: calls.append(("resume", value)),
        pause=lambda value: calls.append(("pause", value)),
    )

    with pytest.raises(ProviderAbort) as exc_info:
        next(timed_stream)

    assert exc_info.value is error
    assert calls == [("resume", ticket), ("pause", ticket)]
