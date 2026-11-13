'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-11-13
  Purpose: Record bounded LLM request lifecycle events for the event channel.
'''

import logging
from typing import Any, Optional

from topsailai.events.collector import record_event


logger = logging.getLogger(__name__)


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
