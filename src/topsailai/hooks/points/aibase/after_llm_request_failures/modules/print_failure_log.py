"""Render one LLM request failure report. Author: DawsonLin."""

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import print_with_time

# Console output stays bounded; the logger always receives every failure.
CONSOLE_DETAIL_LIMIT = 5
_PREFIX = "[LLMRequestFailureLog]"


def main(**payload):
    """Print a bounded summary and log the complete one, only when failures exist."""
    failures = payload.get("failures") or []
    if not failures:
        return
    # Build the header once so the console and the log cannot disagree on the
    # elapsed time of the same request.
    header = _header(payload)
    print_with_time(
        _format(header, payload, CONSOLE_DETAIL_LIMIT),
        need_format=False,
        color_kind="warning",
    )
    logger.warning(_format(header, payload))


def _header(payload):
    """Build the one-line summary shared by console and log output."""
    operation_id = payload.get("operation_id") or "null"
    return (
        f"{_PREFIX} operation_id={operation_id} "
        f"outcome={payload.get('outcome')} "
        f"failed_attempts={payload.get('failed_attempts')} "
        f"last_failed_attempt={payload.get('last_failed_attempt')} "
        f"elapsed_sec={payload.get('elapsed_sec')}"
    )


def _format(header, payload, limit=None):
    """Return the complete summary, or a bounded variant for the console."""
    return "\n".join([header] + _detail_lines(payload, limit))


def _detail_lines(payload, limit):
    """Build per-failure lines, optionally bounded for console output."""
    entries = payload.get("failures") or []
    omitted = 0
    if limit is not None and len(entries) > limit * 2:
        omitted = len(entries) - limit * 2
        entries = entries[:limit] + entries[-limit:]
    lines = []
    for index, failure in enumerate(entries):
        if omitted and index == limit:
            lines.append(f"{_PREFIX}   ... {omitted} failure(s) omitted ...")
        lines.append(
            f"{_PREFIX}   attempt={failure['attempt']} "
            f"error={failure['error']} "
            f"duration_sec={failure['duration_sec']} "
            f"message={failure['message']}"
        )
    dropped = payload.get("dropped_failures") or 0
    if dropped:
        lines.append(f"{_PREFIX}   ... {dropped} failure(s) not recorded ...")
    return lines


__all__ = ["main", "CONSOLE_DETAIL_LIMIT"]
