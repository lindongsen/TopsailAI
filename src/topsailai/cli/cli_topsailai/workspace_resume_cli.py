"""Non-interactive persisted-session resume command."""

from __future__ import annotations

import argparse
import contextlib
import sys

from cli_topsailai.workspace_receipt import (
    RESUME_ERROR_CODES,
    emit_failure,
    emit_receipt,
    json_requested,
    launch_delivery_state,
    new_receipt,
    settle,
)


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
            "not readiness; the default background mechanism is raw. --json "
            "emits one receipt on stdout and redirects other output to stderr."
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
    parser.add_argument(
        "-d", "--driver",
        choices=("topsailai_agent_chats", "topsailai_agent_plan_tasks", "ai-team-flow-dev"),
        default=None, action=_UniqueValue,
        help="resume driver (default: topsailai_agent_chats)",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="emit one JSON receipt on stdout, including failures",
    )
    return parser


def _receipt_response(facts: dict) -> dict:
    """Publish only resume facts established during execution."""
    return {
        "workspace": facts.get("workspace"),
        "mode": facts.get("mode"),
        "driver": facts.get("driver"),
        "background": facts.get("background"),
        "resumed": facts.get("resumed"),
        "launcher_pid": facts.get("launcher_pid"),
        "log_path": facts.get("log_path"),
        "startup_confirmed": facts.get("startup_confirmed", False),
        "startup_pid": facts.get("startup_pid"),
        "startup_reason": facts.get("startup_reason"),
        "child_exit_code": facts.get("child_exit_code"),
        "cleaned_stdout": facts.get("cleaned_stdout", []),
    }


def run_workspace_resume_cli(argv, *, startup_cwd=None) -> int:
    """Parse and execute one exact persisted-session resume request."""
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except SystemExit as error:
        code = int(error.code)
        if json_mode and code != 0:
            emit_failure("resume", code, "usage_error", "Invalid resume arguments")
        return code
    from cli_topsailai.runtime_target import _valid_session

    if not _valid_session(args.session_id):
        if json_mode:
            emit_failure(
                "resume", 2, "usage_error", "Invalid session identifier",
                session_id=args.session_id,
            )
        else:
            print("[ERROR] Invalid session identifier", file=sys.stderr)
        return 2

    from cli_topsailai.project_scope import resume_session_result

    options = {
        "agent_mode": args.agent_mode or ("raw" if args.background else "dtach"),
        "background": args.background,
    }
    if args.driver is not None:
        options["driver"] = args.driver
    if startup_cwd is not None:
        options["entrypoint_base"] = startup_cwd
    if not json_mode:
        return resume_session_result(args.session_id, **options)

    facts: dict = {}
    with contextlib.redirect_stdout(sys.stderr):
        code = resume_session_result(
            args.session_id, **options, receipt=facts, child_stdout=sys.stderr,
        )
    receipt = new_receipt(
        "resume", session_id=args.session_id,
        pid=facts.get("launcher_pid"),
    )
    settle(receipt, code, RESUME_ERROR_CODES)
    receipt["response"] = _receipt_response(facts)
    receipt["delivery_state"] = launch_delivery_state(facts, code)
    if receipt["delivery_state"] == "delivery_unknown":
        receipt["delivery_unknown"] = True
        receipt["message"] = "Resume effects are uncertain; do not retry blindly"
    elif facts.get("startup_confirmed") and code == 0:
        receipt["message"] = "Resume confirmed; the agent answered on its control channel"
    elif code == 0:
        receipt["message"] = "Resume not confirmed; the agent did not answer"
    emit_receipt(receipt)
    return code
