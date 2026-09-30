"""Bounded JSON framing for isolated hook worker communication."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from typing import Any

from topsailai.hooks.contracts import HookContext, HookEvent, JsonValue, ValidationError, _thaw_frozen_json
from topsailai.hooks.validation import freeze_json

_FRAME_HEADER = struct.Struct("!I")
PROTOCOL_VERSION = 1


@dataclass(frozen=True, slots=True)
class ProtocolLimits:
    """Bound request and response frame sizes."""

    request_bytes: int = 131_072
    response_bytes: int = 65_536

    def __post_init__(self) -> None:
        """Reject invalid limits before allocating buffers."""
        if type(self.request_bytes) is not int or self.request_bytes <= 0:
            raise ValueError("request_bytes must be a positive integer")
        if type(self.response_bytes) is not int or self.response_bytes <= 0:
            raise ValueError("response_bytes must be a positive integer")


def encode_frame(value: Any, max_bytes: int) -> bytes:
    """Encode one exact built-in JSON object into a bounded length-prefixed frame."""
    detached = freeze_json(value, max_bytes=max_bytes)
    if type(detached) is not dict:
        raise ValidationError("protocol frame must be a JSON object")
    encoded = json.dumps(detached, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode(
        "utf-8"
    )
    if len(encoded) > max_bytes:
        raise ValidationError("protocol frame exceeds maximum encoded size")
    return _FRAME_HEADER.pack(len(encoded)) + encoded


def decode_frame(frame: bytes, max_bytes: int) -> dict[str, JsonValue]:
    """Decode one complete bounded frame and reject trailing or malformed bytes."""
    if type(frame) is not bytes or len(frame) < _FRAME_HEADER.size:
        raise ValidationError("protocol frame is incomplete")
    (size,) = _FRAME_HEADER.unpack(frame[: _FRAME_HEADER.size])
    if size > max_bytes:
        raise ValidationError("protocol frame exceeds maximum encoded size")
    if len(frame) != _FRAME_HEADER.size + size:
        raise ValidationError("protocol frame length is invalid")
    try:
        value = json.loads(frame[_FRAME_HEADER.size :].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ValidationError("protocol frame contains invalid JSON") from exc
    detached = freeze_json(value, max_bytes=max_bytes)
    if type(detached) is not dict:
        raise ValidationError("protocol frame must be a JSON object")
    return detached


def expected_frame_size(buffer: bytes, max_bytes: int) -> int | None:
    """Return total frame bytes once a valid bounded header is available."""
    if len(buffer) < _FRAME_HEADER.size:
        return None
    (size,) = _FRAME_HEADER.unpack(buffer[: _FRAME_HEADER.size])
    if size > max_bytes:
        raise ValidationError("protocol frame exceeds maximum encoded size")
    return _FRAME_HEADER.size + size


def build_request(
    *, correlation_id: str, channel_token: str, handler_ref: str, context: HookContext
) -> dict[str, JsonValue]:
    """Build the detached worker request envelope."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "correlation_id": correlation_id,
        "channel_token": channel_token,
        "handler_ref": handler_ref,
        "context": {
            "event": {
                "event_id": context.event.event_id,
                "name": context.event.name,
                "major_version": context.event.major_version,
                "owner_id": context.event.owner_id,
                "scope_id": context.event.scope_id,
                "operation_id": context.event.operation_id,
                "parent_operation_id": context.event.parent_operation_id,
                "sequence": context.event.sequence,
                "timestamp": context.event.timestamp,
                "layer": context.event.layer,
                "purpose": context.event.purpose,
                "payload": _thaw_frozen_json(context.event.payload),
            },
            "delivery_id": context.delivery_id,
            "binding_id": context.binding_id,
            "registry_generation": context.registry_generation,
            "remaining_budget_ms": context.remaining_budget_ms,
            "origin": context.origin,
            "depth": context.depth,
        },
    }


def parse_request(value: Any) -> tuple[str, str, str, HookContext]:
    """Validate a worker request and reconstruct its immutable context."""
    if type(value) is not dict:
        raise ValidationError("worker request must be an object")
    required = {"protocol_version", "correlation_id", "channel_token", "handler_ref", "context"}
    if set(value) != required or value["protocol_version"] != PROTOCOL_VERSION:
        raise ValidationError("worker request envelope is invalid")
    correlation_id = _required_text(value["correlation_id"], "correlation_id")
    channel_token = _required_text(value["channel_token"], "channel_token")
    handler_ref = _required_text(value["handler_ref"], "handler_ref")
    raw_context = value["context"]
    if type(raw_context) is not dict:
        raise ValidationError("worker context must be an object")
    context_keys = {
        "event",
        "delivery_id",
        "binding_id",
        "registry_generation",
        "remaining_budget_ms",
        "origin",
        "depth",
    }
    if set(raw_context) != context_keys or type(raw_context["event"]) is not dict:
        raise ValidationError("worker context envelope is invalid")
    event_data = raw_context["event"]
    event_keys = {
        "event_id", "name", "major_version", "owner_id", "scope_id", "operation_id",
        "parent_operation_id", "sequence", "timestamp", "layer", "purpose", "payload",
    }
    if set(event_data) != event_keys:
        raise ValidationError("worker event envelope is invalid")
    try:
        event = HookEvent(**event_data)
        context = HookContext(
            event=event,
            delivery_id=_required_text(raw_context["delivery_id"], "delivery_id"),
            binding_id=_required_text(raw_context["binding_id"], "binding_id"),
            registry_generation=_required_non_negative_int(
                raw_context["registry_generation"], "registry_generation"
            ),
            remaining_budget_ms=_required_non_negative_int(
                raw_context["remaining_budget_ms"], "remaining_budget_ms"
            ),
            origin=_required_text(raw_context["origin"], "origin"),
            depth=_required_non_negative_int(raw_context["depth"], "depth"),
        )
    except TypeError as exc:
        raise ValidationError("worker context fields are invalid") from exc
    return correlation_id, channel_token, handler_ref, context


def validate_response(
    value: Any, *, correlation_id: str, channel_token: str, delivery_id: str
) -> dict[str, JsonValue]:
    """Validate correlation and the bounded terminal worker response."""
    if type(value) is not dict:
        raise ValidationError("worker response must be an object")
    required = {
        "protocol_version", "correlation_id", "channel_token", "delivery_id", "status",
        "value", "error_category",
    }
    if set(value) != required or value.get("protocol_version") != PROTOCOL_VERSION:
        raise ValidationError("worker response envelope is invalid")
    if value.get("correlation_id") != correlation_id:
        raise ValidationError("worker response correlation mismatch")
    if value.get("channel_token") != channel_token:
        raise ValidationError("worker response channel mismatch")
    if value.get("delivery_id") != delivery_id:
        raise ValidationError("worker response delivery mismatch")
    if value.get("status") not in ("success", "error", "invalid_output"):
        raise ValidationError("worker response status is invalid")
    error_category = value.get("error_category")
    if error_category is not None and type(error_category) is not str:
        raise ValidationError("worker error category is invalid")
    return value


def _required_text(value: Any, name: str) -> str:
    """Return a non-empty exact string field."""
    if type(value) is not str or not value:
        raise ValidationError(f"{name} must be a non-empty string")
    return value


def _required_non_negative_int(value: Any, name: str) -> int:
    """Return a non-negative exact integer field."""
    if type(value) is not int or value < 0:
        raise ValidationError(f"{name} must be a non-negative integer")
    return value
