#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Test memory-reference recognition without updating memory statistics.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import json
import sys

try:
    from . import _import_topsailai
except ImportError:
    import _import_topsailai

from topsailai.tools import story_memory_tool
from topsailai.tools.memory_tool_utils import memory_ref_parser

try:
    from ._memory_home import resolve_memory_home
except ImportError:
    from _memory_home import resolve_memory_home


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_test_memory_ref",
        description=(
            "Recognize @memory[...] references without reading memory content "
            "or updating memory statistics."
        ),
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Text to inspect. If omitted, read stdin or prompt interactively.",
    )
    parser.add_argument(
        "--home",
        metavar="PATH",
        help=(
            "TOPSAILAI_HOME or memory root used to list canonical titles "
            "(default: configured memory workspace)."
        ),
    )
    parser.add_argument(
        "--memory-title",
        action="append",
        default=None,
        metavar="TITLE",
        help=(
            "Use this canonical memory title instead of listing the memory "
            "workspace; repeat to test ambiguity."
        ),
    )
    parser.add_argument(
        "--no-bare-title",
        action="store_true",
        help="Disable bare-title fallback for this test run.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON output.",
    )
    return parser.parse_args(argv)


def read_input_text(parts: list[str]) -> str:
    """Read text from arguments, redirected stdin, or an interactive prompt."""
    if parts:
        return " ".join(parts)
    if not sys.stdin.isatty():
        return sys.stdin.read()
    return input("Text containing @memory[...] references: ")


def load_memory_titles(home: str | None, supplied: list[str] | None) -> list[str]:
    """Load canonical titles without reading memory content or statistics."""
    if supplied is not None:
        return supplied
    story_memory_tool.WORKSPACE = resolve_memory_home(home)
    return story_memory_tool.list_memories() or []


def inspect_references(
    text: str,
    titles: list[str],
    *,
    bare_title_enabled: bool,
) -> list[dict[str, str | None]]:
    """Resolve every reference independently and return structured results."""
    index = memory_ref_parser.build_title_index(titles)
    results = []
    for title in memory_ref_parser.parse_memory_refs(text):
        canonical_id, reason = memory_ref_parser.resolve_ref(
            title,
            index,
            bare_title_enabled=bare_title_enabled,
        )
        results.append(
            {
                "reference": title,
                "status": "resolved" if canonical_id is not None else reason,
                "canonical_memory_id": canonical_id,
            }
        )
    return results


def format_text(results: list[dict[str, str | None]]) -> str:
    """Format recognition results for terminal output."""
    if not results:
        return "No @memory[...] references found."

    lines = []
    for index, result in enumerate(results, start=1):
        lines.extend(
            (
                f"Reference {index}: {result['reference']}",
                f"Status: {str(result['status']).upper()}",
                f"Canonical memory id: {result['canonical_memory_id'] or '-'}",
                "",
            )
        )
    return "\n".join(lines).rstrip()


def main(argv=None) -> int:
    """Run the side-effect-free memory-reference recognition test."""
    args = parse_args(argv)
    text = read_input_text(args.text)
    try:
        titles = load_memory_titles(args.home, args.memory_title)
        results = inspect_references(
            text,
            titles,
            bare_title_enabled=not args.no_bare_title,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(format_text(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
