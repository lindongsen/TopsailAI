"""Configuration for the event channel.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Event channel configuration
"""

from __future__ import annotations

from dataclasses import dataclass

from topsailai.utils import env_tool

DEFAULT_MAX_SUBSCRIBERS = 8
DEFAULT_QUEUE_SIZE = 1000
DEFAULT_HEARTBEAT_INTERVAL = 10.0
DEFAULT_HEARTBEAT_TIMEOUT = 30.0
DEFAULT_MAX_FRAME_BYTES = 1048576


@dataclass
class EventChannelConfig:
    """Configuration for the event channel.

    Attributes:
        enabled: Master switch; enabled by default so an operator gets
            observability without opting in. The channel is hardened so that
            enabling it can never block or terminate the process.
        max_subscribers: Maximum number of concurrent subscribers.
        queue_size: Per-subscriber queue capacity.
        heartbeat_interval: Client heartbeat interval in seconds.
        heartbeat_timeout: Server idle limit before a subscriber is reclaimed.
        max_frame_bytes: Maximum accepted single frame size.
    """

    enabled: bool = True
    max_subscribers: int = DEFAULT_MAX_SUBSCRIBERS
    queue_size: int = DEFAULT_QUEUE_SIZE
    heartbeat_interval: float = DEFAULT_HEARTBEAT_INTERVAL
    heartbeat_timeout: float = DEFAULT_HEARTBEAT_TIMEOUT
    max_frame_bytes: int = DEFAULT_MAX_FRAME_BYTES

    @classmethod
    def from_env(cls) -> "EventChannelConfig":
        """Build a configuration from environment variables."""
        reader = env_tool.EnvReaderInstance

        enabled = reader.check_bool("TOPSAILAI_EVENT_CHANNEL_ENABLED", default=True)
        max_subscribers = reader.get(
            "TOPSAILAI_EVENT_CHANNEL_MAX_SUBSCRIBERS",
            default=DEFAULT_MAX_SUBSCRIBERS,
            formatter=int,
        )
        queue_size = reader.get(
            "TOPSAILAI_EVENT_CHANNEL_QUEUE_SIZE",
            default=DEFAULT_QUEUE_SIZE,
            formatter=int,
        )
        heartbeat_interval = reader.get(
            "TOPSAILAI_EVENT_CHANNEL_HEARTBEAT_INTERVAL",
            default=DEFAULT_HEARTBEAT_INTERVAL,
            formatter=float,
        )
        heartbeat_timeout = reader.get(
            "TOPSAILAI_EVENT_CHANNEL_HEARTBEAT_TIMEOUT",
            default=DEFAULT_HEARTBEAT_TIMEOUT,
            formatter=float,
        )
        max_frame_bytes = reader.get(
            "TOPSAILAI_EVENT_CHANNEL_MAX_FRAME_BYTES",
            default=DEFAULT_MAX_FRAME_BYTES,
            formatter=int,
        )

        return cls(
            enabled=enabled,
            max_subscribers=max_subscribers
            if max_subscribers is not None and max_subscribers > 0
            else DEFAULT_MAX_SUBSCRIBERS,
            queue_size=queue_size
            if queue_size is not None and queue_size > 0
            else DEFAULT_QUEUE_SIZE,
            heartbeat_interval=heartbeat_interval
            if heartbeat_interval is not None and heartbeat_interval > 0
            else DEFAULT_HEARTBEAT_INTERVAL,
            heartbeat_timeout=heartbeat_timeout
            if heartbeat_timeout is not None and heartbeat_timeout > 0
            else DEFAULT_HEARTBEAT_TIMEOUT,
            max_frame_bytes=max_frame_bytes
            if max_frame_bytes is not None and max_frame_bytes > 0
            else DEFAULT_MAX_FRAME_BYTES,
        )


def get_event_channel_config() -> EventChannelConfig:
    """Return a fresh configuration parsed from the current environment."""
    return EventChannelConfig.from_env()
