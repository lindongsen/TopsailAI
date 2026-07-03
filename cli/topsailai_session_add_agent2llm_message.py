#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Add a runtime message to Agent2LLM message source JSONL files.

This script writes messages to the file-based Agent2LLM runtime message source
so that a running agent can inject them into the Agent2LLM context before the
next LLM call.

When --session_id and/or --pid are omitted, the script scans
{TOPSAILAI_HOME}/workspace/task/ for files matching
``{session_id}.{pid}.session.stdout`` and derives the JSONL message source
path(s) from each match.
"""

import argparse
import os
import sys
from typing import List, Optional, Tuple

# Add project root to path so we can import topsailai.
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, project_root + "/src")

from topsailai.utils import env_tool
from topsailai.workspace.agent.runtime_message_sources.file import (
    get_default_inject_message_file_path,
    write_message,
)
from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK


JSONL_SUFFIX = ".session.agent2llm_inject_messages.jsonl"


def parse_stdout_filename(filename: str) -> Tuple[Optional[str], Optional[str]]:
    """Parse ``{session_id}.{pid}.session.stdout`` into (session_id, pid).

    Also supports the temporary-session form ``topsailai.{pid}.session.stdout``,
    which yields ``("topsailai", pid)``.

    Returns:
        Tuple of (session_id, pid) strings. Either value may be ``None`` if
        the filename does not match the expected format.
    """
    suffix = ".session.stdout"
    if not filename.endswith(suffix):
        return None, None
    base = filename[: -len(suffix)]
    if not base:
        return None, None

    parts = base.split(".")
    pid = parts[-1]
    if not pid.isdigit():
        return None, None

    session_id = ".".join(parts[:-1]) if len(parts) > 1 else "topsailai"
    return session_id, pid


def build_inject_path(session_id: str, pid: str) -> str:
    """Return the JSONL path that corresponds to a stdout file."""
    return os.path.join(
        FOLDER_WORKSPACE_TASK,
        f"{session_id}.{pid}{JSONL_SUFFIX}",
    )


def get_task_folder() -> str:
    """Return the workspace task folder used for session files."""
    return FOLDER_WORKSPACE_TASK


def discover_jsonl_files(
    task_folder: str,
    session_id: Optional[str] = None,
    pid: Optional[str] = None,
    jsonl_suffix: str = JSONL_SUFFIX,
) -> List[str]:
    """Discover JSONL inject targets from stdout files in the task directory.

    Args:
        task_folder: Directory containing session stdout files.
        session_id: If provided, only match stdout files for this session.
        pid: If provided, only match stdout files for this PID.
        jsonl_suffix: Suffix used to build the JSONL path from a stdout file.

    Returns:
        Sorted list of JSONL file paths for each matching stdout file. The
        list is sorted by stdout file mtime descending so the most recently
        active session comes first.
    """
    targets = []
    if not os.path.isdir(task_folder):
        return targets

    for entry in os.listdir(task_folder):
        if not entry.endswith(".session.stdout"):
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

        inject_path = os.path.join(
            task_folder,
            f"{sid}.{spid}{jsonl_suffix}",
        )
        if not os.path.exists(inject_path):
            continue

        try:
            mtime = os.path.getmtime(stdout_path)
        except OSError:
            continue

        targets.append((inject_path, mtime))

    targets.sort(key=lambda x: x[1], reverse=True)
    return [inject_path for inject_path, _ in targets]


def read_multiline_input() -> str:
    """Read multi-line input until a standalone 'EOF' line is entered."""
    print("[INFO] Enter message (type EOF on its own line to finish):")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        except KeyboardInterrupt:
            print("\n[INFO] Cancelled.")
            sys.exit(130)
        if line == "EOF":
            break
        lines.append(line)
    return "\n".join(lines)


def get_params() -> dict:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Add a runtime message to Agent2LLM message source JSONL files."
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
        "-m",
        "--message",
        dest="message",
        type=str,
        default=None,
        help="Single-line message to inject. If omitted, interactive multi-line input is used.",
    )
    parser.add_argument(
        "--file-path",
        dest="file_path",
        type=str,
        default=None,
        help="Override the JSONL file path. When set, --session_id and --pid are ignored.",
    )

    args = parser.parse_args()
    return {
        "session_id": args.session_id,
        "pid": args.pid,
        "message": args.message,
        "file_path": args.file_path,
    }


def main() -> int:
    params = get_params()
    message = params["message"]
    if message is None:
        message = read_multiline_input()

    if not message:
        print("[ERROR] Message is empty.", file=sys.stderr)
        return 1

    file_path_override = params["file_path"]
    if file_path_override:
        targets = [os.path.abspath(file_path_override)]
    else:
        targets = discover_jsonl_files(
            get_task_folder(),
            session_id=params["session_id"],
            pid=params["pid"],
        )

    if not targets:
        print(
            f"[ERROR] No matching session stdout file found in {get_task_folder()}.",
            file=sys.stderr,
        )
        return 1

    success_count = 0
    for inject_path in targets:
        if write_message(inject_path, message):
            print(f"[INFO] Message written to {inject_path}")
            success_count += 1
        else:
            print(f"[ERROR] Failed to write message to {inject_path}", file=sys.stderr)

    if success_count == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
