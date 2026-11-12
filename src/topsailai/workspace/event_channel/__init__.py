"""Event channel: push recorded events to external subscribers.

The channel is independent of the control channel. The control channel is
request/response and must never be delayed by a slow subscriber; this channel is
server-push, tolerates loss, and isolates every subscriber behind its own queue
and writer thread.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Event channel transport and server
"""

from topsailai.workspace.event_channel.config import (
    EventChannelConfig,
    get_event_channel_config,
)
from topsailai.workspace.event_channel.connection import EventConnection
from topsailai.workspace.event_channel.protocol import (
    EventChannelProtocolError,
    decode_frame,
    encode_error,
    encode_event,
    encode_heartbeat_ack,
    encode_subscribed,
    encode_unsubscribed,
    parse_heartbeat,
    parse_subscribe,
)
from topsailai.workspace.event_channel.server import EventChannelServer
from topsailai.workspace.event_channel.writer import EventWriter

__all__ = [
    "EventChannelConfig",
    "get_event_channel_config",
    "EventConnection",
    "EventChannelProtocolError",
    "decode_frame",
    "encode_error",
    "encode_event",
    "encode_heartbeat_ack",
    "encode_subscribed",
    "encode_unsubscribed",
    "parse_heartbeat",
    "parse_subscribe",
    "EventChannelServer",
    "EventWriter",
]
