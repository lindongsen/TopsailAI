#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preview synchronized story-memory eviction without deleting files."""

import argparse
import json
import sys

try:
    from . import _import_topsailai
except ImportError:
    import _import_topsailai

from topsailai.tools import story_memory_tool
from topsailai.tools.memory_tool_utils import memory_evict, memory_stat
try:
    from ._memory_home import resolve_memory_home
except ImportError:
    from _memory_home import resolve_memory_home

SORT_DESCRIPTION = "oldest last_activity_at first, then lexicographic memory_id"


def positive_int(value: str) -> int:
    """Parse a strictly positive integer for an argparse option."""
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive integer") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return parsed


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_memory_evict",
        description=(
            "Preview old synchronized story memories that exceed the retention "
            "limit. Memories are ordered by least-recent activity, but this "
            "command never deletes files."
        ),
        epilog=(
            "Use topsailai_memory_delete to delete a reviewed memory explicitly. "
            "Example: topsailai_memory_evict --max-count 50 --json"
        ),
    )
    parser.add_argument(
        "--home",
        metavar="PATH",
        help=(
            "TOPSAILAI_HOME; memory resolves to {home}/memory "
            "(default: TOPSAILAI_HOME/memory)."
        ),
    )
    parser.add_argument(
        "--max-count",
        type=positive_int,
        default=100,
        metavar="COUNT",
        help=(
            "Maximum healthy synchronized memory/stat pairs to retain; older "
            "excess pairs are reported as eviction candidates (default: 100)."
        ),
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the dry-run summary and candidate list as JSON.",
    )
    return parser.parse_args(argv)


def resolve_home(value: str | None) -> str:
    """Resolve an optional TOPSAILAI_HOME to its memory root."""
    return resolve_memory_home(value)


def collect_victims(workspace: str, max_count: int) -> list[dict]:
    """Collect ordered victim metadata without modifying memory files."""
    victims = []
    for memory_file, stat_file in memory_evict.select_eviction_victims(
        workspace, max_count
    ):
        stat = memory_stat.read_memory_stat_file(stat_file)
        victims.append(
            {
                "memory_id": stat["memory_id"],
                "last_activity_at": stat["last_activity_at"],
                "synced": memory_stat.is_memory_synced(stat),
            }
        )
    return victims


def build_result(workspace: str, max_count: int) -> dict:
    """Run the dry-run engine and build the CLI result payload."""
    victims = collect_victims(workspace, max_count)
    summary = memory_evict.maybe_evict_memory_stats(
        workspace, max_count, dry_run=True
    ).to_dict()
    return {
        "workspace": workspace,
        "max_count": max_count,
        "dry_run": True,
        "sort": SORT_DESCRIPTION,
        "victims": victims,
        "summary": summary,
    }


def format_text(result: dict) -> str:
    """Format a dry-run result for human-readable terminal output."""
    lines = [
        "Memory eviction dry-run",
        f"Workspace: {result['workspace']}",
        f"Max count: {result['max_count']}",
        f"Sort: {result['sort']}",
        f"Victims: {len(result['victims'])}",
    ]
    for victim in result["victims"]:
        lines.append(
            "- memory_id={memory_id} last_activity_at={last_activity_at} "
            "synced={synced}".format(**victim)
        )
    summary = result["summary"]
    lines.append(
        "Summary: scanned={scanned} eligible={eligible} would_evict={evicted} "
        "protected_unsynced={protected_unsynced} errors={errors}".format(**summary)
    )
    lines.append("No files were deleted.")
    return "\n".join(lines)


def main(argv=None) -> int:
    """Run the always-dry-run memory eviction preview CLI."""
    args = parse_args(argv)
    workspace = resolve_home(args.home)
    try:
        result = build_result(workspace, args.max_count)
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
