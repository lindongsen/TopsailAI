"""Trace-composition helpers for artifact ownership handoff tests."""

from __future__ import annotations

import sys
from contextlib import contextmanager
from typing import Callable, Iterator


def _combine_traces(first, second):
    """Compose two local trace callbacks without reviving a declined callback."""
    if first is None:
        return second
    if second is None:
        return first

    def combined(frame, event, argument):
        return _combine_traces(
            first(frame, event, argument), second(frame, event, argument)
        )

    return combined


@contextmanager
def composed_line_interruption(
    target_code,
    target_line: int,
    interruption: BaseException,
    *,
    before_interrupt: Callable[[], None] | None = None,
    traced_code=None,
    declined_code=None,
) -> Iterator[list[tuple[str, str]]]:
    """Own one target frame while preserving an installed global/local tracer."""
    runner_trace = sys.gettrace()
    sentinel_events: list[tuple[str, str]] = []

    def sentinel_local(frame, event, argument):
        sentinel_events.append((frame.f_code.co_name, event))
        return sentinel_local

    def sentinel_global(frame, event, argument):
        sentinel_events.append((frame.f_code.co_name, event))
        return sentinel_local if frame.f_code is traced_code else None

    def installed_original(frame, event, argument):
        runner_local = (
            runner_trace(frame, event, argument) if runner_trace is not None else None
        )
        return _combine_traces(runner_local, sentinel_global(frame, event, argument))

    sys.settrace(installed_original)
    original_trace = sys.gettrace()
    delegated: dict[int, object] = {}
    declined: set[int] = set()

    def interruption_trace(frame, event, argument):
        if frame.f_code is target_code:
            if event == "line" and frame.f_lineno == target_line:
                sys.settrace(original_trace)
                if before_interrupt is not None:
                    before_interrupt()
                raise interruption
            return interruption_trace
        frame_id = id(frame)
        if event == "call":
            delegate = original_trace(frame, event, argument)
            sys.settrace(interruption_trace)
            if delegate is None:
                declined.add(frame_id)
            else:
                delegated[frame_id] = delegate
        elif frame_id in delegated:
            delegate = delegated[frame_id]
            next_delegate = delegate(frame, event, argument)
            sys.settrace(interruption_trace)
            if next_delegate is None:
                delegated.pop(frame_id, None)
            else:
                delegated[frame_id] = next_delegate
        if event == "return":
            delegated.pop(frame_id, None)
        return interruption_trace

    sys.settrace(interruption_trace)
    try:
        yield sentinel_events
    finally:
        sys.settrace(runner_trace)
        assert sys.gettrace() is runner_trace
