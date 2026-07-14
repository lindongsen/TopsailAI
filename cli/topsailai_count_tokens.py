#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Count tokens for text or file content."""

import argparse
import os
import sys

# Allow importing from the parent project's source tree.
CLI_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.join(os.path.dirname(CLI_DIR), "src")
if os.path.isdir(SRC_DIR):
    sys.path.insert(0, SRC_DIR)

from topsailai.context.token import count_tokens


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_count_tokens",
        description="Count tokens for the provided text or file content.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--text",
        type=str,
        help="Raw text to count tokens for.",
    )
    group.add_argument(
        "--file",
        type=str,
        help="Path to a file whose content will be counted.",
    )
    parser.add_argument(
        "--encoding",
        type=str,
        default="cl100k_base",
        help="Tiktoken encoding name to use (default: cl100k_base).",
    )
    return parser.parse_args()


def read_file(path: str) -> str:
    """Read text from a file using UTF-8 encoding."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main() -> int:
    """Entry point for the token counting CLI."""
    args = parse_args()

    if args.file is not None:
        if not os.path.isfile(args.file):
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            return 1
        text = read_file(args.file)
    else:
        text = args.text

    token_count = count_tokens(text, encoding_name=args.encoding)
    print(token_count)
    return 0


if __name__ == "__main__":
    sys.exit(main())
