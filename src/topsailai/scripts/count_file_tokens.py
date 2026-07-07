#!/usr/bin/env python3
"""
Count tokens in a file using the project's token-counting utilities.

Usage:
    python -m topsailai.scripts.count_file_tokens <file_path> [--encoding ENCODING]
    python /TopsailAI/src/topsailai/scripts/count_file_tokens.py <file_path> [--encoding ENCODING]

Examples:
    python -m topsailai.scripts.count_file_tokens /path/to/file.txt
    python -m topsailai.scripts.count_file_tokens /path/to/file.txt --encoding gpt2
"""

import argparse
import sys

from topsailai.context.token import count_tokens


def main():
    parser = argparse.ArgumentParser(
        description="Read a file and calculate its token count."
    )
    parser.add_argument("file_path", help="Path to the file to tokenize.")
    parser.add_argument(
        "--encoding",
        default="cl100k_base",
        help="tiktoken encoding name (default: cl100k_base).",
    )
    args = parser.parse_args()

    try:
        with open(args.file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        print(f"Error: file not found: {args.file_path}", file=sys.stderr)
        return 1
    except OSError as e:
        print(f"Error: failed to read {args.file_path}: {e}", file=sys.stderr)
        return 1

    token_count = count_tokens(content, encoding_name=args.encoding)
    print(f"{token_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
