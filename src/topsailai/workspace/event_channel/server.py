"""Event channel server.

Accepts subscriber connections over a Unix domain socket, performs the
``subscribe`` handshake, and pushes events through one writer thread per
subscriber. The channel is deliberately independent of the control channel: the
control channel is request/response and must never be delayed by a slow
subscriber, while this channel is server-push and tolerates loss.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Event channel server
"""

from __future__ import annotations

import atexit
import logging
import socket
import threading
from typing import Dict, Optional, Tuple

from topsailai.events.subscribers.registry import SubscriptionRegistry
from topsailai.workspace.control_channel.transport import (
    create_unix_socket,
    remove_socket_file,
    restrict_socket_permissions,
)
from topsailai.workspace.event_channel.config import EventChannelConfig
from topsailai.workspace.event_channel.connection import EventConnection
from topsailai.workspace.event_channel.protocol import (
    FRAME_HEARTBEAT,
    FRAME_SUBSCRIBE,
    FRAME_UNSUBSCRIBE,
    EventChannelProtocolError,
    decode_frame,
    encode_error,
    encode_heartbeat_ack,
    encode_subscribed,
    encode_unsubscribed,
    parse_heartbeat,
    parse_subscribe,
)
from topsailai.workspace.event_channel.writer import EventWriter

logger = logging.getLogger(__name__)

DEFAULT_BACKLOG = 16
DEFAULT_READ_TIMEOUT = 1.0
DEFAULT_REAPER_INTERVAL = 5.0
RECV_CHUNK_SIZE = 65536

# Shutdown runs from ``atexit``, so every wait is bounded and short. A thread
# that refuses to stop is logged and abandoned instead of delaying interpreter
# exit; the channel is an observability facility and must never hold the process
# open.
DEFAULT_STOP_JOIN_TIMEOUT = 1.0

# Pause before retrying a failed accept, so a persistent system error cannot turn
# the accept loop into a busy spin.
DEFAULT_ACCEPT_RETRY_DELAY = 0.5


def _recv_line(
    conn: socket.socket,
    buffer: bytes,
    max_bytes: int,
) -> Tuple[Optional[str], bytes]:
    """Read one newline-terminated frame from a connection.

    A persistent buffer is used instead of a per-call ``makefile`` so bytes
    already received are never discarded between frames, which matters on a
    long-lived connection that carries many frames.

    Args:
        conn: Connected socket.
        buffer: Bytes received but not yet consumed.
        max_bytes: Maximum accepted frame size.

    Returns:
        A tuple of the decoded line (None on EOF) and the remaining buffer.

    Raises:
        EventChannelProtocolError: When a frame exceeds ``max_bytes``.
    """
    while b"\n" not in buffer:
        chunk = conn.recv(RECV_CHUNK_SIZE)
        if not chunk:
            return None, buffer
        buffer += chunk
        if len(buffer) > max_bytes:
            raise EventChannelProtocolError("frame too large")

    line, _, remainder = buffer.partition(b"\n")
    return line.decode("utf-8", errors="replace").strip(), remainder


class EventChannelServer:
    """Unix domain socket server that pushes events to subscribers.

    Attributes:
        socket_path: Path to the UDS endpoint.
        config: Channel configuration.
        registry: Subscription registry shared with the fan-out layer.
    """

    def __init__(
        self,
        socket_path: str,
        config: Optional[EventChannelConfig] = None,
        registry: Optional[SubscriptionRegistry] = None,
        backlog: int = DEFAULT_BACKLOG,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        reaper_interval: float = DEFAULT_REAPER_INTERVAL,
    ):
        self.socket_path = socket_path
        self.config = config or EventChannelConfig()
        self.registry = (
            registry
            if registry is not None
            else SubscriptionRegistry(
                max_subscribers=self.config.max_subscribers,
                queue_size=self.config.queue_size,
            )
        )
        self.backlog = backlog
        self.read_timeout = read_timeout
        self.reaper_interval = reaper_interval
        self._sock: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._reaper: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._links: Dict[str, Tuple[EventConnection, EventWriter]] = {}
        self._links_lock = threading.Lock()

    def start(self) -> None:
        """Start the accept loop and the stale-subscriber reaper.

        Every step is guarded so a failure leaves no partial state behind: the
        socket file is removed and the stop flag is set before the error is
        reported to the caller. The caller decides whether to continue without a
        channel, which is the normal outcome because observability must never
        break the process it observes.

        Raises:
            OSError: When the socket cannot be created, bound, or configured.
        """
        if self._thread is not None and self._thread.is_alive():
            logger.warning("event channel already running on %s", self.socket_path)
            return

        self._install_runtime_observer()
        self._stop_event.clear()
        try:
            self._sock = create_unix_socket(self.socket_path, backlog=self.backlog)
            restrict_socket_permissions(self.socket_path)
            self._sock.settimeout(self.read_timeout)
        except Exception:
            self._abort_start()
            raise

        try:
            self._thread = threading.Thread(
                target=self._serve, name="EventChannelServer", daemon=True
            )
            self._thread.start()
            self._reaper = threading.Thread(
                target=self._reap_loop, name="EventChannelReaper", daemon=True
            )
            self._reaper.start()
        except Exception:
            self._abort_start()
            raise

        try:
            atexit.register(self.stop)
        except Exception:
            logger.warning(
                "event channel could not register its exit handler", exc_info=True
            )
        logger.info("event channel listening on %s", self.socket_path)

    def _abort_start(self) -> None:
        """Undo a partially completed start so no socket or thread is left over."""
        self._stop_event.set()
        sock = self._sock
        self._sock = None
        if sock is not None:
            try:
                sock.close()
            except Exception:
                pass
        remove_socket_file(self.socket_path)

    def stop(self) -> None:
        """Stop the server, close every link, and remove the socket file.

        This routine runs from ``atexit``, so it must never raise and must never
        wait indefinitely: a failure in one step is logged and the remaining
        steps still run, and a thread that refuses to stop is abandoned rather
        than joined forever. Shutdown is therefore never an abnormal exit point
        and never a blocking point.
        """
        # Each step is isolated instead of sharing one try block. A failure in
        # an early step must not skip the later ones: skipping the join would
        # leave the accept thread running, and skipping the socket removal would
        # leave a stale endpoint behind for the next process.
        self._run_shutdown_step("set stop flag", self._stop_event.set)
        self._run_shutdown_step("close listener", self._close_listener)
        self._run_shutdown_step("join threads", self._join_threads)
        self._run_shutdown_step("close links", self._close_all_links)
        self._run_shutdown_step(
            "remove socket file", lambda: remove_socket_file(self.socket_path)
        )
        try:
            atexit.unregister(self.stop)
        except Exception:
            pass

    def _run_shutdown_step(self, name: str, step) -> None:
        """Run one shutdown step, logging instead of raising on failure.

        Shutdown runs from ``atexit``, where an escaping exception is reported as
        a process-level error and can change the exit status. The channel is
        optional, so a failing step is logged and the remaining steps still run.
        """
        try:
            step()
        except Exception:
            logger.warning("event channel shutdown step failed: %s", name, exc_info=True)

    def _close_listener(self) -> None:
        """Wake the accept loop and close the listening socket."""
        sock = self._sock
        self._sock = None
        if sock is None:
            return
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as wake:
                wake.settimeout(0.5)
                wake.connect(self.socket_path)
        except OSError:
            pass
        try:
            sock.close()
        except Exception:
            pass

    def _join_threads(self) -> None:
        """Join the accept and reaper threads with a short bounded wait."""
        for thread in (self._thread, self._reaper):
            if thread is None or not thread.is_alive():
                continue
            try:
                thread.join(timeout=DEFAULT_STOP_JOIN_TIMEOUT)
            except Exception:
                logger.warning(
                    "event channel thread %s could not be joined", thread.name
                )
                continue
            if thread.is_alive():
                logger.warning("event channel thread %s did not stop", thread.name)

    def _close_all_links(self) -> None:
        """Close every subscriber link, isolating one failure from the rest."""
        for subscriber_id in list(self._links.keys()):
            try:
                self._close_link(
                    subscriber_id,
                    reason="server_stop",
                    join_timeout=DEFAULT_STOP_JOIN_TIMEOUT,
                )
            except Exception:
                logger.warning(
                    "event channel could not close link for subscriber %s",
                    subscriber_id,
                    exc_info=True,
                )

    def is_running(self) -> bool:
        """Return True while the accept thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def _install_runtime_observer(self) -> None:
        """Attach the Runtime Data drop mirror when the channel becomes active.

        The import is deferred so the transport layer does not depend on the
        Agent runtime at module load time, and a failure here never prevents
        the channel from starting.
        """
        try:
            from topsailai.workspace.event_channel.runtime_state import (
                install_event_channel_runtime_observer,
            )

            install_event_channel_runtime_observer()
        except Exception:
            logger.warning(
                "event channel Runtime Data observer not installed", exc_info=True
            )

    def _serve(self) -> None:
        """Accept connections until the server is stopped.

        The loop is the channel's only long-lived reader, so it must survive
        anything a single connection or a transient system condition can throw.
        A failure that is not a shutdown signal is logged and the loop continues
        after a short pause instead of ending the channel for the rest of the
        process.
        """
        while not self._stop_event.is_set():
            sock = self._sock
            if sock is None:
                break
            try:
                conn, _ = sock.accept()
            except socket.timeout:
                continue
            except OSError as error:
                if self._stop_event.is_set():
                    break
                logger.warning("event channel accept failed: %s", error)
                self._stop_event.wait(DEFAULT_ACCEPT_RETRY_DELAY)
                continue
            except Exception:
                logger.warning("event channel accept loop error", exc_info=True)
                self._stop_event.wait(DEFAULT_ACCEPT_RETRY_DELAY)
                continue
            self._start_client_thread(conn)

    def _start_client_thread(self, conn: socket.socket) -> None:
        """Serve one accepted connection on its own daemon thread.

        Thread creation can fail when the process is out of resources. That must
        not end the accept loop, so the connection is closed and the failure is
        logged.
        """
        try:
            threading.Thread(
                target=self._handle_connection,
                args=(conn,),
                name="EventChannelClient",
                daemon=True,
            ).start()
        except Exception:
            logger.warning(
                "event channel could not start a client thread", exc_info=True
            )
            try:
                conn.close()
            except Exception:
                pass

    def _handle_connection(self, conn: socket.socket) -> None:
        """Run the subscribe handshake and then serve one subscriber."""
        subscriber_id: Optional[str] = None
        connection: Optional[EventConnection] = None
        writer: Optional[EventWriter] = None
        buffer = b""
        try:
            conn.settimeout(self.read_timeout)
            raw, buffer = _recv_line(conn, buffer, self.config.max_frame_bytes)
            if raw is None:
                return
            frame = decode_frame(raw)
            if frame.get("type") != FRAME_SUBSCRIBE:
                self._send_raw(conn, encode_error("expected subscribe frame"))
                return

            request = parse_subscribe(frame)
            subscriber = self.registry.register(
                request.subscriber_id, request.event_types
            )
            if subscriber is None:
                self._send_raw(conn, encode_error("subscriber limit reached"))
                return

            subscriber_id = request.subscriber_id
            connection = EventConnection(conn, subscriber_id)
            self._send_raw(conn, encode_subscribed(subscriber_id))

            writer = EventWriter(subscriber, connection)
            previous = self._install_link(subscriber_id, connection, writer)
            if previous is not None:
                self._retire_link(previous, reason="replaced")
            writer.start()

            self._read_loop(connection, subscriber, buffer)
        except EventChannelProtocolError as e:
            logger.info("event channel protocol error: %s", e.message)
            if connection is not None:
                connection.send(encode_error(e.message))
        except Exception:
            logger.exception("event channel connection failed")
        finally:
            if writer is not None:
                writer.join_and_stop()
            if connection is not None:
                connection.close()
            if subscriber_id is not None:
                self._release_link(subscriber_id, connection)

    def _read_loop(
        self,
        connection: EventConnection,
        subscriber,
        buffer: bytes,
    ) -> None:
        """Serve heartbeat and unsubscribe frames until the link ends."""
        while not self._stop_event.is_set() and not connection.closed:
            try:
                raw, buffer = _recv_line(
                    connection.sock, buffer, self.config.max_frame_bytes
                )
            except socket.timeout:
                continue
            except EventChannelProtocolError as e:
                connection.send(encode_error(e.message))
                return
            except OSError:
                return

            if raw is None:
                return
            if not raw:
                continue

            try:
                frame = decode_frame(raw)
            except EventChannelProtocolError as e:
                connection.send(encode_error(e.message))
                continue

            frame_type = frame.get("type")
            if frame_type == FRAME_HEARTBEAT:
                heartbeat = parse_heartbeat(frame)
                subscriber.touch()
                if not connection.send(encode_heartbeat_ack(heartbeat.seq)):
                    return
            elif frame_type == FRAME_UNSUBSCRIBE:
                connection.send(encode_unsubscribed(subscriber.subscriber_id))
                return
            else:
                connection.send(encode_error(f"unsupported frame: {frame_type}"))

    def _reap_loop(self) -> None:
        """Reclaim subscribers that stopped sending heartbeats."""
        while not self._stop_event.is_set():
            self._stop_event.wait(self.reaper_interval)
            if self._stop_event.is_set():
                break
            try:
                for subscriber in self.registry.stale_subscribers(
                    self.config.heartbeat_timeout
                ):
                    logger.info(
                        "event channel reclaiming stale subscriber %s",
                        subscriber.subscriber_id,
                    )
                    self._close_link(subscriber.subscriber_id, reason="heartbeat_timeout")
            except Exception:
                logger.exception("event channel reaper failed")

    def _install_link(
        self,
        subscriber_id: str,
        connection: EventConnection,
        writer: EventWriter,
    ) -> Optional[Tuple[EventConnection, EventWriter]]:
        """Store a link and return the entry it replaced, if any."""
        with self._links_lock:
            previous = self._links.get(subscriber_id)
            self._links[subscriber_id] = (connection, writer)
            return previous

    def _retire_link(
        self,
        entry: Tuple[EventConnection, EventWriter],
        reason: str,
    ) -> None:
        """Stop a link that was already replaced in the registry.

        The replaced entry is no longer reachable through ``_links``, so it is
        torn down directly instead of by subscriber id; otherwise the new link
        would be closed by mistake.
        """
        connection, writer = entry
        writer.join_and_stop()
        connection.close()
        logger.info(
            "event channel retired replaced link for subscriber %s (%s)",
            connection.subscriber_id,
            reason,
        )

    def _release_link(
        self,
        subscriber_id: str,
        connection: EventConnection,
    ) -> None:
        """Remove a link only when the stored entry is still this connection.

        A reconnect installs a new entry under the same subscriber id, so a
        late teardown of the old connection must not remove the new one.
        """
        with self._links_lock:
            entry = self._links.get(subscriber_id)
            if entry is None or entry[0] is not connection:
                return
            self._links.pop(subscriber_id, None)
            writer = entry[1]

        self.registry.unregister(subscriber_id)
        writer.join_and_stop()
        connection.close()
        logger.info(
            "event channel closed link for subscriber %s (disconnected)",
            subscriber_id,
        )

    def _close_link(
        self,
        subscriber_id: str,
        reason: str,
        join_timeout: Optional[float] = None,
    ) -> None:
        """Remove a subscriber link by id and stop its writer.

        Args:
            subscriber_id: Subscriber to remove.
            reason: Why the link is being closed, used for logging.
            join_timeout: Optional bound on the writer join. Shutdown passes a
                short value so a stuck writer cannot delay interpreter exit.
        """
        with self._links_lock:
            entry = self._links.pop(subscriber_id, None)
        if entry is None:
            return
        connection, writer = entry
        self.registry.unregister(subscriber_id)
        if join_timeout is None:
            writer.join_and_stop()
        else:
            writer.join_and_stop(timeout=join_timeout)
        connection.close()
        logger.info(
            "event channel closed link for subscriber %s (%s)", subscriber_id, reason
        )

    @staticmethod
    def _send_raw(conn: socket.socket, data: bytes) -> bool:
        """Send bytes on a raw socket before a connection object exists."""
        try:
            conn.sendall(data)
            return True
        except Exception:
            return False
