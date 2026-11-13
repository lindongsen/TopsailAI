'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-13
  Purpose: Record bounded LLM request lifecycle events for the event channel.
'''

import contextvars
from dataclasses import dataclass
import functools
import logging
import time
from typing import Any, Optional

from topsailai.events.collector import record_event


logger = logging.getLogger(__name__)


@dataclass
class _RequestEventLifecycle:
    """Track one logical request so every emitted start has one terminal end."""

    operation_id: str = ""
    model_name: str = ""
    attempt_count: int = 0
    started_at: float = 0.0
    started: bool = False
    ended: bool = False


_active_request_event_lifecycle = contextvars.ContextVar(
    "topsailai_llm_request_event_lifecycle", default=None
)


def _observe_lifecycle_event(event_type: str, payload: dict) -> bool:
    """Update lifecycle ownership and reject a duplicate terminal event."""
    state = _active_request_event_lifecycle.get()
    if state is None:
        return True
    if event_type == "llm.request.start":
        state.operation_id = str(payload.get("operation_id") or "")
        state.model_name = str(payload.get("model_name") or "")
        state.started_at = time.monotonic()
        state.started = True
        return True
    if event_type != "llm.request.end" or not state.started:
        return True
    if str(payload.get("operation_id") or "") != state.operation_id:
        return True
    if state.ended:
        return False
    state.ended = True
    return True


def observe_llm_request_attempt(attempt_count: int) -> None:
    """Record the latest attempted request number for terminal fallback events."""
    state = _active_request_event_lifecycle.get()
    if state is None or not state.started or state.ended:
        return
    try:
        state.attempt_count = max(state.attempt_count, int(attempt_count))
    except (TypeError, ValueError):
        return


def _terminal_outcome(error: BaseException) -> str:
    """Map an unchanged request exception to its public terminal category."""
    category = type(error).__name__
    if category in ("HardInterruptError", "KeyboardInterrupt"):
        return "interrupted"
    if category == "LLMBackToChatError":
        return "abandoned"
    if category == "LLMRetryExhaustedError":
        return "exhausted"
    return "failed"


def _settle_lifecycle(state: _RequestEventLifecycle, error=None) -> None:
    """Best-effort publish one missing terminal event without masking outcomes."""
    if not state.started or state.ended:
        return
    outcome = "success" if error is None else _terminal_outcome(error)
    error_category = None if error is None else type(error).__name__
    attempt_count = getattr(error, "attempts", state.attempt_count)
    try:
        payload = build_llm_request_end_payload(
            operation_id=state.operation_id,
            model_name=state.model_name,
            outcome=outcome,
            attempt_count=attempt_count,
            duration_sec=max(0.0, time.monotonic() - state.started_at),
            error_category=error_category,
        )
        record_llm_request_event("llm.request.end", payload)
    except BaseException:
        logger.warning(
            "LLM request lifecycle settlement failed category=%s",
            error_category or "success",
            exc_info=True,
        )


def track_llm_request_events(method):
    """Guarantee one terminal event after every start while preserving behavior."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        state = _RequestEventLifecycle()
        token = _active_request_event_lifecycle.set(state)
        try:
            result = method(self, *args, **kwargs)
        except BaseException as error:
            _settle_lifecycle(state, error)
            raise
        else:
            _settle_lifecycle(state)
            return result
        finally:
            _active_request_event_lifecycle.reset(token)

    return wrapper


def resolve_model_name(model: Any) -> str:
    """Resolve a model name without ever raising.

    Telemetry must not be able to break an LLM request, and a partially
    constructed model object may have neither the attribute nor a working
    resolver. Every lookup is therefore guarded and an empty string is the
    final fallback.

    Args:
        model: Object that may expose ``model_name`` or ``get_model_name()``.

    Returns:
        str: Resolved model name, or an empty string when unavailable.
    """
    try:
        name = getattr(model, "model_name", None)
        if name:
            return str(name)
    except Exception:
        pass
    try:
        resolver = getattr(model, "get_model_name", None)
        if callable(resolver):
            name = resolver()
            if name:
                return str(name)
    except Exception:
        pass
    return ""


def record_llm_request_event(event_type: str, payload: dict) -> None:
    """Record one LLM request lifecycle event.

    The event channel is fire-and-forget telemetry, so recording must never
    change the outcome of an LLM request: any failure is logged and swallowed
    and the caller keeps its original return value or exception.

    Payloads carry only bounded operational metadata. Message content, prompt
    text, tool arguments and response bodies are never included, because the
    event channel is not a transcript store.

    Args:
        event_type: Event type such as ``llm.request.start``.
        payload: Bounded operational fields.
    """
    try:
        if not _observe_lifecycle_event(event_type, payload):
            return
    except Exception:
        logger.warning(
            "llm request lifecycle observation failed event_type=%s",
            event_type,
            exc_info=True,
        )
    try:
        record_event(event_type, payload)
    except Exception:
        logger.warning(
            "llm request event recording failed event_type=%s",
            event_type,
            exc_info=True,
        )


def build_llm_request_start_payload(
    operation_id: str,
    model_name: Optional[str],
    messages: Any,
    stream: bool,
    return_mode: str,
) -> dict:
    """Build the bounded payload for an ``llm.request.start`` event.

    Args:
        operation_id: Identifier shared by every attempt of one logical request.
        model_name: Model name, or ``None`` when unavailable.
        messages: Request message list; only its length is recorded.
        stream: Whether the request uses streaming mode.
        return_mode: Requested return shape.

    Returns:
        dict: Bounded operational fields with no message content.
    """
    try:
        message_count = len(messages or [])
    except TypeError:
        message_count = 0
    return {
        "operation_id": operation_id,
        "model_name": model_name or "",
        "message_count": message_count,
        "stream": bool(stream),
        "return_mode": return_mode,
    }


def build_llm_request_end_payload(
    operation_id: str,
    model_name: Optional[str],
    outcome: str,
    attempt_count: int,
    duration_sec: float,
    error_category: Optional[str] = None,
) -> dict:
    """Build the bounded payload for an ``llm.request.end`` event.

    Args:
        operation_id: Identifier shared by every attempt of one logical request.
        model_name: Model name, or ``None`` when unavailable.
        outcome: Terminal outcome category such as ``success`` or ``exhausted``.
        attempt_count: Number of attempts consumed by this logical request.
        duration_sec: Wall-clock duration of the whole logical request.
        error_category: Exception class name for a failed request.

    Returns:
        dict: Bounded operational fields with no response content.
    """
    payload = {
        "operation_id": operation_id,
        "model_name": model_name or "",
        "outcome": outcome,
        "attempt_count": int(attempt_count),
        "duration_sec": round(float(duration_sec), 3),
    }
    if error_category:
        payload["error_category"] = str(error_category)[:128]
    return payload
