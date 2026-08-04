"""
Transport layer for the control channel module.

Provides Unix Domain Socket (UDS) listener and connection helpers.

Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-08-03
Purpose: UDS transport for control channel
"""

import logging
import os
import socket
from typing import Optional

logger = logging.getLogger(__name__)


def create_unix_socket(socket_path: str, backlog: int = 128) -> socket.socket:
    """Create and bind a Unix Domain Socket.

    Any existing socket file at the path is removed before binding.

    Args:
        socket_path: Filesystem path for the UDS endpoint.
        backlog: Listen backlog size.

    Returns:
        A bound and listening socket.socket instance.

    Raises:
        OSError: If the socket cannot be created or bound.
    """
    remove_socket_file(socket_path)
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        sock.bind(socket_path)
        sock.listen(backlog)
    except Exception:
        sock.close()
        raise
    return sock


def remove_socket_file(socket_path: str) -> None:
    """Remove a socket file if it exists.

    Args:
        socket_path: Path to the socket file.
    """
    if not socket_path:
        return
    try:
        if os.path.exists(socket_path):
            os.remove(socket_path)
            logger.debug("removed existing control socket: %s", socket_path)
    except Exception as e:
        logger.warning("failed to remove control socket %s: %s", socket_path, e)


def restrict_socket_permissions(socket_path: str, mode: int = 0o600) -> None:
    """Restrict socket file permissions to the owner.

    Args:
        socket_path: Path to the socket file.
        mode: Desired file permission bits.
    """
    if not socket_path or not os.path.exists(socket_path):
        return
    try:
        os.chmod(socket_path, mode)
    except Exception as e:
        logger.warning("failed to chmod control socket %s: %s", socket_path, e)


def read_jsonl_lines(conn: socket.socket, timeout: Optional[float] = None) -> Optional[str]:
    """Read a single JSONL line from a socket connection.

    Args:
        conn: Connected socket.
        timeout: Optional read timeout in seconds.

    Returns:
        A stripped JSONL line, or None if the connection is closed.

    Raises:
        socket.timeout: If the read exceeds the timeout.
    """
    if timeout is not None:
        conn.settimeout(timeout)
    file_obj = conn.makefile("r")
    try:
        line = file_obj.readline()
    finally:
        file_obj.close()
    if not line:
        return None
    return line.strip()


def send_bytes(conn: socket.socket, data: bytes) -> bool:
    """Send all bytes over a socket connection.

    Args:
        conn: Connected socket.
        data: Bytes to send.

    Returns:
        True if all bytes were sent, False otherwise.
    """
    try:
        conn.sendall(data)
        return True
    except Exception as e:
        logger.warning("failed to send data over control channel: %s", e)
        return False
