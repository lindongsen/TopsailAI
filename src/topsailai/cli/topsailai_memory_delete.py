#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Delete a specific story memory and its stat record.

Author: DawsonLin
Email: lin_dongsen@126.com
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

try:
    from . import _import_topsailai
except ImportError:
    import _import_topsailai

from topsailai.tools import story_memory_tool
try:
    from ._memory_home import resolve_memory_home
except ImportError:
    from _memory_home import resolve_memory_home


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_memory_delete",
        description="Delete a specific story memory and its stat record.",
    )
    parser.add_argument(
        "title",
        help=(
            "Memory id (filename stem) to delete, e.g. "
            "20260101T000000.My_Memory. May include the '.md' suffix."
        ),
    )
    parser.add_argument(
        "--home",
        help=(
            "TOPSAILAI_HOME; memory resolves to {home}/memory "
            "(default: TOPSAILAI_HOME/memory)."
        ),
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the confirmation prompt.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output structured JSON instead of human-readable text.",
    )
    return parser.parse_args(argv)


def resolve_home(value: Optional[str]) -> str:
    """Resolve an optional TOPSAILAI_HOME to its memory root."""
    return resolve_memory_home(value)


def resolve_memory_file(workspace: str, title: str) -> Optional[str]:
    """Resolve the exact memory file path for a title, or None if absent."""
    return story_memory_tool.StoryFileInstance.get_story_file(
        workspace, title, must_only_one=True
    )


def confirm_deletion(title: str, memory_file: str) -> bool:
    """Prompt the user for confirmation before deleting a memory."""
    if not sys.stdin.isatty():
        return False
    print(f"[WARN] Delete memory '{title}' ({memory_file})? [y/N]")
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = "n"
    return answer in ("y", "yes")


def build_result(
    workspace: str, title: str, memory_file: Optional[str], deleted: bool
) -> dict:
    """Build the CLI result payload."""
    return {
        "workspace": workspace,
        "title": title,
        "memory_file": memory_file,
        "deleted": deleted,
    }


def main(argv: Optional[list[str]] = None) -> int:
    """Run the memory deletion CLI."""
    args = parse_args(argv)
    workspace = resolve_home(args.home)
    # Bind the resolved workspace onto the module so delete_memory targets it.
    story_memory_tool.WORKSPACE = workspace

    try:
        memory_file = resolve_memory_file(workspace, args.title)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if not memory_file:
        message = f"No memory found for title: {args.title}"
        if args.json:
            print(
                json.dumps(
                    {
                        "workspace": workspace,
                        "title": args.title,
                        "memory_file": None,
                        "deleted": False,
                        "error": message,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"Error: {message}", file=sys.stderr)
        return 1

    if not args.yes and not confirm_deletion(args.title, memory_file):
        if args.json:
            print(
                json.dumps(
                    {
                        "workspace": workspace,
                        "title": args.title,
                        "memory_file": memory_file,
                        "deleted": False,
                        "confirmed": False,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print("Aborted: deletion cancelled.")
        return 0

    try:
        deleted = story_memory_tool.delete_memory(args.title)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    result = build_result(workspace, args.title, memory_file, deleted)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"Deleted memory: {args.title}")
        print(f"Memory file: {memory_file}")
        print(f"Workspace: {workspace}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
