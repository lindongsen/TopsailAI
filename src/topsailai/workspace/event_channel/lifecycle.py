"""Process-wide lifecycle for the shared event channel server.

The event channel socket path is session- and process-scoped, so every
``AgentChat`` in one process that targets the same session must share a single
server. Binding the same path twice raises ``OSError``, and a second server
would also install a second subscription registry, so the fan-out layer would
only ever see one of them.

This module owns that sharing: the first caller starts the server and installs
its registry, later callers reuse it, and the server stops only when the last
caller releases it. The pattern mirrors the control channel so both channels
follow one lifecycle convention.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Share one event channel server per session and process
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from topsailai.events.subscribers.fanout import (
    get_subscription_registry_or_none,
    set_subscription_registry,
)
from topsailai.events.subscribers.registry import SubscriptionRegistry
from topsailai.workspace.event_channel.config import EventChannelConfig
from topsailai.workspace.event_channel.server import EventChannelServer
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai.workspace.folder_utils import (
    get_event_channel_socket_path,
    resolve_session_id_for_files,
)

logger = logging.getLogger(__name__)


@dataclass
class _ChannelEntry:
    """Internal record for a shared EventChannelServer instance."""

    server: EventChannelServer
    registry: SubscriptionRegistry
    ref_count: int = 1


# Process-level registry mapping (session_id, pid) to a shared server. This
# guarantees that only one event channel server is started per session+pid
# combination inside a single process, even when multiple AgentChat instances
# (e.g. subagents) are created for the same session.
_event_channel_servers: Dict[Tuple[str, int], _ChannelEntry] = {}
_event_channel_lock = threading.Lock()


def resolve_event_channel_socket_path(session_id: Optional[str] = None) -> str:
    """Resolve the default event channel socket path for this process.

    Args:
        session_id: Optional explicit session ID. When omitted or empty, the
            session id is resolved via ``resolve_session_id_for_files``.

    Returns:
        Absolute path for the event channel socket.
    """
    if not session_id:
        session_id = resolve_session_id_for_files()
    return get_event_channel_socket_path(
        FOLDER_WORKSPACE_TASK, session_id, os.getpid()
    )


def get_or_start_event_channel_server(
    session_id: str,
    pid: int,
    config: Optional[EventChannelConfig] = None,
    socket_path: Optional[str] = None,
) -> EventChannelServer:
    """Return an existing EventChannelServer for (session_id, pid) or create one.

    The server is shared across all callers in the same process that target the
    same session and pid. Reference counting keeps the server alive until the
    last caller releases it.

    The subscription registry is installed into the fan-out layer before the
    accept loop starts, so an event produced immediately after startup is never
    dropped merely because the registry was not yet visible.

    Args:
        session_id: Session identifier.
        pid: Process identifier.
        config: Optional channel configuration. Defaults to a disabled config,
            so callers must pass an enabled one to actually start a server.
        socket_path: Optional explicit socket path. Defaults to the standard
            session-scoped path.

    Returns:
        The shared EventChannelServer instance.

    Raises:
        OSError: When the socket cannot be created or bound.
    """
    key = (session_id, pid)
    with _event_channel_lock:
        entry = _event_channel_servers.get(key)
        if entry is not None and entry.server.is_running():
            entry.ref_count += 1
            logger.debug(
                "reusing event channel server for session=%s pid=%s (ref_count=%s)",
                session_id,
                pid,
                entry.ref_count,
            )
            return entry.server

        if socket_path is None:
            socket_path = get_event_channel_socket_path(
                FOLDER_WORKSPACE_TASK, session_id, pid
            )

        effective = config or EventChannelConfig()
        registry = SubscriptionRegistry(
            max_subscribers=effective.max_subscribers,
            queue_size=effective.queue_size,
        )
        server = EventChannelServer(
            socket_path=socket_path,
            config=effective,
            registry=registry,
        )
        previous_registry = get_subscription_registry_or_none()
        set_subscription_registry(registry)
        try:
            server.start()
        except Exception:
            # Restore whatever was installed before this attempt. Detaching the
            # registry outright would silently stop fan-out for a server that is
            # still running for another session in the same process.
            set_subscription_registry(previous_registry)
            raise
        _event_channel_servers[key] = _ChannelEntry(server=server, registry=registry)
        logger.info(
            "started shared event channel server at %s for session=%s pid=%s",
            socket_path,
            session_id,
            pid,
        )
        return server


def release_event_channel_server(
    session_id: str,
    pid: int,
    server: Optional[EventChannelServer] = None,
) -> None:
    """Release one reference to the shared EventChannelServer for (session_id, pid).

    When the reference count reaches zero the server is stopped, its socket file
    is removed, and the process-wide subscription registry is detached so a
    stopped channel cannot keep receiving fan-out traffic.

    Args:
        session_id: Session identifier.
        pid: Process identifier.
        server: Optional server instance to validate against the registry.
    """
    key = (session_id, pid)
    with _event_channel_lock:
        entry = _event_channel_servers.get(key)
        if entry is None:
            logger.debug(
                "no shared event channel server to release for session=%s pid=%s",
                session_id,
                pid,
            )
            return
        if server is not None and entry.server is not server:
            logger.warning(
                "release_event_channel_server called with mismatched server "
                "for session=%s pid=%s",
                session_id,
                pid,
            )
            return

        entry.ref_count -= 1
        logger.debug(
            "released event channel server for session=%s pid=%s (ref_count=%s)",
            session_id,
            pid,
            entry.ref_count,
        )
        if entry.ref_count > 0:
            return

        # Detach the entry under the lock, then stop the server outside it.
        # Stopping joins threads, and holding the process-wide lock across a
        # join would make shutdown a blocking point for every other thread.
        _event_channel_servers.pop(key, None)

    try:
        entry.server.stop()
    except Exception as e:
        logger.warning("failed to stop shared event channel server: %s", e)
    set_subscription_registry(None)
    logger.info(
        "stopped shared event channel server for session=%s pid=%s",
        session_id,
        pid,
    )


def reset_event_channel_lifecycle() -> None:
    """Stop every shared server and clear the process-level registry.

    Intended for tests and for a process that must drop all channel state. Each
    server is stopped independently so one failure cannot leave the others
    running.
    """
    with _event_channel_lock:
        entries = list(_event_channel_servers.items())
        _event_channel_servers.clear()
    for (session_id, pid), entry in entries:
        try:
            entry.server.stop()
        except Exception as e:
            logger.warning(
                "failed to stop event channel server for session=%s pid=%s: %s",
                session_id,
                pid,
                e,
            )
    set_subscription_registry(None)


__all__ = [
    "get_or_start_event_channel_server",
    "release_event_channel_server",
    "reset_event_channel_lifecycle",
    "resolve_event_channel_socket_path",
]
