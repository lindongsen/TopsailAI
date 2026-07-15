#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Count tokens for text or file content."""

import argparse
import os
import sys

import _import_topsailai

from topsailai.context.token import count_tokens

# change PWD after importing topsailai
PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)


def resolve_path(path: str) -> str:
    """Resolve a relative path against the original TOPSAILAI_PWD.

    Importing the parent project's source tree may change the current working
    directory (for example to TOPSAILAI_HOME). To keep file arguments working
    when invoked through the dispatcher script, relative paths are resolved
    against the directory where the user ran the command.
    """
    pwd = os.getenv("TOPSAILAI_PWD")
    if pwd and not os.path.isabs(path):
        return os.path.join(os.path.abspath(pwd), path)
    return path


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_count_tokens",
        description="Count tokens for the provided text or file content.",
    )
    group = parser.add_mutually_exclusive_group()
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
        "files",
        nargs="*",
        help="Paths to files whose content will be counted.",
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


def count_file(path: str, encoding: str) -> int:
    """Read a file and return its token count."""
    text = read_file(path)
    return count_tokens(text, encoding_name=encoding)


def main() -> int:
    """Entry point for the token counting CLI."""
    args = parse_args()

    if args.text is not None:
        if args.files:
            print(
                "Error: --text cannot be used with positional file arguments.",
                file=sys.stderr,
            )
            return 2
        print(count_tokens(args.text, encoding_name=args.encoding))
        return 0

    if args.file is not None:
        if args.files:
            print(
                "Error: --file cannot be used with positional file arguments.",
                file=sys.stderr,
            )
            return 2
        file_path = resolve_path(args.file)
        if not os.path.isfile(file_path):
            print(f"Error: file not found: {args.file}", file=sys.stderr)
            return 1
        print(count_file(file_path, args.encoding))
        return 0

    if not args.files:
        print(
            "Error: provide --text, --file, or one or more file paths.",
            file=sys.stderr,
        )
        return 2

    exit_code = 0
    for path in args.files:
        resolved = resolve_path(path)
        if not os.path.isfile(resolved):
            print(f"Error: file not found: {path}", file=sys.stderr)
            exit_code = 1
            continue
        token_count = count_file(resolved, args.encoding)
        print(f"{token_count} {path}")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
