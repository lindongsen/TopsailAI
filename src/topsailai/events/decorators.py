"""
Event-recording decorators for common agent operations.

These decorators are designed to be applied later to:
  - ai_base/agent_types/tool.py::exec_tool_func
  - ai_base/tool_approval/decorator.py::with_tool_approval
  - ai_base/llm_base.py::LLMModel.chat

They are intentionally not applied yet.
"""

from __future__ import annotations

import functools
import time
from typing import Any, Callable, Optional

from topsailai.events.collector import EventCollector, get_event_collector


def _resolve_collector(collector: Optional[EventCollector]) -> Optional[EventCollector]:
    """Return the provided collector or the module-level default."""
    if collector is not None:
        return collector
    return get_event_collector()


def _is_enabled(collector: Optional[EventCollector]) -> bool:
    """Return True when the collector exists and is enabled."""
    return collector is not None and getattr(collector, "enabled", True)


def record_tool_call_events(
    func: Callable | None = None,
    *,
    collector: Optional[EventCollector] = None,
    tool_name: str | None = None,
) -> Callable:
    """
    Record tool_call.start and tool_call.end events around a tool execution.

    Can be used with or without keyword arguments:
        @record_tool_call_events
        def exec_tool_func(...): ...

        @record_tool_call_events(tool_name="my_tool")
        def exec_tool_func(...): ...

    Payload fields:
      - tool_name: name of the invoked tool
      - args: tool arguments
      - success: True on success, False on error
      - result: returned value on success
      - error: exception message on failure
      - error_type: exception type name on failure
      - duration_ms: elapsed time in milliseconds
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = _resolve_collector(collector)
            resolved_tool_name = tool_name
            tool_args = kwargs.get("args")

            if resolved_tool_name is None:
                resolved_tool_name = kwargs.get("tool_name")
            if resolved_tool_name is None and len(args) > 2:
                resolved_tool_name = args[2]
            if tool_args is None and len(args) > 1:
                tool_args = args[1]

            enabled = _is_enabled(coll)
            start_payload = {
                "tool_name": resolved_tool_name,
                "args": tool_args,
            }
            if enabled:
                coll.record("tool_call.start", payload=start_payload)

            start_time = time.monotonic()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.monotonic() - start_time) * 1000)
                if enabled:
                    coll.record(
                        "tool_call.end",
                        payload={
                            "tool_name": resolved_tool_name,
                            "args": tool_args,
                            "success": True,
                            "result": _safe_result(result),
                            "duration_ms": duration_ms,
                        },
                    )
                return result
            except Exception as exc:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                if enabled:
                    coll.record(
                        "tool_call.end",
                        payload={
                            "tool_name": resolved_tool_name,
                            "args": tool_args,
                            "success": False,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                            "duration_ms": duration_ms,
                        },
                    )
                raise

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def record_approval_events(
    func: Callable | None = None,
    *,
    collector: Optional[EventCollector] = None,
) -> Callable:
    """
    Record tool_approval.decision events around a tool approval check.

    Payload fields:
      - tool_name: name of the tool being approved
      - args: tool arguments
      - decision: the decision object returned by the wrapped function, or
        {"action": "deny", "error": ...} when an exception is raised
      - approved: True when execution was allowed
      - denied: True when execution was denied
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = _resolve_collector(collector)
            tool_name = kwargs.get("tool_name")
            tool_args = kwargs.get("args")

            if tool_name is None and len(args) > 2:
                tool_name = args[2]
            if tool_args is None and len(args) > 1:
                tool_args = args[1]

            enabled = _is_enabled(coll)
            try:
                result = func(*args, **kwargs)
                decision = result if isinstance(result, dict) else {"action": "allow"}
                approved = decision.get("action") in ("allow", "approved", "yes")
                if enabled:
                    coll.record(
                        "tool_approval.decision",
                        payload={
                            "tool_name": tool_name,
                            "args": tool_args,
                            "decision": decision,
                            "approved": approved,
                            "denied": not approved,
                        },
                    )
                return result
            except Exception as exc:
                decision = {"action": "deny", "error": str(exc)}
                if enabled:
                    coll.record(
                        "tool_approval.decision",
                        payload={
                            "tool_name": tool_name,
                            "args": tool_args,
                            "decision": decision,
                            "approved": False,
                            "denied": True,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    )
                raise

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def record_llm_chat_events(
    func: Callable | None = None,
    *,
    collector: Optional[EventCollector] = None,
) -> Callable:
    """
    Record llm.request.start, llm.response.success, and llm.response.error events.

    Payload fields:
      - model: model name when available
      - messages_count: number of messages in the request
      - duration_ms: elapsed time
      - result_type: type name of the successful response
      - error: exception message on failure
      - error_type: exception type name
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            coll = _resolve_collector(collector)
            # args[0] is typically self (LLMModel instance).
            instance = args[0] if args else None
            model_name = kwargs.get("model")
            if model_name is None and instance is not None:
                model_name = getattr(instance, "model", None)
            messages = kwargs.get("messages")
            if messages is None and instance is not None:
                messages = getattr(instance, "messages", None)
            messages_count = len(messages) if isinstance(messages, list) else None

            enabled = _is_enabled(coll)
            start_payload = {
                "model": model_name,
                "messages_count": messages_count,
            }
            if enabled:
                coll.record("llm.request.start", payload=start_payload)

            start_time = time.monotonic()
            try:
                result = func(*args, **kwargs)
                duration_ms = int((time.monotonic() - start_time) * 1000)
                if enabled:
                    coll.record(
                        "llm.response.success",
                        payload={
                            "model": model_name,
                            "messages_count": messages_count,
                            "duration_ms": duration_ms,
                            "result_type": type(result).__name__,
                        },
                    )
                return result
            except Exception as exc:
                duration_ms = int((time.monotonic() - start_time) * 1000)
                if enabled:
                    coll.record(
                        "llm.response.error",
                        payload={
                            "model": model_name,
                            "messages_count": messages_count,
                            "duration_ms": duration_ms,
                            "error": str(exc),
                            "error_type": type(exc).__name__,
                        },
                    )
                raise

        return wrapper

    if func is not None:
        return decorator(func)
    return decorator


def _safe_result(result: Any) -> Any:
    """Return a JSON-serializable summary of a tool result."""
    if result is None:
        return None
    if isinstance(result, (str, int, float, bool, list, dict)):
        return result
    try:
        return str(result)
    except Exception:
        return "<unserializable result>"
