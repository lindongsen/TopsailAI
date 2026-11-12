"""Per-request LLM failure recording.

One logical LLM chat request may retry the same provider call many times.
``LLMModel.chat()`` owns those retries, so the consecutive failures of a single
request are invisible once the request returns. This module records every
failed attempt inside that one request and dispatches one report when the
request exits.

This module owns collection and lifecycle only. Presentation belongs to the
``hook__aibase__after__llm_request_failures`` Hook Point, so a new observer can
be added without touching ``LLMModel.chat()``.

The module is provider-neutral and deliberately does not classify retries:
``LLMModel.chat()`` keeps the retry decision and only reports each failure.
"""

from __future__ import annotations

import contextvars
import functools
import time
from typing import Callable, Optional

from topsailai.hooks.points.aibase.after_llm_request_failures import (
    hook__aibase__after__llm_request_failures,
)
from topsailai.hooks.points.aibase.after_llm_request_failures.point import (
    FAILURE_MESSAGE_MAX_CHARS,
    MAX_FAILURES,
)
from topsailai.logger.log_chat import logger

# Kept as module aliases so existing callers and tests keep one spelling.
MAX_RECORDED_FAILURES = MAX_FAILURES

_active_request_failure_log = contextvars.ContextVar(
    "topsailai_llm_request_failure_log", default=None
)


def _one_line(text: str, limit: int = FAILURE_MESSAGE_MAX_CHARS) -> str:
    """Collapse one error message into a bounded single line."""
    collapsed = " ".join(str(text).split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[:limit] + "..."


class LLMRequestFailureLog:
    """Collect the consecutive failures of one logical LLM request."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        """Start one empty record for a single request."""
        self._clock = clock
        self.started_at = clock()
        self.operation_id = ""
        self.outcome = "unknown"
        self.failures: list[dict] = []
        # Counters stay exact even when the recorded detail list hits its cap,
        # so the report never under-reports how many attempts actually failed.
        self.failed_attempts = 0
        self.last_failed_attempt = 0
        self.dropped_failures = 0

    def bind_operation(self, operation_id: str) -> None:
        """Adopt the request operation id so the report correlates with hooks."""
        self.operation_id = operation_id or ""

    def record_failure(
        self,
        attempt_number: int,
        error: BaseException,
        duration_sec: Optional[float] = None,
    ) -> None:
        """Record one failed attempt of this request."""
        # Exact counters are updated first so a capped detail list cannot make
        # the report claim fewer failures than actually happened.
        self.failed_attempts += 1
        self.last_failed_attempt = attempt_number
        if len(self.failures) >= MAX_RECORDED_FAILURES:
            self.dropped_failures += 1
            return
        self.failures.append({
            "attempt": attempt_number,
            "error": type(error).__name__,
            # The report schema has no nullable number, so an unknown duration
            # is recorded as zero instead of inventing a measurement.
            "duration_sec": 0.0 if duration_sec is None else round(float(duration_sec), 3),
            "message": _one_line(error),
        })

    def mark_outcome(self, outcome: str) -> None:
        """Record how the request ended: ``success``, ``failed`` or ``aborted``."""
        self.outcome = outcome

    def has_failures(self) -> bool:
        """Return whether this request recorded at least one failure."""
        return self.failed_attempts > 0

    def build_report(self) -> dict:
        """Return the detached data-only report payload of this request."""
        elapsed = round(max(0.0, self._clock() - self.started_at), 3)
        return {
            "schema_version": 1,
            "operation_id": self.operation_id,
            "outcome": self.outcome,
            "failed_attempts": self.failed_attempts,
            "last_failed_attempt": self.last_failed_attempt,
            "elapsed_sec": elapsed,
            "dropped_failures": self.dropped_failures,
            "failures": [dict(failure) for failure in self.failures],
        }

    def report(self) -> None:
        """Dispatch the report once, only when failures were recorded."""
        if not self.has_failures():
            return
        hook__aibase__after__llm_request_failures(**self.build_report())


def current_llm_request_failure_log() -> Optional[LLMRequestFailureLog]:
    """Return the record of the request running in this execution context."""
    return _active_request_failure_log.get()


def bind_llm_request_operation(operation_id: str) -> None:
    """Attach the current request's operation id to its active record."""
    record = current_llm_request_failure_log()
    if record is not None:
        record.bind_operation(operation_id)


def record_llm_request_failure(
    attempt_number: int,
    error: BaseException,
    duration_sec: Optional[float] = None,
) -> None:
    """Record one failed attempt on the active request record, when present."""
    record = current_llm_request_failure_log()
    if record is not None:
        record.record_failure(attempt_number, error, duration_sec)


def log_llm_request_failures(method):
    """Record and report the failures of one complete LLM chat request.

    The record lives for exactly one ``chat()`` call: it is created before the
    retry loop starts, reported once when the request exits, and dropped
    afterwards. Reporting never replaces the original exception.
    """
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        record = LLMRequestFailureLog()
        token = _active_request_failure_log.set(record)
        try:
            result = method(self, *args, **kwargs)
        except BaseException as error:
            record.mark_outcome(
                "aborted" if isinstance(error, (KeyboardInterrupt, SystemExit))
                else "failed"
            )
            raise
        else:
            record.mark_outcome("success")
            return result
        finally:
            _active_request_failure_log.reset(token)
            _report_without_masking(record)

    return wrapper


def _report_without_masking(record: LLMRequestFailureLog) -> None:
    """Report once, letting host control flow through but nothing else."""
    try:
        record.report()
    except (KeyboardInterrupt, SystemExit):
        raise
    except BaseException as report_error:  # noqa: BLE001 - never mask the request
        logger.warning("failed to report LLM request failures: %s", report_error)
