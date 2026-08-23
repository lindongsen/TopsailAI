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


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    """Parse memory reconciliation command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_memory_reconcile",
        description="Reconcile memory stat records with Markdown memories.",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Report planned actions without changing files (default: enabled).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    """Run memory reconciliation and print its structured summary."""
    args = _parse_args(argv)
    try:
        summary = story_memory_tool.reconcile_memories(dry_run=args.dry_run)
    except Exception as exc:
        print(f"Error: memory reconciliation failed: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
