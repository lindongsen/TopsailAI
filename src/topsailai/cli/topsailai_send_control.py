#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Send control messages to running TopsailAI sessions through UDS.

This script connects to a session's Unix Domain Socket control channel and
sends a raw action string. The protocol is JSONL-over-UDS using the
ControlRequest format:

    {"request_id": "...", "action": "...", "payload": {...}}

When --session_id and/or --pid are omitted, the script scans
{TOPSAILAI_HOME}/workspace/task/ for files matching
``{session_id}.{pid}.session.stdout`` or
``{session_id}.{pid}[.{other}].task.stdout`` and derives the control socket
path(s) from each match.
"""

import argparse
import json
import os
import socket
import sys
import uuid
from typing import Any, List, Optional, Tuple

import _import_topsailai  # noqa: F401

from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK
from topsailai_session_add_agent2llm_message import (
    parse_stdout_filename,
)

SOCKET_SUFFIX = ".session.control.sock"


def build_socket_path(session_id: str, pid: str) -> str:
    """Return the default UDS socket path for a session process."""
    return os.path.abspath(
        os.path.join(
            FOLDER_WORKSPACE_TASK,
            f"{session_id}.{pid}{SOCKET_SUFFIX}",
        )
    )


def discover_socket_paths(
    task_folder: str,
    session_id: Optional[str] = None,
    pid: Optional[str] = None,
) -> List[str]:
    """Discover control socket paths from stdout files in the task directory.

    Args:
        task_folder: Directory containing session/task stdout files.
        session_id: If provided, only match stdout files for this session.
        pid: If provided, only match stdout files for this PID.

    Returns:
        Sorted list of socket paths for each matching stdout file. The list is
        sorted by stdout file mtime descending so the most recently active
        session/task comes first.
    """
    targets = []
    if not os.path.isdir(task_folder):
        return targets

    for entry in os.listdir(task_folder):
        if not (entry.endswith(".session.stdout") or entry.endswith(".task.stdout")):
            continue
        stdout_path = os.path.join(task_folder, entry)
        if not os.path.isfile(stdout_path):
            continue

        sid, spid = parse_stdout_filename(entry)
        if sid is None or spid is None:
            continue
        if session_id is not None and sid != session_id:
            continue
        if pid is not None and spid != pid:
            continue

        socket_path = build_socket_path(sid, spid)

        try:
            mtime = os.path.getmtime(stdout_path)
        except OSError:
            continue

        targets.append((socket_path, mtime))

    targets.sort(key=lambda x: x[1], reverse=True)
    return [socket_path for socket_path, _ in targets]


def send_control_request(
    socket_path: str,
    action: str,
    payload: dict,
    timeout: float,
) -> Tuple[bool, dict]:
    """Send a ControlRequest to a UDS socket and read the response.

    Args:
        socket_path: Path to the UDS socket.
        action: The raw action name to send.
        payload: JSON object payload for the action.
        timeout: Connection timeout in seconds.

    Returns:
        Tuple of (success, response_dict). On failure, response_dict contains
        an "error" key.
    """
    request = {
        "request_id": uuid.uuid4().hex,
        "action": action,
        "payload": payload,
    }
    request_bytes = json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n"

    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(timeout)
            sock.connect(socket_path)
            sock.sendall(request_bytes)

            file_obj = sock.makefile("r")
            try:
                line = file_obj.readline()
            finally:
                file_obj.close()

            if not line:
                return False, {"error": "server closed connection without response"}

            try:
                response = json.loads(line)
            except json.JSONDecodeError as e:
                return False, {"error": f"invalid json response: {e}"}

            if not isinstance(response, dict):
                return False, {"error": "response is not a json object"}

            return True, response
    except socket.timeout:
        return False, {"error": f"connection to {socket_path} timed out"}
    except OSError as e:
        return False, {"error": f"failed to connect to {socket_path}: {e}"}


def format_human_response(response: dict) -> str:
    """Format a control response for human-readable output."""
    status = response.get("status", "unknown")
    request_id = response.get("request_id", "")
    if status == "ok":
        result = response.get("result")
        if result is None:
            return f"[{status}] request_id={request_id}"
        return f"[{status}] request_id={request_id} result={json.dumps(result, ensure_ascii=False)}"
    error = response.get("error", "unknown error")
    return f"[{status}] request_id={request_id} error={error}"


def get_params() -> dict:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Send control messages to running TopsailAI sessions through UDS."
    )
    parser.add_argument(
        "-s",
        "--session_id",
        dest="session_id",
        type=str,
        default=None,
        help="Target session ID. If omitted, all sessions are scanned.",
    )
    parser.add_argument(
        "-p",
        "--pid",
        dest="pid",
        type=str,
        default=None,
        help="Target process ID. If omitted, all PIDs are scanned.",
    )
    parser.add_argument(
        "-c",
        "--command",
        dest="command",
        type=str,
        required=True,
        help="Control action name to send (e.g. hard_interrupt, soft_interrupt, clear_interrupt, get_runtime_messages).",
    )
    parser.add_argument(
        "-a",
        "--args",
        dest="args",
        type=str,
        default="{}",
        help='JSON string payload for the action. Default "{}".',
    )
    parser.add_argument(
        "--socket-path",
        dest="socket_path",
        type=str,
        default=None,
        help="Override the UDS socket path. When set, --session_id and --pid are ignored.",
    )
    parser.add_argument(
        "--timeout",
        dest="timeout",
        type=float,
        default=5.0,
        help="Socket connection timeout in seconds. Default 5.0.",
    )
    parser.add_argument(
        "--json",
        dest="json_output",
        action="store_true",
        default=False,
        help="Output the raw server response as JSON.",
    )

    args = parser.parse_args()

    try:
        payload = json.loads(args.args)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid --args JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(payload, dict):
        print("[ERROR] --args must be a JSON object.", file=sys.stderr)
        sys.exit(1)

    return {
        "session_id": args.session_id,
        "pid": args.pid,
        "command": args.command,
        "payload": payload,
        "socket_path": args.socket_path,
        "timeout": args.timeout,
        "json_output": args.json_output,
    }


def main() -> int:
    params = get_params()

    socket_path_override = params["socket_path"]
    if socket_path_override:
        targets = [os.path.abspath(socket_path_override)]
    else:
        targets = discover_socket_paths(
            FOLDER_WORKSPACE_TASK,
            session_id=params["session_id"],
            pid=params["pid"],
        )

    if not targets:
        print(
            f"[ERROR] No matching session/task stdout file found in {FOLDER_WORKSPACE_TASK}.",
            file=sys.stderr,
        )
        return 1

    success_count = 0
    last_error = ""
    for socket_path in targets:
        success, response = send_control_request(
            socket_path,
            params["command"],
            params["payload"],
            params["timeout"],
        )

        if params["json_output"]:
            print(json.dumps(response, ensure_ascii=False))
        else:
            print(format_human_response(response))

        if success and response.get("status") == "ok":
            success_count += 1
        else:
            last_error = response.get("error", "request failed")

    if success_count == 0:
        if len(targets) > 1:
            print(f"[ERROR] All {len(targets)} targets failed. Last error: {last_error}", file=sys.stderr)
        return 1

    if len(targets) > 1:
        print(f"[INFO] {success_count}/{len(targets)} targets succeeded.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
