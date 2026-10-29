"""Non-interactive workspace agent command."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional


class _ModeAction(argparse.Action):
    """Collect mode options while allowing identical repetitions."""

    def __call__(self, parser, namespace, values, option_string=None):
        modes = list(getattr(namespace, self.dest, None) or [])
        if modes and values not in modes:
            raise argparse.ArgumentError(self, "conflicting --agent-mode values")
        modes.append(values)
        setattr(namespace, self.dest, modes)


class WorkspaceAgentError(ValueError):
    """Raised when a workspace agent request cannot be prepared."""


def build_parser() -> argparse.ArgumentParser:
    """Build the strict workspace-agent parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace agent",
        allow_abbrev=False,
        description="Launch a configured agent in a folder.",
        epilog=("Foreground mode attaches to the launcher. Background mode is headless, "
                "reports submission rather than readiness, and has no --json output."),
    )
    parser.add_argument("folder", help="agent workspace folder")
    parser.add_argument(
        "-m", "--agent-mode", choices=("raw", "dtach", "tmux"),
        action=_ModeAction, default=None,
    )
    parser.add_argument(
        "-b", "--background", action="store_true",
        help="submit a headless launch under a detached supervisor "
             "(default mechanism: raw)",
    )
    return parser


def _resolve_folder(folder: str, startup_cwd: Optional[str]) -> str:
    """Resolve and validate a folder against the caller's startup directory."""
    base = startup_cwd or os.getcwd()
    expanded = os.path.expanduser(folder)
    target = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
    target = os.path.abspath(target)
    if not os.path.isdir(target):
        raise WorkspaceAgentError(f"Folder is not a directory: {target}")
    return target


def run_workspace_agent_cli(argv, *, startup_cwd: Optional[str] = None) -> int:
    """Parse and launch one configured agent without entering the watcher."""
    try:
        args = build_parser().parse_args(list(argv))
        modes = args.agent_mode or []
        mode = modes[0] if modes else None
        target = _resolve_folder(args.folder, startup_cwd)
    except SystemExit as error:
        return int(error.code)
    except WorkspaceAgentError as error:
        print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
        return 3

    from cli_topsailai.agent_launch import launch_configured_agent

    return launch_configured_agent(
        target,
        mode=mode,
        background=args.background,
        entrypoint_base=startup_cwd or os.getcwd(),
    )
