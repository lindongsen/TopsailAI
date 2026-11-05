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
import re
import sys
from typing import Any, List, Optional, Tuple

import _import_topsailai  # noqa: F401

from cli_topsailai.colors import Colors, colored
from cli_topsailai.log_files import parse_stdout_filename
from cli_topsailai.runtime_control import (
    build_socket_path, get_control_actions, send_control_request,
)
from topsailai.workspace.folder_constants import (
    FOLDER_WORKSPACE_TASK,
)


CONTROL_ACTIONS = get_control_actions()


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
        session/task comes first. Only sockets that actually exist on disk are
        returned, avoiding wasted connection attempts.
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

        socket_path = build_socket_path(task_folder, sid, spid)
        if not os.path.exists(socket_path):
            continue

        try:
            mtime = os.path.getmtime(stdout_path)
        except OSError:
            continue

        targets.append((socket_path, mtime))

    targets.sort(key=lambda x: x[1], reverse=True)
    return [socket_path for socket_path, _ in targets]


_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"
)
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


def _sanitize_text(text: str) -> str:
    """Strip ANSI escapes and control characters except newline and tab.

    Control responses originate from the agent process, so a result may carry
    terminal escape sequences. Removing them keeps a human-readable block from
    clearing or recoloring the terminal.
    """
    return _CONTROL_CHAR_RE.sub("", _ANSI_ESCAPE_RE.sub("", text))


def _is_empty_result(result: Any) -> bool:
    """Report whether a result carries nothing worth printing.

    Only an empty result may be hidden; every non-empty result is printed
    regardless of the response status.
    """
    if result is None:
        return True
    if isinstance(result, str):
        return not result.strip()
    if isinstance(result, (dict, list, tuple, set)):
        return len(result) == 0
    return False


def _render_result(result: Any) -> str:
    """Render a non-empty result, preserving real newlines in strings.

    A string result is printed verbatim so instruction help output keeps its
    own indentation and separator widths. Structured results are rendered as
    indented JSON, which is already multi-line.
    """
    if isinstance(result, str):
        return _sanitize_text(result)
    if isinstance(result, (dict, list)):
        return _sanitize_text(json.dumps(result, ensure_ascii=False, indent=2))
    return _sanitize_text(str(result))


def _color_enabled() -> bool:
    """Enable color only on a TTY with NO_COLOR unset."""
    if os.environ.get("NO_COLOR"):
        return False
    try:
        return bool(sys.stdout.isatty())
    except (AttributeError, OSError, ValueError):
        return False


def _paint(text: str, color: str, enabled: bool) -> str:
    """Apply a color only when color output is enabled."""
    return colored(text, color=color) if enabled else text


def format_human_response(response: dict, color: Optional[bool] = None) -> str:
    """Format a control response as readable text.

    A non-empty ``result`` is always printed, whatever the status; only an
    empty result is omitted. ``color`` overrides TTY detection when given.
    """
    if not isinstance(response, dict):
        return _sanitize_text(str(response))
    enabled = _color_enabled() if color is None else color
    status = response.get("status", "unknown")
    request_id = _sanitize_text(str(response.get("request_id", "")))
    status_color = {"ok": Colors.GREEN, "error": Colors.RED}.get(status, Colors.YELLOW)
    lines = [
        f"{_paint('status:', Colors.GRAY, enabled)} "
        f"{_paint(str(status), status_color, enabled)}    "
        f"{_paint('request_id:', Colors.GRAY, enabled)} {request_id}"
    ]
    error = response.get("error")
    if error not in (None, ""):
        lines.append(
            f"{_paint('error:', Colors.GRAY, enabled)} {_sanitize_text(str(error))}"
        )
    result = response.get("result")
    if not _is_empty_result(result):
        lines.append("")
        lines.append(_render_result(result))
    return "\n".join(lines)


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
        choices=CONTROL_ACTIONS,
        help=f"Control action name to send. Supported actions: {', '.join(CONTROL_ACTIONS)}.",
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
        help=(
            "Print the raw server response as JSON instead of readable text. "
            "Use this for scripts; the default output is for humans."
        ),
    )

    args = parser.parse_args()

    args_value = args.args.strip()
    if not args_value:
        args_value = "{}"
    try:
        payload = json.loads(args_value)
    except json.JSONDecodeError as e:
        print(f"[ERROR] Invalid --args JSON {args_value!r}: {e}", file=sys.stderr)
        sys.exit(1)

    if not isinstance(payload, dict):
        print(f"[ERROR] --args must be a JSON object, got {args_value!r}.", file=sys.stderr)
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


def _ensure_session_id_in_payload(params: dict) -> dict:
    """Copy CLI session_id into payload for get_session_messages if absent."""
    if params["command"] != "get_session_messages":
        return params
    session_id = params.get("session_id")
    if session_id is None:
        return params
    payload = params["payload"]
    if payload.get("session_id"):
        return params
    params["payload"] = {**payload, "session_id": session_id}
    return params


def main() -> int:
    params = _ensure_session_id_in_payload(get_params())

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
    errors: List[Tuple[str, str]] = []
    json_output = params["json_output"]
    multiple = len(targets) > 1
    for socket_path in targets:
        success, response = send_control_request(
            socket_path,
            params["command"],
            params["payload"],
            params["timeout"],
        )

        if json_output:
            print(json.dumps(response, ensure_ascii=False, indent=2))
        else:
            if multiple:
                print(f"=== {socket_path} ===")
            print(format_human_response(response))
            if multiple:
                print()

        if success and response.get("status") == "ok":
            success_count += 1
        else:
            errors.append((socket_path, response.get("error", "request failed")))

    if success_count == 0:
        if len(targets) > 1:
            print(
                f"[ERROR] All {len(targets)} targets failed:",
                file=sys.stderr,
            )
            for socket_path, error in errors:
                print(f"  - {socket_path}: {error}", file=sys.stderr)
        return 1

    if len(targets) > 1:
        print(f"[INFO] {success_count}/{len(targets)} targets succeeded.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
