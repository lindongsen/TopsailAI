"""Protocol frames for the event channel.

The event channel is a server-push channel: the subscriber connects, sends one
``subscribe`` frame, and then receives ``event`` frames until it unsubscribes or
the link dies. Frames are JSON Lines, one object per line.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Event channel message protocol
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

FRAME_SUBSCRIBE = "subscribe"
FRAME_SUBSCRIBED = "subscribed"
FRAME_EVENT = "event"
FRAME_HEARTBEAT = "heartbeat"
FRAME_HEARTBEAT_ACK = "heartbeat_ack"
FRAME_UNSUBSCRIBE = "unsubscribe"
FRAME_UNSUBSCRIBED = "unsubscribed"
FRAME_ERROR = "error"

DEFAULT_MAX_FRAME_BYTES = 1048576


class EventChannelProtocolError(Exception):
    """Raised when a frame cannot be parsed or violates the protocol."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class SubscribeFrame:
    """Client request to start receiving events.

    Attributes:
        subscriber_id: Client-generated identity, stable across reconnects.
        event_types: Filter patterns; empty means every event type.
    """

    subscriber_id: str
    event_types: List[str] = field(default_factory=list)


@dataclass
class HeartbeatFrame:
    """Client liveness signal.

    Attributes:
        seq: Client-chosen sequence number, echoed back in the acknowledgement.
    """

    seq: int = 0


def encode_frame(frame_type: str, **fields: Any) -> bytes:
    """Encode one frame as a JSONL line.

    Args:
        frame_type: Frame type placed in the ``type`` field.
        **fields: Additional frame fields.

    Returns:
        UTF-8 encoded JSON terminated with a newline.
    """
    payload: Dict[str, Any] = {"type": frame_type}
    payload.update(fields)
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def encode_subscribed(subscriber_id: str) -> bytes:
    """Encode the confirmation sent after a successful subscription."""
    return encode_frame(FRAME_SUBSCRIBED, subscriber_id=subscriber_id)


def encode_event(event_dict: Dict[str, Any]) -> bytes:
    """Encode one pushed event."""
    return encode_frame(FRAME_EVENT, event=event_dict)


def encode_heartbeat_ack(seq: int) -> bytes:
    """Encode a heartbeat acknowledgement echoing the client sequence number."""
    return encode_frame(FRAME_HEARTBEAT_ACK, seq=seq)


def encode_unsubscribed(subscriber_id: str) -> bytes:
    """Encode the confirmation sent before the link is closed."""
    return encode_frame(FRAME_UNSUBSCRIBED, subscriber_id=subscriber_id)


def encode_error(message: str, subscriber_id: Optional[str] = None) -> bytes:
    """Encode a protocol error frame."""
    fields: Dict[str, Any] = {"message": message}
    if subscriber_id:
        fields["subscriber_id"] = subscriber_id
    return encode_frame(FRAME_ERROR, **fields)


def decode_frame(raw: str) -> Dict[str, Any]:
    """Decode one JSONL line into a frame dictionary.

    Args:
        raw: A single JSONL line.

    Returns:
        The decoded frame with a non-empty ``type`` field.

    Raises:
        EventChannelProtocolError: When the line is not a JSON object or has no
            usable ``type`` field.
    """
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        raise EventChannelProtocolError(f"invalid json: {e}") from e

    if not isinstance(data, dict):
        raise EventChannelProtocolError("frame must be a JSON object")

    frame_type = data.get("type")
    if not isinstance(frame_type, str) or not frame_type:
        raise EventChannelProtocolError("missing frame type")

    return data


def parse_subscribe(frame: Dict[str, Any]) -> SubscribeFrame:
    """Validate a decoded frame as a subscribe request.

    Args:
        frame: Decoded frame dictionary.

    Returns:
        The parsed subscribe request.

    Raises:
        EventChannelProtocolError: When the subscriber id is missing or the
            filter is not a list of strings.
    """
    subscriber_id = frame.get("subscriber_id")
    if not isinstance(subscriber_id, str) or not subscriber_id:
        raise EventChannelProtocolError("missing subscriber_id")

    filter_spec = frame.get("filter") or {}
    if not isinstance(filter_spec, dict):
        raise EventChannelProtocolError("filter must be a JSON object")

    event_types = filter_spec.get("event_types") or []
    if not isinstance(event_types, list) or not all(
        isinstance(item, str) for item in event_types
    ):
        raise EventChannelProtocolError("filter.event_types must be a list of strings")

    return SubscribeFrame(subscriber_id=subscriber_id, event_types=list(event_types))


def parse_heartbeat(frame: Dict[str, Any]) -> HeartbeatFrame:
    """Validate a decoded frame as a heartbeat.

    Args:
        frame: Decoded frame dictionary.

    Returns:
        The parsed heartbeat; a missing or non-integer ``seq`` becomes 0.
    """
    seq = frame.get("seq", 0)
    if not isinstance(seq, int) or isinstance(seq, bool):
        seq = 0
    return HeartbeatFrame(seq=seq)
