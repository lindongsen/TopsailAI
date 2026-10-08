"""Bounded JSON protocol for framework-owned hook scripts."""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass
from typing import Any

from topsailai.hooks.contracts import (
    HookContext,
    HookEvent,
    JsonValue,
    ValidationError,
    _thaw_frozen_json,
)
from topsailai.hooks.validation import freeze_json

PROTOCOL_VERSION = 1
_FRAME_HEADER = struct.Struct("!I")
_INVOCATION_ID = re.compile(r"^[0-9a-f]{32}$")
_INPUT_KEYS = frozenset(
    {"protocol_version", "delivery_id", "invocation_id", "entry_index", "context"}
)
_RESULT_KEYS = frozenset(
    {"protocol_version", "delivery_id", "invocation_id", "entry_index", "value"}
)
_CONTEXT_KEYS = frozenset(
    {
        "event",
        "delivery_id",
        "binding_id",
        "registry_generation",
        "remaining_budget_ms",
        "origin",
        "depth",
    }
)
_EVENT_KEYS = frozenset(
    {
        "event_id",
        "name",
        "major_version",
        "owner_id",
        "scope_id",
        "operation_id",
        "parent_operation_id",
        "sequence",
        "timestamp",
        "layer",
        "purpose",
        "payload",
    }
)


@dataclass(frozen=True, slots=True)
class ScriptResult:
    """Return one validated result and its observed framed byte count."""

    value: JsonValue
    observed_bytes: int


class ScriptProtocolError(ValidationError):
    """Report a stable script-protocol failure without exposing input data."""

    def __init__(self, category: str) -> None:
        """Store and expose only the stable protocol category."""
        self.category = category
        super().__init__(category)


def encode_script_input(
    *,
    context: HookContext,
    invocation_id: str,
    entry_index: int,
    max_bytes: int,
) -> bytes:
    """Encode one detached plain-JSON stdin envelope to be followed by EOF."""
    _validate_limit(max_bytes)
    if type(context) is not HookContext or type(context.event) is not HookEvent:
        raise ScriptProtocolError("invalid_input")
    _validate_identity(
        context.delivery_id, invocation_id, entry_index, category="invalid_input"
    )
    context_value = _context_mapping(context)
    _validate_context_mapping(context_value)
    envelope: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "delivery_id": context.delivery_id,
        "invocation_id": invocation_id,
        "entry_index": entry_index,
        "context": context_value,
    }
    try:
        detached = freeze_json(envelope, max_bytes=max_bytes)
        encoded = _canonical_json(detached)
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_input") from exc
    if len(encoded) > max_bytes:
        raise ScriptProtocolError("input_limit")
    return encoded


def encode_script_result(
    *,
    delivery_id: str,
    invocation_id: str,
    entry_index: int,
    value: Any,
    result_limit_bytes: int,
) -> bytes:
    """Encode one correlated result as a bounded length-prefixed frame."""
    _validate_limit(result_limit_bytes)
    _validate_identity(delivery_id, invocation_id, entry_index)
    result_value = _freeze_result_value(value)
    envelope = _result_envelope(delivery_id, invocation_id, entry_index, result_value)
    try:
        body = _canonical_json(envelope)
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_result") from exc
    if not 1 <= len(body) <= result_limit_bytes:
        raise ScriptProtocolError("result_limit")
    return _FRAME_HEADER.pack(len(body)) + body


def decode_script_result(
    data: bytes,
    *,
    delivery_id: str,
    invocation_id: str,
    entry_index: int,
    result_limit_bytes: int,
) -> ScriptResult:
    """Validate exactly one correlated result frame followed by EOF."""
    _validate_limit(result_limit_bytes)
    _validate_identity(delivery_id, invocation_id, entry_index)
    if type(data) is not bytes:
        raise ScriptProtocolError("invalid_result")
    if not data:
        raise ScriptProtocolError("missing_result")
    if len(data) < _FRAME_HEADER.size:
        raise ScriptProtocolError("invalid_result")
    (body_size,) = _FRAME_HEADER.unpack(data[: _FRAME_HEADER.size])
    if not 1 <= body_size <= result_limit_bytes:
        raise ScriptProtocolError("result_limit")
    expected_size = _FRAME_HEADER.size + body_size
    if len(data) != expected_size:
        raise ScriptProtocolError("invalid_result")
    body = data[_FRAME_HEADER.size:]
    value = _decode_json_object(body)
    if (
        set(value) != _RESULT_KEYS
        or type(value.get("protocol_version")) is not int
        or value["protocol_version"] != PROTOCOL_VERSION
    ):
        raise ScriptProtocolError("invalid_result")
    if (
        value.get("delivery_id") != delivery_id
        or value.get("invocation_id") != invocation_id
        or type(value.get("entry_index")) is not int
        or value.get("entry_index") != entry_index
    ):
        raise ScriptProtocolError("result_identity_mismatch")
    result = _freeze_result_value(value["value"])
    canonical_envelope = _result_envelope(
        delivery_id, invocation_id, entry_index, result
    )
    try:
        canonical_body = _canonical_json(canonical_envelope)
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_result") from exc
    if len(canonical_body) > result_limit_bytes:
        raise ScriptProtocolError("result_limit")
    return ScriptResult(result, expected_size)


def decode_script_input(data: bytes, *, max_bytes: int) -> dict[str, JsonValue]:
    """Decode a complete stdin envelope for native script implementations."""
    _validate_limit(max_bytes)
    if type(data) is not bytes or not data or len(data) > max_bytes:
        raise ScriptProtocolError("invalid_input")
    value = _decode_json_object(data, category="invalid_input")
    if (
        set(value) != _INPUT_KEYS
        or type(value.get("protocol_version")) is not int
        or value["protocol_version"] != PROTOCOL_VERSION
    ):
        raise ScriptProtocolError("invalid_input")
    delivery_id = value.get("delivery_id")
    invocation_id = value.get("invocation_id")
    entry_index = value.get("entry_index")
    _validate_identity(delivery_id, invocation_id, entry_index, category="invalid_input")
    context = value.get("context")
    _validate_context_mapping(context)
    if context.get("delivery_id") != delivery_id:
        raise ScriptProtocolError("input_identity_mismatch")
    try:
        return freeze_json(value, max_bytes=max_bytes)
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_input") from exc


def _context_mapping(context: HookContext) -> dict[str, Any]:
    """Build the exact detached context mapping."""
    event = context.event
    return {
        "event": {
            "event_id": event.event_id,
            "name": event.name,
            "major_version": event.major_version,
            "owner_id": event.owner_id,
            "scope_id": event.scope_id,
            "operation_id": event.operation_id,
            "parent_operation_id": event.parent_operation_id,
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "layer": event.layer,
            "purpose": event.purpose,
            "payload": _thaw_frozen_json(event.payload),
        },
        "delivery_id": context.delivery_id,
        "binding_id": context.binding_id,
        "registry_generation": context.registry_generation,
        "remaining_budget_ms": context.remaining_budget_ms,
        "origin": context.origin,
        "depth": context.depth,
    }


def _decode_json_object(data: bytes, *, category: str = "invalid_result") -> dict[str, Any]:
    """Decode strict UTF-8 JSON while rejecting duplicate object members."""
    if data.startswith(b"\xef\xbb\xbf"):
        raise ScriptProtocolError(category)

    def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise ScriptProtocolError(category)
            result[key] = item
        return result

    def reject_constant(_: str) -> None:
        raise ScriptProtocolError(category)

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except ScriptProtocolError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError, ValueError) as exc:
        raise ScriptProtocolError(category) from exc
    if type(value) is not dict:
        raise ScriptProtocolError(category)
    return value


def _validate_identity(
    delivery_id: Any,
    invocation_id: Any,
    entry_index: Any,
    *,
    category: str = "invalid_identity",
) -> None:
    """Validate exact invocation correlation field types and values."""
    if type(delivery_id) is not str or not delivery_id:
        raise ScriptProtocolError(category)
    if type(invocation_id) is not str or not _INVOCATION_ID.fullmatch(invocation_id):
        raise ScriptProtocolError(category)
    if type(entry_index) is not int or entry_index < 0:
        raise ScriptProtocolError(category)


def _validate_context_mapping(context: Any) -> None:
    """Validate the exact context and event schema used by both codec directions."""
    if type(context) is not dict or set(context) != _CONTEXT_KEYS:
        raise ScriptProtocolError("invalid_input")
    event = context.get("event")
    if type(event) is not dict or set(event) != _EVENT_KEYS:
        raise ScriptProtocolError("invalid_input")
    text_fields = ("delivery_id", "binding_id", "origin")
    int_fields = ("registry_generation", "remaining_budget_ms", "depth")
    if any(type(context.get(name)) is not str or not context[name] for name in text_fields):
        raise ScriptProtocolError("invalid_input")
    if any(type(context.get(name)) is not int or context[name] < 0 for name in int_fields):
        raise ScriptProtocolError("invalid_input")
    event_text = (
        "event_id", "name", "owner_id", "scope_id", "operation_id", "timestamp", "layer", "purpose"
    )
    if any(type(event.get(name)) is not str for name in event_text):
        raise ScriptProtocolError("invalid_input")
    if event.get("parent_operation_id") is not None and type(event["parent_operation_id"]) is not str:
        raise ScriptProtocolError("invalid_input")
    if type(event.get("major_version")) is not int or event["major_version"] <= 0:
        raise ScriptProtocolError("invalid_input")
    if type(event.get("sequence")) is not int or event["sequence"] < 0:
        raise ScriptProtocolError("invalid_input")
    try:
        freeze_json(event.get("payload"))
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_input") from exc


def _result_envelope(
    delivery_id: str,
    invocation_id: str,
    entry_index: int,
    value: JsonValue,
) -> dict[str, Any]:
    """Build the exact canonical result envelope."""
    return {
        "protocol_version": PROTOCOL_VERSION,
        "delivery_id": delivery_id,
        "invocation_id": invocation_id,
        "entry_index": entry_index,
        "value": value,
    }


def _freeze_result_value(value: Any) -> JsonValue:
    """Validate and detach a result value under the shared C03 JSON limits."""
    try:
        return freeze_json(value, max_bytes=1_048_576)
    except ValidationError as exc:
        raise ScriptProtocolError("invalid_result") from exc


def _validate_limit(value: Any) -> None:
    """Validate one exact positive v1 byte limit."""
    if type(value) is not int or not 1 <= value <= 1_048_576:
        raise ScriptProtocolError("invalid_limit")


def _canonical_json(value: Any) -> bytes:
    """Encode strict canonical compact UTF-8 JSON."""
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError, OverflowError) as exc:
        raise ValidationError("JSON value cannot be encoded safely") from exc
