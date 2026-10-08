"""Focused tests for the bounded hook-script wire protocol."""

from __future__ import annotations

import json
import struct
from dataclasses import replace

import pytest

from topsailai.hooks import HookContext, HookEvent
from topsailai.hooks.hook_script import HookScriptExecutionPolicy
from topsailai.hooks.script_protocol import (
    ScriptProtocolError,
    decode_script_input,
    decode_script_result,
    encode_script_input,
    encode_script_result,
)

_INVOCATION_ID = "0123456789abcdef0123456789abcdef"


def _context(payload: object = None) -> HookContext:
    """Build one valid detached script context."""
    event = HookEvent(
        "event-1",
        "conversation.started",
        1,
        "owner",
        "scope",
        "operation",
        None,
        1,
        "2026-10-03T00:00:00+00:00",
        "agent",
        "test",
        {} if payload is None else payload,
    )
    return HookContext(event, "delivery-1", "hook_script", 7, 800, "host", 0)


def _result_body(value: object, **overrides: object) -> bytes:
    """Build a raw result frame for strict-decoder tests."""
    envelope = {
        "protocol_version": 1,
        "delivery_id": "delivery-1",
        "invocation_id": _INVOCATION_ID,
        "entry_index": 2,
        "value": value,
    }
    envelope.update(overrides)
    body = json.dumps(envelope, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return struct.pack("!I", len(body)) + body


def test_input_round_trip_is_plain_json_eof_and_non_mutating() -> None:
    """Stdin uses plain detached JSON with exact correlation and no frame prefix."""
    source = {"nested": [None, False, 0, "", [], {}]}
    context = _context(source)
    encoded = encode_script_input(
        context=context,
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        max_bytes=65_536,
    )
    source["nested"].append("later")
    assert encoded.startswith(b"{")
    decoded = decode_script_input(encoded, max_bytes=65_536)
    assert decoded["delivery_id"] == decoded["context"]["delivery_id"] == "delivery-1"
    assert decoded["context"]["event"]["payload"] == {
        "nested": [None, False, 0, "", [], {}]
    }


@pytest.mark.parametrize("value", [None, False, 0, "", [], {}])
def test_result_round_trip_preserves_every_valid_empty_json_value(value: object) -> None:
    """Missing output remains distinguishable from every explicit JSON value."""
    encoded = encode_script_result(
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        value=value,
        result_limit_bytes=16_384,
    )
    result = decode_script_result(
        encoded,
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        result_limit_bytes=16_384,
    )
    assert result.value == value
    assert result.observed_bytes == len(encoded)


def test_unicode_result_limit_uses_utf8_bytes_at_exact_boundary() -> None:
    """The body limit is inclusive and counts encoded bytes rather than characters."""
    value = "界"
    frame = encode_script_result(
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        value=value,
        result_limit_bytes=16_384,
    )
    body_size = len(frame) - 4
    assert decode_script_result(
        frame,
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        result_limit_bytes=body_size,
    ).value == value
    with pytest.raises(ScriptProtocolError, match="result_limit"):
        decode_script_result(
            frame,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=body_size - 1,
        )


@pytest.mark.parametrize(
    ("data", "category"),
    [
        (b"", "missing_result"),
        (b"\x00\x00", "invalid_result"),
        (struct.pack("!I", 5) + b"{}", "invalid_result"),
        (_result_body(None) + b"x", "invalid_result"),
        (_result_body(None) + _result_body(False), "invalid_result"),
        (_result_body(None, delivery_id="wrong"), "result_identity_mismatch"),
        (_result_body(None, invocation_id="f" * 32), "result_identity_mismatch"),
        (_result_body(None, entry_index=3), "result_identity_mismatch"),
        (_result_body(None, protocol_version=2), "invalid_result"),
        (struct.pack("!I", 2) + b"\xff\xff", "invalid_result"),
        (struct.pack("!I", 5) + b"\xef\xbb\xbf{}", "invalid_result"),
    ],
)
def test_result_rejects_missing_partial_duplicate_trailing_and_wrong_identity(
    data: bytes, category: str
) -> None:
    """A result is exactly one valid correlated frame followed by EOF."""
    with pytest.raises(ScriptProtocolError, match=category):
        decode_script_result(
            data,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=16_384,
        )


def test_duplicate_unknown_nonfinite_and_overcomplex_results_are_rejected() -> None:
    """Strict decoding rejects ambiguous members and unsafe JSON shapes."""
    duplicate = (
        b'{"protocol_version":1,"delivery_id":"delivery-1",'
        b'"invocation_id":"' + _INVOCATION_ID.encode() + b'","entry_index":2,'
        b'"value":null,"value":false}'
    )
    samples = [
        duplicate,
        json.dumps({
            "protocol_version": 1,
            "delivery_id": "delivery-1",
            "invocation_id": _INVOCATION_ID,
            "entry_index": 2,
            "value": None,
            "extra": "SECRET_SENTINEL",
        }).encode(),
        (
            b'{"protocol_version":1,"delivery_id":"delivery-1",'
            b'"invocation_id":"' + _INVOCATION_ID.encode() + b'","entry_index":2,"value":NaN}'
        ),
    ]
    nested: object = None
    for _ in range(18):
        nested = [nested]
    samples.append(json.dumps({
        "protocol_version": 1,
        "delivery_id": "delivery-1",
        "invocation_id": _INVOCATION_ID,
        "entry_index": 2,
        "value": nested,
    }).encode())
    for body in samples:
        frame = struct.pack("!I", len(body)) + body
        with pytest.raises(ScriptProtocolError) as raised:
            decode_script_result(
                frame,
                delivery_id="delivery-1",
                invocation_id=_INVOCATION_ID,
                entry_index=2,
                result_limit_bytes=16_384,
            )
        assert "SECRET_SENTINEL" not in str(raised.value)


def test_input_rejects_duplicate_keys_delivery_mismatch_and_bom() -> None:
    """The native-side decoder enforces exact stdin schema and identity."""
    valid = encode_script_input(
        context=_context(), invocation_id=_INVOCATION_ID, entry_index=2, max_bytes=65_536
    )
    duplicate = valid[:-1] + b',"delivery_id":"delivery-1"}'
    decoded = json.loads(valid)
    decoded["context"]["delivery_id"] = "other"
    mismatch = json.dumps(decoded, separators=(",", ":")).encode("utf-8")
    for data in (duplicate, b"\xef\xbb\xbf" + valid):
        with pytest.raises(ScriptProtocolError, match="invalid_input"):
            decode_script_input(data, max_bytes=65_536)
    with pytest.raises(ScriptProtocolError, match="input_identity_mismatch"):
        decode_script_input(mismatch, max_bytes=65_536)


def test_exact_correlation_types_and_protocol_version_reject_bool() -> None:
    """Boolean integers and mismatched correlation never pass exact v1 checks."""
    input_envelope = json.loads(
        encode_script_input(
            context=_context(), invocation_id=_INVOCATION_ID, entry_index=2, max_bytes=65_536
        )
    )
    input_envelope["protocol_version"] = True
    with pytest.raises(ScriptProtocolError, match="invalid_input"):
        decode_script_input(
            json.dumps(input_envelope, separators=(",", ":")).encode(), max_bytes=65_536
        )
    for field, category in (
        ("protocol_version", "invalid_result"),
        ("entry_index", "result_identity_mismatch"),
    ):
        frame = _result_body(None, **{field: True})
        with pytest.raises(ScriptProtocolError, match=category):
            decode_script_result(
                frame,
                delivery_id="delivery-1",
                invocation_id=_INVOCATION_ID,
                entry_index=2,
                result_limit_bytes=16_384,
            )


@pytest.mark.parametrize("limit", [True, 0, -1, 1.5, 1_048_577])
def test_protocol_limits_are_exact_positive_v1_budgets(limit: object) -> None:
    """Protocol codecs reject booleans, nonpositive values, and values above v1 maxima."""
    with pytest.raises(ScriptProtocolError, match="invalid_limit"):
        encode_script_input(
            context=_context(), invocation_id=_INVOCATION_ID, entry_index=2,
            max_bytes=limit,
        )


def test_policy_adds_backward_compatible_result_limit_default() -> None:
    """The C05 result limit appends one default without changing old construction."""
    policy = HookScriptExecutionPolicy()
    assert policy.result_limit_bytes == 16_384
    assert replace(policy, result_limit_bytes=1).result_limit_bytes == 1


@pytest.mark.parametrize(
    "context",
    [
        object(),
        replace(_context(), event=object()),
        replace(_context(), registry_generation=True),
        replace(_context(), remaining_budget_ms="800"),
        replace(_context(), depth=-1),
        replace(_context(), event=replace(_context().event, major_version=True)),
        replace(_context(), event=replace(_context().event, sequence="1")),
    ],
)
def test_input_encoder_rejects_invalid_context_and_event_types(context: object) -> None:
    """Encoding applies the same exact context schema without leaking attribute errors."""
    with pytest.raises(ScriptProtocolError, match="^invalid_input$"):
        encode_script_input(
            context=context,
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            max_bytes=65_536,
        )


def _nested_array(depth: int) -> object:
    """Build one JSON value with an exact array nesting depth."""
    value: object = None
    for _ in range(depth):
        value = [value]
    return value


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (_nested_array(16), True),
        (_nested_array(17), False),
        ([None] * 1_024, True),
        ([None] * 1_025, False),
        ("界" * 32_768, True),
        ("界" * 32_769, False),
    ],
)
def test_result_value_complexity_boundaries_match_both_codec_directions(
    value: object, accepted: bool
) -> None:
    """Encoding and decoding apply depth, item, and string limits to value only."""
    if accepted:
        frame = encode_script_result(
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            value=value,
            result_limit_bytes=1_048_576,
        )
        result = decode_script_result(
            frame,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=1_048_576,
        )
        assert result.value == value
        return

    with pytest.raises(ScriptProtocolError, match="^invalid_result$"):
        encode_script_result(
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            value=value,
            result_limit_bytes=1_048_576,
        )
    frame = _result_body(value)
    with pytest.raises(ScriptProtocolError, match="^invalid_result$"):
        decode_script_result(
            frame,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=1_048_576,
        )


@pytest.mark.parametrize(
    "value",
    [
        "界" * 32_768,
        ["界" * 12_000, "语" * 12_000, "文" * 12_000],
    ],
)
def test_large_result_uses_complete_body_byte_limit_only(value: object) -> None:
    """Legal values above 65536 bytes are bounded only by the complete body cap."""
    frame = encode_script_result(
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        value=value,
        result_limit_bytes=1_048_576,
    )
    body_size = len(frame) - 4
    assert len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()) > 65_536
    assert encode_script_result(
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        value=value,
        result_limit_bytes=body_size,
    ) == frame
    assert decode_script_result(
        frame,
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        result_limit_bytes=body_size,
    ).value == value
    with pytest.raises(ScriptProtocolError, match="^result_limit$"):
        encode_script_result(
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            value=value,
            result_limit_bytes=body_size - 1,
        )
    with pytest.raises(ScriptProtocolError, match="^result_limit$"):
        decode_script_result(
            frame,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=body_size - 1,
        )


def test_noncanonical_number_cannot_bypass_canonical_body_limit() -> None:
    """Received and canonical body sizes both obey the configured result budget."""
    raw_body = (
        b'{"protocol_version":1,"delivery_id":"delivery-1",'
        b'"invocation_id":"' + _INVOCATION_ID.encode() +
        b'","entry_index":2,"value":1e2}'
    )
    frame = struct.pack("!I", len(raw_body)) + raw_body
    canonical_frame = encode_script_result(
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        value=100.0,
        result_limit_bytes=1_048_576,
    )
    canonical_body_size = len(canonical_frame) - 4
    assert len(raw_body) < canonical_body_size

    with pytest.raises(ScriptProtocolError, match="^result_limit$"):
        decode_script_result(
            frame,
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            result_limit_bytes=len(raw_body),
        )
    assert decode_script_result(
        frame,
        delivery_id="delivery-1",
        invocation_id=_INVOCATION_ID,
        entry_index=2,
        result_limit_bytes=canonical_body_size,
    ).value == 100.0
    with pytest.raises(ScriptProtocolError, match="^result_limit$"):
        encode_script_result(
            delivery_id="delivery-1",
            invocation_id=_INVOCATION_ID,
            entry_index=2,
            value=100.0,
            result_limit_bytes=canonical_body_size - 1,
        )
