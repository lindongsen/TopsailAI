"""Non-interactive workspace agent command."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from typing import Optional

from cli_topsailai.workspace_receipt import (
    AGENT_ERROR_CODES,
    emit_failure,
    emit_receipt,
    json_requested,
    launch_delivery_state,
    new_receipt,
    settle,
)


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
        epilog=("The folder is optional and defaults to the caller's working directory. "
                "Foreground mode attaches to the launcher. Background mode is headless and "
                "reports submission rather than readiness. --json emits one receipt on "
                "stdout and redirects all other output to stderr."),
    )
    parser.add_argument(
        "folder", nargs="?", default=None,
        help="agent workspace folder (default: the caller's working directory)",
    )
    parser.add_argument(
        "-m", "--agent-mode", choices=("raw", "dtach", "tmux"),
        action=_ModeAction, default=None,
    )
    parser.add_argument(
        "-b", "--background", action="store_true",
        help="submit a headless launch under a detached supervisor "
             "(default mechanism: raw)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit one JSON receipt on stdout, including failures",
    )
    return parser


def _resolve_folder(folder: Optional[str], startup_cwd: Optional[str]) -> str:
    """Resolve and validate a folder against the caller's startup directory.

    An omitted folder means the caller's working directory: the startup
    directory when the dispatcher recorded one, otherwise the current
    process working directory.
    """
    base = startup_cwd or os.getcwd()
    if folder is None:
        target = os.path.abspath(base)
    else:
        expanded = os.path.expanduser(folder)
        target = expanded if os.path.isabs(expanded) else os.path.join(base, expanded)
        target = os.path.abspath(target)
    if not os.path.isdir(target):
        raise WorkspaceAgentError(f"Folder is not a directory: {target}")
    return target


def _receipt_response(facts: dict) -> dict:
    """Publish only the launch facts that were actually established."""
    return {
        "workspace": facts.get("workspace"),
        "mode": facts.get("mode"),
        "background": facts.get("background"),
        "resumed": facts.get("resumed"),
        "launcher_pid": facts.get("launcher_pid"),
        "log_path": facts.get("log_path"),
        "startup_confirmed": facts.get("startup_confirmed", False),
        "child_exit_code": facts.get("child_exit_code"),
    }


def run_workspace_agent_cli(argv, *, startup_cwd: Optional[str] = None) -> int:
    """Parse and launch one configured agent without entering the watcher."""
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
        modes = args.agent_mode or []
        mode = modes[0] if modes else None
        target = _resolve_folder(args.folder, startup_cwd)
    except SystemExit as error:
        code = int(error.code)
        # Help stays ordinary text; only a real usage failure becomes a receipt.
        if json_mode and code != 0:
            emit_failure("agent", code, "usage_error", "Invalid agent arguments")
        return code
    except WorkspaceAgentError as error:
        if json_mode:
            emit_failure("agent", 3, "invalid_folder", str(error))
        else:
            print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
        return 3

    from cli_topsailai.agent_launch import launch_configured_agent

    if not json_mode:
        return launch_configured_agent(
            target,
            mode=mode,
            background=args.background,
            entrypoint_base=startup_cwd or os.getcwd(),
        )

    facts: dict = {}
    # stdout must carry exactly one document, so every human-readable line and
    # the launched agent's own output are redirected to stderr.
    with contextlib.redirect_stdout(sys.stderr):
        code = launch_configured_agent(
            target,
            mode=mode,
            background=args.background,
            entrypoint_base=startup_cwd or os.getcwd(),
            receipt=facts,
            child_stdout=sys.stderr,
        )
    receipt = new_receipt(
        "agent", session_id=facts.get("session_id"),
        pid=facts.get("launcher_pid"),
    )
    settle(receipt, code, AGENT_ERROR_CODES)
    receipt["response"] = _receipt_response(facts)
    receipt["delivery_state"] = launch_delivery_state(facts, code)
    if receipt["delivery_state"] == "delivery_unknown":
        receipt["delivery_unknown"] = True
        receipt["message"] = "Launch effects are uncertain; do not retry blindly"
    elif receipt["delivery_state"] == "submitted" and code == 0:
        receipt["message"] = "Launch submitted; startup is not confirmed"
    elif receipt["delivery_state"] == "launcher_exited" and code == 0:
        receipt["message"] = (
            "Launcher exited; a wrapper exit is not agent completion"
        )
    emit_receipt(receipt)
    return code
