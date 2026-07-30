#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse and format LLM responses using the shared format_response helper."""

import argparse
import json
import os
import sys

import _import_topsailai

from topsailai.ai_base.llm_control.message import format_response
from topsailai.utils.format_tool import to_topsailai_format

# change PWD after importing topsailai
PWD = os.getenv("TOPSAILAI_PWD")
if PWD:
    os.chdir(PWD)

print(f"OPENAI_MODEL: {os.getenv("OPENAI_MODEL")}")

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


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_format_response",
        description="Format an LLM response into the standardized internal list format.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--text",
        type=str,
        help="Raw response text to format.",
    )
    group.add_argument(
        "--file",
        type=str,
        help="Path to a file containing the response to format.",
    )
    parser.add_argument(
        "files",
        nargs="*",
        help="Paths to files containing responses to format. Use '-' to read from stdin.",
    )
    parser.add_argument(
        "--format",
        type=str,
        default="json",
        choices=("json", "topsailai"),
        help="Output format (default: json).",
    )
    parser.add_argument(
        "--indent",
        type=int,
        default=2,
        help="Indentation level for JSON output (default: 2).",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Output compact JSON instead of pretty-printed JSON.",
    )
    return parser.parse_args(argv)


def read_file(path: str) -> str:
    """Read text from a file using UTF-8 encoding."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def read_input(path: str) -> str:
    """Read text from a file or stdin when path is '-'."""
    if path == "-":
        return sys.stdin.read()
    return read_file(path)


def format_output(data, fmt: str, indent: int, compact: bool) -> str:
    """Serialize formatted response data to the requested output format."""
    if fmt == "topsailai":
        return to_topsailai_format(data, key_name="step_name", value_name="raw_text", for_print=True)
    if compact:
        return json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return json.dumps(data, ensure_ascii=False, indent=indent)


def format_response_text(text: str, fmt: str = "json", indent: int = 2, compact: bool = False) -> str:
    """Format a single response string and return output in the requested format."""
    print("\n--- calling format_response ---")
    data = format_response(text)
    print("\n--- outputing ---")
    return format_output(data, fmt, indent, compact)


def main(argv=None) -> int:
    """Entry point for the response formatting CLI."""
    args = parse_args(argv)

    if args.text is not None:
        if args.files:
            print(
                "Error: --text cannot be used with positional file arguments.",
                file=sys.stderr,
            )
            return 2
        try:
            print(format_response_text(args.text, args.format, args.indent, args.compact))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
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
        try:
            text = read_file(file_path)
            print(format_response_text(text, args.format, args.indent, args.compact))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        return 0

    if not args.files:
        print(
            "Error: provide --text, --file, or one or more file paths.",
            file=sys.stderr,
        )
        return 2

    exit_code = 0
    for path in args.files:
        print(f"\n>>> {path}")
        if path == "-":
            text = sys.stdin.read()
            try:
                print(format_response_text(text, args.format, args.indent, args.compact))
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                exit_code = 1
            continue
        resolved = resolve_path(path)
        if not os.path.isfile(resolved):
            print(f"Error: file not found: {path}", file=sys.stderr)
            exit_code = 1
            continue
        try:
            text = read_file(resolved)
            print(format_response_text(text, args.format, args.indent, args.compact))
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            exit_code = 1

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
