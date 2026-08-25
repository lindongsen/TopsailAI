#!/usr/bin/env python3
"""Reconcile memory stat records with their Markdown memories.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

import _import_topsailai

from topsailai.tools import story_memory_tool

try:
    from ._memory_home import resolve_memory_home
except ImportError:
    from _memory_home import resolve_memory_home


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse memory reconciliation command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_memory_reconcile",
        description=(
            "Check consistency between story-memory Markdown files and their "
            "stat JSON records. Missing stats may be rebuilt, orphan stats "
            "purged, and malformed stats quarantined."
        ),
        epilog=(
            "The default is a safe preview. Review the JSON summary first, then "
            "use --no-dry-run to apply repairs, cleanup, and quarantine actions."
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
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help=(
            "Preview planned reconciliation actions without changing files "
            "(default). Use --no-dry-run to apply them."
        ),
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run memory reconciliation and print its structured summary."""
    args = _parse_args(argv)
    story_memory_tool.WORKSPACE = resolve_memory_home(args.home)
    try:
        summary = story_memory_tool.reconcile_memories(dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: memory reconciliation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
