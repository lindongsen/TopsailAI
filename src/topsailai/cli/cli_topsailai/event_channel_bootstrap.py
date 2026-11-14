"""Start the event channel once per CLI process.

The event channel is a process-level facility: a subscriber attaches to the
process, not to one agent turn. Every CLI entry point that runs an agent or an
LLM chat therefore starts the channel once, before the first turn, and lets the
process-level ``atexit`` handler release it.

Keeping the call in the entry point rather than in the agent runtime means the
socket exists for the whole process lifetime, so a subscriber can attach before
the first turn and keeps receiving events across turns, subagents, and retries.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Start the process event channel from a CLI entry point
"""

from __future__ import annotations

import logging
from typing import Optional

from topsailai.workspace.event_channel.process_bootstrap import (
    start_process_event_channel,
)
from topsailai.workspace.event_channel.server import EventChannelServer

logger = logging.getLogger(__name__)


def start_event_channel_for_process(
    session_id: Optional[str] = None,
) -> Optional[EventChannelServer]:
    """Start the process-wide event channel for this CLI process.

    The call is idempotent and never raises: a channel that cannot start must
    not prevent the CLI from running. The channel stays disabled unless
    ``TOPSAILAI_EVENT_CHANNEL_ENABLED`` is set, so an ordinary run creates no
    socket and behaves exactly as before.

    Args:
        session_id: Optional explicit session identity. Pass the identity the
            process already resolved so the socket name matches the events file
            name produced by the same process.

    Returns:
        The running server, or None when the channel is disabled or failed.
    """
    try:
        return start_process_event_channel(session_id=session_id)
    except Exception as e:
        logger.warning("Failed to start the process event channel: %s", e)
        return None


__all__ = ["start_event_channel_for_process"]
