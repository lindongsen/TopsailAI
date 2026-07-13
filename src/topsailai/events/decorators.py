"""Event decorators for common agent operations."""

from __future__ import annotations

import functools
import json
import time
from typing import Any, Callable, Optional

from topsailai.events.collector import get_event_collector


def _safe_result(result: Any, max_bytes: int = 10000) -> Any:
    """Return the result if small, otherwise a truncated string marker."""
    try:
        text = json.dumps(result, ensure_ascii=False, default=str)
    except Exception:
        text = str(result)
    encoded = text.encode("utf-8")
    if len(encoded) > max_bytes:
        truncated = encoded[:max_bytes].decode("utf-8", errors="ignore")
        return f"{truncated}...[truncated, original {len(text)} chars]"
    return result


def record_tool_call_events(
    func=None, *, collector=None, tool_name: Optional[str] = None, flush: bool = False
):
    """Decorator that records tool_call.start and tool_call.end events."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)

            effective_tool_name = tool_name
            if effective_tool_name is None:
                effective_tool_name = kwargs.get("tool_name") or getattr(
                    func, "__name__", None
                )
            if not effective_tool_name:
                effective_tool_name = "unknown_tool"

            # The wrapped function (exec_tool_func) receives the tool args as
            # the positional ``args`` parameter or as the keyword ``args``.
            tool_args = kwargs.get("args")
            if tool_args is None and len(args) >= 2:
                tool_args = args[1]
            if tool_args is None:
                tool_args = {}

            coll.record(
                "tool_call.start",
                {"tool_name": effective_tool_name, "args": tool_args},
                flush=flush,
            )
            start_time = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                duration_ms = (time.perf_counter() - start_time) * 1000
                coll.record(
                    "tool_call.end",
                    {
                        "tool_name": effective_tool_name,
                        "args": tool_args,
                        "success": True,
                        "result": _safe_result(result),
                        "duration_ms": duration_ms,
                        "error_type": None,
                    },
                    flush=flush,
                )
                return result
            except Exception as exc:
                duration_ms = (time.perf_counter() - start_time) * 1000
                coll.record(
                    "tool_call.end",
                    {
                        "tool_name": effective_tool_name,
                        "args": tool_args,
                        "success": False,
                        "error": str(exc),
                        "error_type": type(exc).__name__,
                        "duration_ms": duration_ms,
                    },
                    flush=flush,
                )
                raise

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def record_approval_events(func=None, *, collector=None, flush: bool = False):
    """Decorator that records a tool_approval.decision event."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)
            decision = func(*args, **kwargs)
            coll.record("tool_approval.decision", {"decision": decision}, flush=flush)
            return decision

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def record_llm_chat_events(func=None, *, collector=None, flush: bool = False):
    """Decorator that records llm.request.start and llm.response.* events."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)
            coll.record("llm.request.start", {}, flush=flush)
            try:
                result = func(*args, **kwargs)
                coll.record("llm.response.success", {"result": result}, flush=flush)
                return result
            except Exception as exc:
                coll.record("llm.response.error", {"error": str(exc)}, flush=flush)
                raise

        return wrapper

    if func is None:
        return decorator
    return decorator(func)
