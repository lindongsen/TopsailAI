#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Display story memories in most-recently-used order.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import OrderedDict

try:
    from . import _import_topsailai
except ImportError:
    import _import_topsailai

from topsailai.tools import story_memory_tool

MAX_TOKENS_ENV = "TOPSAILAI_CONTEXT_MEMORY_LOAD_MAX_TOKENS"
SORT_DESCRIPTION = (
    "newest last_activity_at first, then newest created_at, then memory_id"
)


def non_negative_int(value: str) -> int:
    """Parse a non-negative integer for an argparse option."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a non-negative integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be a non-negative integer")
    return parsed


def default_max_tokens() -> int:
    """Read the existing startup-memory token budget from the environment."""
    return story_memory_tool._parse_max_tokens(os.getenv(MAX_TOKENS_ENV))


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_memory_top",
        description=(
            "Display top story memories in most-recently-used order without "
            "updating their read statistics."
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=non_negative_int,
        default=default_max_tokens(),
        metavar="TOKENS",
        help=(
            "Maximum cumulative content tokens; 0 means unlimited "
            f"(default: {MAX_TOKENS_ENV}, then 0)."
        ),
    )
    parser.add_argument(
        "--max-count",
        type=non_negative_int,
        default=0,
        metavar="COUNT",
        help="Maximum number of memories to print; 0 means unlimited (default: 0).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the ordered memories and selection details as JSON.",
    )
    return parser.parse_args(argv)


def load_top_memories(max_tokens: int, max_count: int) -> OrderedDict:
    """Load MRU-ranked memories and apply the optional count bound."""
    memories = story_memory_tool._load_memories_lru(max_tokens)
    if max_count == 0:
        return memories
    return OrderedDict(list(memories.items())[:max_count])


def build_result(max_tokens: int, max_count: int) -> dict:
    """Build the structured CLI result while preserving memory order."""
    total_count = len(story_memory_tool.list_memories() or [])
    memories = load_top_memories(max_tokens, max_count)
    current_count = len(memories)
    return {
        "max_tokens": max_tokens,
        "max_count": max_count,
        "sort": SORT_DESCRIPTION,
        "current_count": current_count,
        "total_count": total_count,
        "memories": [
            {"title": title, "content": content}
            for title, content in memories.items()
        ],
    }


def format_text(result: dict) -> str:
    """Format top memories as a Markdown document with YAML frontmatter."""
    sort = json.dumps(result["sort"], ensure_ascii=False)
    lines = [
        "---",
        f"max_tokens: {result['max_tokens']}",
        f"max_count: {result['max_count']}",
        f"current_count: {result['current_count']}",
        f"total_count: {result['total_count']}",
        f"sort: {sort}",
        "---",
        "",
        "# Top Memories",
        "",
        "## Titles",
        "",
    ]
    lines.extend(
        f"{index}. {memory['title']}"
        for index, memory in enumerate(result["memories"], start=1)
    )
    lines.extend(("", "## Memories"))
    for memory in result["memories"]:
        lines.extend(("", f"### {memory['title']}", "", memory["content"]))
    return "\n".join(lines)


def main(argv=None) -> int:
    """Run the top-memory CLI."""
    args = parse_args(argv)
    try:
        result = build_result(args.max_tokens, args.max_count)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
