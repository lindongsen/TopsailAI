"""Event decorators for common agent operations."""

from __future__ import annotations

import functools
from typing import Callable, Optional

from topsailai.events.collector import get_event_collector


def record_tool_call_events(func=None, *, collector=None, tool_name: Optional[str] = None):
    """Decorator that records tool_call.start and tool_call.end events."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)
            effective_tool_name = tool_name or getattr(func, "__name__", None) or "unknown_tool"
            coll.record(
                "tool_call.start",
                {"tool_name": effective_tool_name, "args": {"args": list(args), "kwargs": kwargs}},
            )
            try:
                result = func(*args, **kwargs)
                coll.record(
                    "tool_call.end",
                    {"tool_name": effective_tool_name, "success": True, "result": result},
                )
                return result
            except Exception as exc:
                coll.record(
                    "tool_call.end",
                    {"tool_name": effective_tool_name, "success": False, "error": str(exc)},
                )
                raise

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def record_approval_events(func=None, *, collector=None):
    """Decorator that records a tool_approval.decision event."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)
            decision = func(*args, **kwargs)
            coll.record("tool_approval.decision", {"decision": decision})
            return decision

        return wrapper

    if func is None:
        return decorator
    return decorator(func)


def record_llm_chat_events(func=None, *, collector=None):
    """Decorator that records llm.request.start and llm.response.* events."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = collector if collector is not None else get_event_collector()
            if not getattr(coll, "enabled", True):
                return func(*args, **kwargs)
            coll.record("llm.request.start", {})
            try:
                result = func(*args, **kwargs)
                coll.record("llm.response.success", {"result": result})
                return result
            except Exception as exc:
                coll.record("llm.response.error", {"error": str(exc)})
                raise

        return wrapper

    if func is None:
        return decorator
    return decorator(func)
