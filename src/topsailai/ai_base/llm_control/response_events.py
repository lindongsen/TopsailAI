"""Deterministic response-event payload truncation.

This module owns the pure payload-size/truncation helper used to bound the
serialized size of an LLM response event. It is intentionally provider-neutral
and side-effect free: it does not import OpenAI, HTTPX, HTTPCore, or the events
subsystem. ``LLMModel`` remains responsible for response adaptation and for
orchestrating ``record_event()``.
"""

import json


def truncate_event_payload(payload, max_bytes):
    """Truncate an event payload so its JSON representation fits ``max_bytes``.

    Truncation is applied defensively without mutating caller state: the
    payload is copied before any modification. Large ``raw_response`` and
    ``content`` fields are reduced first; if the payload is still too large,
    a minimal fallback record is returned.
    """
    try:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
    except Exception:
        return {"_error": "payload not serializable"}

    if len(data.encode("utf-8")) <= max_bytes:
        return payload

    # Copy so the caller's dict is never mutated.
    payload = dict(payload)

    # First drop the raw response, which is usually the largest part.
    if "raw_response" in payload:
        payload["raw_response"] = {"_truncated": True}
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(data.encode("utf-8")) <= max_bytes:
            return payload

    # Then truncate textual content.
    if isinstance(payload.get("content"), str):
        payload["content"] = payload["content"][: max_bytes // 10]
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(data.encode("utf-8")) <= max_bytes:
            return payload

    # Then truncate tool-call arguments.
    if payload.get("tool_calls"):
        payload["tool_calls"] = [
            dict(tc) for tc in payload["tool_calls"]
        ]
        for tc in payload["tool_calls"]:
            func = dict(tc.get("function") or {})
            if isinstance(func.get("arguments"), str):
                func["arguments"] = func["arguments"][: max_bytes // 10]
            tc["function"] = func
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)
        if len(data.encode("utf-8")) <= max_bytes:
            return payload

    # Final fallback: keep only safe metadata.
    return {
        "_truncated": True,
        "model": payload.get("model"),
        "is_stream": payload.get("is_stream"),
        "content_length": len(payload.get("content", "") or ""),
        "tool_call_count": len(payload.get("tool_calls") or []),
    }


class LLMResponseEventMixin:
    """Build and record provider-neutral LLM response event payloads."""

    def _record_llm_response_event(
        self,
        response,
        is_stream=False,
        sampled_chunks=None,
        *,
        enabled=True,
        max_payload_bytes=100000,
        include_raw=True,
        recorder=None,
    ):
        """Safely build, truncate, and dispatch one LLM response event."""
        if not enabled or recorder is None:
            return

        try:
            message = self._get_llm_response_event_message(response)
            content = getattr(message, "content", None) or ""
            payload = {
                "model": self._get_llm_response_event_model_name(),
                "is_stream": is_stream,
                "content": content,
                "tool_calls": self._serialize_llm_response_event_tool_calls(message),
            }

            if include_raw:
                payload["raw_response"] = self._serialize_llm_response_event_raw(
                    response
                )
            if sampled_chunks:
                payload["sampled_chunks"] = sampled_chunks

            recorder(self._truncate_event_payload(payload, max_payload_bytes))
        except Exception:
            # Observability must never interrupt an LLM request.
            pass

    def _truncate_event_payload(self, payload, max_bytes):
        """Return a bounded response-event payload."""
        return truncate_event_payload(payload, max_bytes)

    def _get_llm_response_event_message(self, response):
        """Return the provider response message used by event serialization."""
        raise NotImplementedError

    def _get_llm_response_event_model_name(self):
        """Return the model identifier included in response event payloads."""
        raise NotImplementedError

    @staticmethod
    def _serialize_llm_response_event_tool_calls(message):
        """Convert provider tool-call objects into JSON-compatible mappings."""
        raw_tool_calls = getattr(message, "tool_calls", None)
        if not raw_tool_calls:
            return None

        tool_calls = []
        for tool_call in raw_tool_calls:
            function = getattr(tool_call, "function", None)
            tool_calls.append({
                "id": getattr(tool_call, "id", None),
                "type": getattr(tool_call, "type", "function"),
                "function": {
                    "name": getattr(function, "name", None) if function else None,
                    "arguments": (
                        getattr(function, "arguments", None) if function else None
                    ),
                },
            })
        return tool_calls

    @staticmethod
    def _serialize_llm_response_event_raw(response):
        """Convert a provider response into a safely representable raw value."""
        try:
            if hasattr(response, "to_dict"):
                return response.to_dict()
            if hasattr(response, "model_dump"):
                return response.model_dump()
            return {"_repr": repr(response)}
        except Exception:
            return {"_error": "failed to serialize raw response"}
