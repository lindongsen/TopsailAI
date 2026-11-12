"""A single event-channel connection.

One connection carries frames in both directions: the reader thread sends
``heartbeat_ack`` while the writer thread sends ``event``. Both go through the
same socket, so every outbound frame is serialized by one write lock; without
it, two concurrent ``sendall`` calls would interleave bytes and tear frames.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-11-12
Purpose: Event channel connection with serialized outbound frames
"""

from __future__ import annotations

import logging
import socket
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class EventConnection:
    """One subscriber link: a socket, a write lock, and a closed flag.

    Attributes:
        subscriber_id: Identity of the subscriber owning this link.
        sock: The connected socket.
    """

    def __init__(self, sock: socket.socket, subscriber_id: str):
        self.sock = sock
        self.subscriber_id = subscriber_id
        self._write_lock = threading.Lock()
        self._closed = False

    @property
    def closed(self) -> bool:
        """Return True once the link has been closed."""
        return self._closed

    def send(self, data: bytes) -> bool:
        """Send one frame, serialized against every other outbound frame.

        Args:
            data: Encoded frame bytes.

        Returns:
            True when the frame was fully written, False when the link is
            already closed or the write failed.
        """
        with self._write_lock:
            if self._closed:
                return False
            try:
                self.sock.sendall(data)
                return True
            except Exception as e:
                logger.info(
                    "event channel send failed for subscriber %s: %s",
                    self.subscriber_id,
                    e,
                )
                return False

    def close(self) -> None:
        """Close the link. Idempotent and safe to call from any thread."""
        with self._write_lock:
            if self._closed:
                return
            self._closed = True
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self.sock.close()
            except Exception as e:
                logger.debug(
                    "event channel socket close failed for subscriber %s: %s",
                    self.subscriber_id,
                    e,
                )

    def set_read_timeout(self, timeout: Optional[float]) -> None:
        """Apply a read timeout so the reader can observe shutdown."""
        try:
            self.sock.settimeout(timeout)
        except Exception as e:
            logger.debug(
                "event channel settimeout failed for subscriber %s: %s",
                self.subscriber_id,
                e,
            )
