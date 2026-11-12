#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Subscribe to a running TopsailAI session's event channel.

The client connects to the session's event-channel Unix domain socket, sends a
``subscribe`` frame, then prints every pushed event as one JSON line. A
heartbeat is sent on an interval so the server can tell a live subscriber from a
dead one; when the link drops the client exits, and re-running it with the same
subscriber id resumes from the current moment.

The subscriber id is generated automatically and can be overridden with
``--subscriber-id`` so a reconnect is recognised as the same subscriber.
"""

import argparse
import json
import os
import socket
import sys
import time
import uuid
from typing import List, Optional

import _import_topsailai  # noqa: F401

from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai.workspace.folder_utils import (
    get_event_channel_socket_path,
    resolve_session_id_for_files,
)

DEFAULT_HEARTBEAT_INTERVAL = 10.0
DEFAULT_READ_TIMEOUT = 1.0
RECV_CHUNK_SIZE = 65536


def generate_subscriber_id() -> str:
    """Return a fresh subscriber id for a new subscription."""
    return f"sub-{uuid.uuid4().hex[:12]}"


def resolve_socket_path(session_id: str, pid: Optional[int]) -> str:
    """Return the event-channel socket path for a session process.

    Args:
        session_id: Session identifier.
        pid: Explicit process id, or None to discover it from the task folder.

    Returns:
        Absolute socket path.

    Raises:
        SystemExit: When no matching socket can be found.
    """
    if pid is not None:
        return get_event_channel_socket_path(FOLDER_WORKSPACE_TASK, session_id, pid)

    candidates = discover_socket_paths(session_id)
    if not candidates:
        print(
            f"ERROR: no event channel socket found for session {session_id}",
            file=sys.stderr,
        )
        raise SystemExit(1)
    if len(candidates) > 1:
        print(
            "ERROR: multiple event channel sockets found; pass --pid to choose one:",
            file=sys.stderr,
        )
        for path in candidates:
            print(f"  {path}", file=sys.stderr)
        raise SystemExit(1)
    return candidates[0]


def discover_socket_paths(session_id: str) -> List[str]:
    """Return every event-channel socket path belonging to a session."""
    if not os.path.isdir(FOLDER_WORKSPACE_TASK):
        return []
    prefix = f"{session_id}."
    suffix = ".session.events.sock"
    found = []
    for name in sorted(os.listdir(FOLDER_WORKSPACE_TASK)):
        if not name.startswith(prefix) or not name.endswith(suffix):
            continue
        path = os.path.join(FOLDER_WORKSPACE_TASK, name)
        if os.path.exists(path):
            found.append(os.path.abspath(path))
    return found


def send_frame(sock: socket.socket, frame: dict) -> None:
    """Send one JSONL frame."""
    sock.sendall(json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n")


def subscribe(
    sock: socket.socket,
    subscriber_id: str,
    event_types: Optional[List[str]],
) -> dict:
    """Send the subscribe frame and return the server's first response."""
    frame = {"type": "subscribe", "subscriber_id": subscriber_id}
    if event_types:
        frame["filter"] = {"event_types": event_types}
    send_frame(sock, frame)
    return read_frame(sock, b"")[0]


def read_frame(sock: socket.socket, buffer: bytes):
    """Read one JSONL frame, returning the frame and the remaining buffer."""
    while b"\n" not in buffer:
        chunk = sock.recv(RECV_CHUNK_SIZE)
        if not chunk:
            return None, buffer
        buffer += chunk
    line, _, remainder = buffer.partition(b"\n")
    text = line.decode("utf-8", errors="replace").strip()
    if not text:
        return read_frame(sock, remainder)
    return json.loads(text), remainder


def run_client(
    socket_path: str,
    subscriber_id: str,
    event_types: Optional[List[str]],
    heartbeat_interval: float,
    max_events: Optional[int],
) -> int:
    """Subscribe and print events until the link ends or the limit is reached.

    Args:
        socket_path: Event-channel socket path.
        subscriber_id: Client-generated identity.
        event_types: Optional filter patterns.
        heartbeat_interval: Seconds between heartbeats.
        max_events: Stop after this many events; None runs until the link ends.

    Returns:
        Process exit code.
    """
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.settimeout(DEFAULT_READ_TIMEOUT)
    try:
        sock.connect(socket_path)
    except OSError as e:
        print(f"ERROR: cannot connect to {socket_path}: {e}", file=sys.stderr)
        sock.close()
        return 1

    try:
        confirmation = subscribe(sock, subscriber_id, event_types)
        if confirmation is None or confirmation.get("type") != "subscribed":
            message = (confirmation or {}).get("message", "no response")
            print(f"ERROR: subscription rejected: {message}", file=sys.stderr)
            return 1

        print(
            f"subscribed: subscriber_id={subscriber_id} socket={socket_path}",
            file=sys.stderr,
            flush=True,
        )

        buffer = b""
        seq = 0
        last_heartbeat = time.monotonic()
        received = 0

        while True:
            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_interval:
                seq += 1
                send_frame(sock, {"type": "heartbeat", "seq": seq})
                last_heartbeat = now

            try:
                frame, buffer = read_frame(sock, buffer)
            except socket.timeout:
                continue
            except OSError:
                print("link closed", file=sys.stderr, flush=True)
                return 0

            if frame is None:
                print("link closed", file=sys.stderr, flush=True)
                return 0

            frame_type = frame.get("type")
            if frame_type == "event":
                print(json.dumps(frame.get("event", {}), ensure_ascii=False), flush=True)
                received += 1
                if max_events is not None and received >= max_events:
                    return 0
            elif frame_type == "heartbeat_ack":
                continue
            elif frame_type == "error":
                print(
                    f"ERROR: {frame.get('message', 'unknown')}", file=sys.stderr
                )
                return 1
            elif frame_type == "unsubscribed":
                return 0
    except KeyboardInterrupt:
        try:
            send_frame(sock, {"type": "unsubscribe"})
        except OSError:
            pass
        return 0
    finally:
        try:
            sock.close()
        except OSError:
            pass


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""
    parser = argparse.ArgumentParser(
        description="Subscribe to a TopsailAI session event channel",
    )
    parser.add_argument(
        "-s",
        "--session-id",
        default=None,
        help="Session id; resolved from the environment when omitted",
    )
    parser.add_argument(
        "-p",
        "--pid",
        type=int,
        default=None,
        help="Process id of the target session; discovered when omitted",
    )
    parser.add_argument(
        "--subscriber-id",
        default=None,
        help="Subscriber identity; generated automatically when omitted",
    )
    parser.add_argument(
        "--event-types",
        default=None,
        help="Comma-separated filter patterns, e.g. 'tool_call.*,llm.*'",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=float,
        default=DEFAULT_HEARTBEAT_INTERVAL,
        help=f"Heartbeat interval in seconds (default {DEFAULT_HEARTBEAT_INTERVAL})",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=None,
        help="Exit after receiving this many events",
    )
    parser.add_argument(
        "--socket-path",
        default=None,
        help="Explicit event-channel socket path",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for the event-channel subscriber client."""
    args = build_parser().parse_args(argv)

    session_id = args.session_id or resolve_session_id_for_files()
    subscriber_id = args.subscriber_id or generate_subscriber_id()
    event_types = (
        [item.strip() for item in args.event_types.split(",") if item.strip()]
        if args.event_types
        else None
    )
    socket_path = args.socket_path or resolve_socket_path(session_id, args.pid)

    return run_client(
        socket_path=socket_path,
        subscriber_id=subscriber_id,
        event_types=event_types,
        heartbeat_interval=args.heartbeat_interval,
        max_events=args.max_events,
    )


if __name__ == "__main__":
    raise SystemExit(main())
