"""Per-request LLM failure recording.

One logical LLM chat request may retry the same provider call many times.
``LLMModel.chat()`` owns those retries, so the consecutive failures of a single
request are invisible once the request returns. This module records every
failed attempt inside that one request, prints one summary when the request
exits, and drops the record afterwards.

The module is provider-neutral and deliberately does not classify retries:
``LLMModel.chat()`` keeps the retry decision and only reports each failure.
"""

from __future__ import annotations

import contextvars
import functools
import time
from typing import Callable, Optional

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import print_with_time


# One request is bounded by the retry loop (18 attempts per cycle, at most 8
# cycles). The cap only protects against a future unbounded loop.
MAX_RECORDED_FAILURES = 200
# Keep one failure line readable; the complete error text stays in the attempt log.
FAILURE_MESSAGE_MAX_CHARS = 200
# Console output stays bounded; the logger always receives every failure.
CONSOLE_DETAIL_LIMIT = 5

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
        self.dropped_failures = 0

    def bind_operation(self, operation_id: str) -> None:
        """Adopt the request operation id so the summary correlates with hooks."""
        self.operation_id = operation_id or ""

    def record_failure(
        self,
        attempt_number: int,
        error: BaseException,
        duration_sec: Optional[float] = None,
    ) -> None:
        """Record one failed attempt of this request."""
        if len(self.failures) >= MAX_RECORDED_FAILURES:
            self.dropped_failures += 1
            return
        self.failures.append({
            "attempt": attempt_number,
            "error": type(error).__name__,
            "duration_sec": (
                None if duration_sec is None else round(float(duration_sec), 3)
            ),
            "message": _one_line(error),
        })

    def mark_outcome(self, outcome: str) -> None:
        """Record how the request ended: ``success``, ``failed`` or ``aborted``."""
        self.outcome = outcome

    def has_failures(self) -> bool:
        """Return whether this request recorded at least one failure."""
        return bool(self.failures)

    def _header(self) -> str:
        """Build the one-line summary shared by console and log output."""
        elapsed = round(max(0.0, self._clock() - self.started_at), 3)
        last_attempt = self.failures[-1]["attempt"] if self.failures else 0
        return (
            f"[LLMRequestFailureLog] operation_id={self.operation_id or 'null'} "
            f"outcome={self.outcome} failed_attempts={len(self.failures)} "
            f"last_failed_attempt={last_attempt} elapsed_sec={elapsed}"
        )

    def _detail_lines(self, limit: Optional[int]) -> list[str]:
        """Build per-failure lines, optionally bounded for console output."""
        entries = self.failures
        omitted = 0
        if limit is not None and len(entries) > limit * 2:
            omitted = len(entries) - limit * 2
            entries = entries[:limit] + entries[-limit:]
        lines = []
        for index, failure in enumerate(entries):
            if omitted and index == limit:
                lines.append(
                    f"[LLMRequestFailureLog]   ... {omitted} failure(s) omitted ..."
                )
            duration = failure["duration_sec"]
            lines.append(
                f"[LLMRequestFailureLog]   attempt={failure['attempt']} "
                f"error={failure['error']} "
                f"duration_sec={'null' if duration is None else duration} "
                f"message={failure['message']}"
            )
        if self.dropped_failures:
            lines.append(
                f"[LLMRequestFailureLog]   ... {self.dropped_failures} failure(s) "
                "not recorded ..."
            )
        return lines

    def format_summary(self, limit: Optional[int] = None, header: str = "") -> str:
        """Return the complete summary, or a bounded variant for the console."""
        return "\n".join([header or self._header()] + self._detail_lines(limit))

    def emit(self) -> None:
        """Print and log the summary once, only when failures were recorded."""
        if not self.has_failures():
            return
        # Build the header once so the console and the log cannot disagree on
        # the elapsed time of the same request.
        header = self._header()
        print_with_time(
            self.format_summary(CONSOLE_DETAIL_LIMIT, header),
            need_format=False,
            color_kind="warning",
        )
        logger.warning(self.format_summary(header=header))


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
            try:
                record.emit()
            except Exception as report_error:  # noqa: BLE001 - never mask the request
                logger.warning(
                    "failed to report LLM request failures: %s", report_error
                )

    return wrapper
