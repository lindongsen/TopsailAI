"""Context-local LLM request outcome tracking.

This module owns the two context-local variables that track whether a provider
request has started and which timing ticket is active, plus the decorator that
records one outcome (success or failure) and finishes timing for each started
provider request. It is provider-neutral: it does not import OpenAI, HTTPX, or
HTTPCore. ``LLMModel`` remains responsible for starting, pausing, resuming, and
finishing individual provider requests through its request-stat methods.
"""

import contextvars
import functools

_llm_request_started = contextvars.ContextVar(
    "topsailai_llm_request_started", default=False
)
_llm_request_timing_ticket = contextvars.ContextVar(
    "topsailai_llm_request_timing_ticket", default=None
)


def record_llm_request_outcome(method):
    """Record one outcome and finish timing for each started provider request."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        started_token = _llm_request_started.set(False)
        ticket_token = _llm_request_timing_ticket.set(None)
        try:
            result = method(self, *args, **kwargs)
            if _llm_request_started.get():
                self._record_llm_request_success()
            return result
        except BaseException:
            if _llm_request_started.get():
                self._record_llm_request_failure()
                ticket = _llm_request_timing_ticket.get()
                if ticket is not None:
                    self._finish_llm_request(ticket)
            raise
        finally:
            _llm_request_timing_ticket.reset(ticket_token)
            _llm_request_started.reset(started_token)

    return wrapper


def log_first_byte_timeout(
    elapsed,
    first_byte_timeout,
    *,
    warning_func,
    service_keyword,
):
    """Emit a first-byte timeout warning through an injected callback."""
    warning_func(
        f"{service_keyword}: first byte timeout threshold reached/exceeded: "
        f"elapsed {elapsed:.1f}s >= threshold {first_byte_timeout}s"
    )


def iter_stream_for_request_timing(stream, ticket, *, resume, pause):
    """Time only blocking provider iterator operations, not chunk processing.

    The ``resume`` and ``pause`` callbacks are invoked around each blocking
    ``next(iterator)`` so that local chunk processing performed by the caller
    between yields is excluded from the provider request/response duration.
    This helper is provider-neutral: it does not import OpenAI, HTTPX, or
    HTTPCore, and it never touches the timing ticket itself.
    """
    iterator = iter(stream)
    while True:
        resume(ticket)
        try:
            chunk = next(iterator)
        except StopIteration:
            pause(ticket)
            return
        except BaseException:
            pause(ticket)
            raise
        pause(ticket)
        yield chunk
