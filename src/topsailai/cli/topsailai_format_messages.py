#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run message data through TopsailAI's real format_messages pipeline."""

import argparse
import copy
import json
import os
import sys

try:
    import _import_topsailai  # noqa: F401
    from topsailai.ai_base.llm_control.message import format_messages
    from topsailai.utils.format_tool import parse_topsailai_format
except ImportError as exc:
    print(
        "Error: unable to import TopsailAI. Run this CLI from the project "
        f"source tree and install its dependencies: {exc}",
        file=sys.stderr,
    )
    sys.exit(1)


ORIGINAL_CWD = os.getenv("TOPSAILAI_PWD") or os.getcwd()
SYSTEM_MESSAGE = {
    "role": "system",
    "content": "Use the proprietary topsailai.xxx message format.",
}


def parse_args(argv=None) -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        prog="topsailai_format_messages",
        description="Run a JSON message list through the real format_messages function.",
    )
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--messages",
        help="Inline JSON array of messages. Reads stdin when omitted.",
    )
    source.add_argument(
        "--file",
        help="UTF-8 JSON file containing an array of messages.",
    )
    source.add_argument(
        "--reverse",
        metavar="TEXT",
        help="Parse a topsailai.xxx formatted string and print the resulting object.",
    )
    parser.add_argument(
        "--no-system",
        action="store_true",
        help="Do not inject the activating system prompt.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Print only the final transformed message list.",
    )
    return parser.parse_args(argv)


def resolve_path(path: str) -> str:
    """Resolve a relative input path against the caller's working directory."""
    if os.path.isabs(path):
        return path
    return os.path.join(ORIGINAL_CWD, path)


def read_message_text(args: argparse.Namespace) -> str:
    """Read message-list JSON from an option, file, or standard input."""
    if args.messages is not None:
        return args.messages
    if args.file is not None:
        with open(resolve_path(args.file), "r", encoding="utf-8") as stream:
            return stream.read()
    return sys.stdin.read()


def load_messages(text: str) -> list[dict]:
    """Parse and validate the message list expected by format_messages."""
    try:
        messages = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"invalid message JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}"
        ) from exc
    if not isinstance(messages, list):
        raise ValueError("message input must be a JSON array")
    for index, message in enumerate(messages):
        if not isinstance(message, dict):
            raise ValueError(f"message {index} must be a JSON object")
        if "role" not in message or "content" not in message:
            raise ValueError(f"message {index} must contain role and content")
        if not isinstance(message["role"], str) or not isinstance(message["content"], str):
            raise ValueError(f"message {index} role and content must be strings")
    return messages


def print_message_details(inputs: list[dict], outputs: list[dict]) -> None:
    """Print input and output content for each caller-provided message."""
    print("MESSAGE TRANSFORMATIONS")
    for index, (source, result) in enumerate(zip(inputs, outputs), start=1):
        print(f"\nMESSAGE {index}")
        print(f"INPUT role={source['role']!r}")
        print(f"INPUT content={source['content']!r}")
        print(f"OUTPUT role={result['role']!r}")
        print(f"OUTPUT content={result['content']!r}")
        try:
            step_name = json.loads(source["content"]).get("step_name")
        except (AttributeError, json.JSONDecodeError):
            step_name = None
        if step_name == "observation":
            converted = result["content"].startswith("topsailai.observation")
            print(f"OBSERVATION -> topsailai.observation: {'YES' if converted else 'NO'}")


def dump_json(value) -> None:
    """Print a value as readable UTF-8 JSON."""
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main(argv=None) -> int:
    """Run the selected forward or reverse formatting operation."""
    args = parse_args(argv)
    if args.reverse is not None:
        dump_json(parse_topsailai_format(args.reverse))
        return 0

    try:
        caller_messages = load_messages(read_message_text(args))
        pipeline_messages = copy.deepcopy(caller_messages)
        if not args.no_system:
            pipeline_messages.insert(0, copy.deepcopy(SYSTEM_MESSAGE))
        elif not pipeline_messages:
            raise ValueError("--no-system requires at least one input message")

        transformed = format_messages(
            pipeline_messages,
            key_name="step_name",
            value_name="raw_text",
        )
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Error: format_messages failed: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        caller_outputs = transformed[-len(caller_messages):]
        print_message_details(caller_messages, caller_outputs)
        print("\nFULL TRANSFORMED MESSAGE LIST")
    dump_json(transformed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
