"""Process-level bootstrap for the event channel server.

The channel belongs to the process, not to one agent run. A subscriber must be
able to attach before the first agent turn starts and must keep receiving events
across every turn, subagent, and retry inside the same process. Starting the
server from the agent runtime instead would bind the socket only for the
duration of one ``run()`` call, so a subscriber that attaches between turns
would find no endpoint at all.

This module owns that process-level lifetime: a CLI entry point calls
``start_process_event_channel`` once at startup, the server stays up for the
whole process, and an ``atexit`` handler releases it on interpreter exit.

Hard invariants: the channel is an observability facility, so it must never be
able to harm the process it observes. Nothing in this module raises out of a
public function, nothing waits without a bound, and nothing changes the process
exit code. A startup failure degrades to "no channel" and the process continues.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-14
Purpose: Start the event channel once per process instead of per agent run
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
from typing import Optional, Tuple

from topsailai.workspace.event_channel.config import get_event_channel_config
from topsailai.workspace.event_channel.lifecycle import (
    get_or_start_event_channel_server,
    release_event_channel_server,
)
from topsailai.workspace.event_channel.server import EventChannelServer
from topsailai.workspace.folder_utils import resolve_session_id_for_files
from topsailai.workspace.session_identity import initialize_session_id

logger = logging.getLogger(__name__)

# The server started for this process, together with the session identity it was
# bound to. Both are needed on release because the socket path is derived from
# the session id and the pid.
_started_server: Optional[EventChannelServer] = None
_started_session_id: Optional[str] = None
_atexit_registered = False

# Reentrant so a nested call from the same thread cannot deadlock, and acquired
# with a timeout on the shutdown path so a thread that died while holding it can
# never hang interpreter exit.
_bootstrap_lock = threading.RLock()
LOCK_ACQUIRE_TIMEOUT = 2.0


def start_process_event_channel(
    session_id: Optional[str] = None,
    socket_path: Optional[str] = None,
) -> Optional[EventChannelServer]:
    """Start the process-wide event channel server when the channel is enabled.

    The call is idempotent: the first caller starts the server and every later
    caller receives the same instance. The server is stopped by
    ``stop_process_event_channel``, which is also registered as an ``atexit``
    handler so a normal interpreter exit releases the socket.

    The channel is enabled by default, so an ordinary run creates a socket.
    Setting ``TOPSAILAI_EVENT_CHANNEL_ENABLED`` to a false value creates no
    socket file. Enabling it by default is safe only because of the hard
    invariants above: no startup, delivery, or shutdown failure can block the
    process or change its exit code.

    Args:
        session_id: Optional explicit session identity. When omitted, the
            identity is resolved from the environment and finally from the
            standard file-path fallback, so the socket name matches the events
            file name produced by the same process.
        socket_path: Optional explicit socket path. Defaults to the standard
            session-scoped path. Tests use it to keep the path short, because a
            Unix domain socket path is limited to about 108 bytes.

    Returns:
        The running server, or None when the channel is disabled or cannot be
        started. A startup failure is logged and never raised, because
        observability must not break the process it observes.
    """
    global _started_server, _started_session_id, _atexit_registered

    try:
        with _bootstrap_lock:
            if _started_server is not None:
                return _started_server

            config = get_event_channel_config()
            if not config.enabled:
                return None

            # Publishing the identity keeps the socket name, the events file
            # name, and the session record on one identity.
            resolved_session_id = (
                initialize_session_id(session_id) or resolve_session_id_for_files()
            )
            server = get_or_start_event_channel_server(
                session_id=resolved_session_id,
                pid=os.getpid(),
                config=config,
                socket_path=socket_path,
            )

            _started_server = server
            _started_session_id = resolved_session_id
            if not _atexit_registered:
                atexit.register(_atexit_stop)
                _atexit_registered = True
    except Exception as e:
        logger.warning("Failed to start the process event channel: %s", e)
        return None

    logger.info(
        "Process event channel listening at %s for session=%s",
        server.socket_path,
        resolved_session_id,
    )
    return server


def _atexit_stop() -> None:
    """Release the channel on interpreter exit without ever raising.

    ``atexit`` handlers run during shutdown, where an escaping exception is
    printed as a process-level error and can change the exit status. The channel
    is optional, so a shutdown problem is logged and swallowed.
    """
    try:
        stop_process_event_channel()
    except Exception:
        logger.warning("Process event channel shutdown failed", exc_info=True)


def stop_process_event_channel() -> None:
    """Release the process-wide event channel server.

    Safe to call when no server was started, and safe to call more than once.
    The socket file is removed by the underlying server stop.
    """
    global _started_server, _started_session_id

    server, session_id = _take_started_server()
    if server is None:
        return

    try:
        release_event_channel_server(
            session_id=session_id,
            pid=os.getpid(),
            server=server,
        )
        logger.info("Released the process event channel for session=%s", session_id)
    except Exception as e:
        logger.warning("Failed to release the process event channel: %s", e)


def _take_started_server() -> Tuple[Optional[EventChannelServer], Optional[str]]:
    """Detach the started server from the module state.

    The lock is acquired with a timeout because this runs from ``atexit``: a
    thread that died while holding the lock must not be able to hang interpreter
    exit. When the lock cannot be taken the state is still detached, because
    releasing the socket matters more than the lock.
    """
    global _started_server, _started_session_id

    acquired = _bootstrap_lock.acquire(timeout=LOCK_ACQUIRE_TIMEOUT)
    if not acquired:
        logger.warning(
            "Process event channel lock unavailable during shutdown; "
            "releasing without it"
        )
        server, session_id = _started_server, _started_session_id
        _started_server = None
        _started_session_id = None
        return server, session_id

    try:
        server, session_id = _started_server, _started_session_id
        _started_server = None
        _started_session_id = None
        return server, session_id
    finally:
        _bootstrap_lock.release()


def get_process_event_channel_server() -> Optional[EventChannelServer]:
    """Return the running process event channel server, or None when absent."""
    return _started_server


def reset_process_event_channel() -> None:
    """Stop the process server and clear the bootstrap state.

    Intended for tests that must observe a fresh process-level startup.
    """
    global _atexit_registered

    stop_process_event_channel()
    try:
        with _bootstrap_lock:
            _atexit_registered = False
    except Exception:
        logger.warning("Process event channel reset failed", exc_info=True)


__all__ = [
    "get_process_event_channel_server",
    "reset_process_event_channel",
    "start_process_event_channel",
    "stop_process_event_channel",
]
