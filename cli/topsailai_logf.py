#!/usr/bin/env python3
"""Tail the TopsailAI main log file.

Follows ``{TOPSAILAI_HOME}/log/topsailai.log`` by default. With ``-e``
follows ``topsailai.log.ec`` instead. The ``-n`` option is forwarded to
``tail`` as the number of initial lines to display.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Optional

from cli_topsailai.paths import get_topsailai_home


DEFAULT_LINES = 10
LOG_SUBDIR = "log"
DEFAULT_LOG = "topsailai.log"
EC_LOG = "topsailai.log.ec"


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Tail the TopsailAI log file."
    )
    parser.add_argument(
        "-e",
        "--ec",
        action="store_true",
        help="Tail the EC log (topsailai.log.ec) instead of the main log.",
    )
    parser.add_argument(
        "-n",
        "--lines",
        type=int,
        default=DEFAULT_LINES,
        help=f"Number of initial lines to output (default: {DEFAULT_LINES}).",
    )
    parser.add_argument(
        "--home",
        type=str,
        default=None,
        help="Override TOPSAILAI_HOME directory.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """Entry point for ``topsailai_logf``."""
    args = _parse_args(argv)

    home = args.home
    if home is None:
        home = get_topsailai_home()

    filename = EC_LOG if args.ec else DEFAULT_LOG
    log_path = os.path.join(home, LOG_SUBDIR, filename)

    if not os.path.isfile(log_path):
        print(f"[INFO] Log file does not exist yet: {log_path}", file=sys.stderr)

    cmd = ["tail", "-f", "-n", str(args.lines), log_path]
    try:
        return subprocess.call(cmd)
    except FileNotFoundError:
        print("[ERROR] 'tail' command not found in PATH.", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
