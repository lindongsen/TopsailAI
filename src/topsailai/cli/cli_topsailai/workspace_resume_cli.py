"""Non-interactive persisted-session resume command."""

from __future__ import annotations

import argparse
import sys


class _UniqueValue(argparse.Action):
    """Reject conflicting repetitions while permitting identical values."""

    def __call__(self, parser, namespace, values, option_string=None):
        current = getattr(namespace, self.dest, None)
        if current is not None and current != values:
            raise argparse.ArgumentError(self, f"conflicting {option_string} values")
        setattr(namespace, self.dest, values)


def build_parser() -> argparse.ArgumentParser:
    """Build the strict workspace-resume parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace resume",
        allow_abbrev=False,
        description="Resume one exact persisted session.",
        epilog=(
            "Background mode submits a headless launch and reports submission, "
            "not readiness; the default background mechanism is raw. "
            "No --json output is provided."
        ),
    )
    parser.add_argument("-s", "--session", dest="session_id", required=True,
                        action=_UniqueValue, help="exact persisted session ID")
    parser.add_argument(
        "-m", "--agent-mode", choices=("raw", "dtach", "tmux"),
        default=None, dest="agent_mode", action=_UniqueValue,
        help="agent launch mode (foreground default: dtach; background default: raw)",
    )
    parser.add_argument(
        "-b", "--background", action="store_true",
        help="submit the resume in headless background mode",
    )
    return parser


def run_workspace_resume_cli(argv, *, startup_cwd=None) -> int:
    """Parse and execute one exact persisted-session resume request."""
    try:
        args = build_parser().parse_args(list(argv))
    except SystemExit as error:
        return int(error.code)
    from cli_topsailai.runtime_target import _valid_session

    if not _valid_session(args.session_id):
        print("[ERROR] Invalid session identifier", file=sys.stderr)
        return 2

    from cli_topsailai.project_scope import resume_session_result

    options = {
        "agent_mode": args.agent_mode or ("raw" if args.background else "dtach"),
        "background": args.background,
    }
    if startup_cwd is not None:
        options["entrypoint_base"] = startup_cwd
    return resume_session_result(args.session_id, **options)
