"""
Server for the control channel module.

Provides a Unix-domain-socket (UDS) server that accepts JSONL control
requests from external processes (e.g. `topsailai_send_control`) and
routes them to registered handlers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: Control channel server
"""

import atexit
import logging
import os
import socket
import threading
from typing import Optional

from topsailai.utils import env_tool
from topsailai.workspace.control_channel.exceptions import ControlProtocolError
from topsailai.workspace.control_channel.handler import ControlHandlerRegistry
from topsailai.workspace.control_channel.protocol import (
    ControlContext,
    ControlResponse,
    decode_request,
    encode_response,
)
from topsailai.workspace.control_channel.transport import (
    create_unix_socket,
    read_jsonl_lines,
    remove_socket_file,
    restrict_socket_permissions,
    send_bytes,
)
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai.workspace.folder_utils import get_control_socket_path

logger = logging.getLogger(__name__)


DEFAULT_BACKLOG = 128
DEFAULT_TIMEOUT = 30.0


def resolve_socket_path(session_id: Optional[str] = None) -> str:
    """Resolve the default control channel socket path.

    The path follows the session-scoped convention used by other runtime files:
    ``{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.sock``.

    Args:
        session_id: Optional session ID. Falls back to env_tool.get_session_id().

    Returns:
        Absolute path for the control socket.
    """
    if not session_id:
        session_id = env_tool.get_session_id() or "topsailai"
    return get_control_socket_path(FOLDER_WORKSPACE_TASK, session_id, os.getpid())


def get_backlog() -> int:
    """Return the configured listen backlog."""
    return env_tool.EnvReaderInstance.get(
        "TOPSAILAI_CONTROL_CHANNEL_BACKLOG",
        default=DEFAULT_BACKLOG,
        formatter=int,
    ) or DEFAULT_BACKLOG


def get_timeout() -> Optional[float]:
    """Return the configured accept timeout in seconds, or None for blocking."""
    value = env_tool.EnvReaderInstance.get(
        "TOPSAILAI_CONTROL_CHANNEL_TIMEOUT",
        default=DEFAULT_TIMEOUT,
        formatter=float,
    )
    if value is None or value <= 0:
        return None
    return value


class ControlServer:
    """Unix Domain Socket server for the runtime control channel.

    Attributes:
        socket_path: Path to the UDS endpoint.
        registry: Handler registry for dispatching requests.
        context: Runtime context passed to handlers.
        backlog: Listen backlog size.
        timeout: Accept timeout in seconds.
    """

    def __init__(
        self,
        socket_path: str,
        registry: ControlHandlerRegistry,
        context: ControlContext,
        backlog: Optional[int] = None,
        timeout: Optional[float] = None,
    ):
        self.socket_path = socket_path
        self.registry = registry
        self.context = context
        self.backlog = backlog if backlog is not None else get_backlog()
        self.timeout = timeout if timeout is not None else get_timeout()
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        """Start the control channel server in a background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("control server already running on %s", self.socket_path)
            return

        self._stop_event.clear()
        self._sock = create_unix_socket(self.socket_path, backlog=self.backlog)
        restrict_socket_permissions(self.socket_path)
        self._sock.settimeout(self.timeout)

        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        atexit.register(self.stop)
        logger.info("control channel listening on %s", self.socket_path)

    def stop(self) -> None:
        """Stop the control channel server and clean up the socket file."""
        self._stop_event.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                logger.warning("control server thread did not stop within timeout")
        remove_socket_file(self.socket_path)
        try:
            atexit.unregister(self.stop)
        except Exception:
            pass

    def is_running(self) -> bool:
        """Return True if the server thread is currently running."""
        return self._thread is not None and self._thread.is_alive()

    def _serve(self) -> None:
        """Main accept loop running in the background thread."""
        while not self._stop_event.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            client_thread = threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                daemon=True,
            )
            client_thread.start()

    def _handle_connection(self, conn: socket.socket) -> None:
        """Handle a single client connection until it closes."""
        with conn:
            while not self._stop_event.is_set():
                try:
                    line = read_jsonl_lines(conn)
                except socket.timeout:
                    continue
                except OSError:
                    break
                if line is None:
                    break
                if not line:
                    continue
                response = self._dispatch(line)
                encoded = encode_response(response)
                if not send_bytes(conn, encoded):
                    break

    def _dispatch(self, raw: str) -> ControlResponse:
        """Decode and dispatch a single raw JSONL line."""
        try:
            request = decode_request(raw)
        except ControlProtocolError as e:
            return ControlResponse(
                request_id=e.request_id,
                status="error",
                error=e.message,
            )
        return self.registry.handle(request, self.context)
