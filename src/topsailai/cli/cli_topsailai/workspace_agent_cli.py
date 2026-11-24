"""Non-interactive workspace agent command."""

from __future__ import annotations

import argparse
import contextlib
import os
import sys
from typing import Optional

from cli_topsailai.launch_parameters import (
    LaunchParameterError,
    parse_env_overrides,
    validate_session_id,
)
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
                "reports submission rather than readiness. --non-interactive suppresses "
                "launcher prompts for this launch only. --driver selects the agent driver "
                "the launcher runs instead of the settings.yaml ai_agent_driver. "
                "--session-id fixes the launched session identity instead of minting one; "
                "an identity that is live or unverifiable is refused rather than reused. "
                "--env KEY=VALUE supplies a launch environment value that outranks "
                "settings.yaml, and may be repeated. --json emits one receipt on "
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
    parser.add_argument(
        "--task", metavar="MESSAGE", default=None,
        help="provide the initial user task so the launched agent starts without prompting",
    )
    parser.add_argument(
        "--non-interactive", action="store_true", dest="non_interactive",
        help="never prompt while the launcher resolves its configuration; "
             "this affects the launch only and does not change the agent's "
             "own interactive mode",
    )
    parser.add_argument(
        "--driver", metavar="DRIVER", default=None,
        help="run this agent driver instead of the settings.yaml ai_agent_driver; "
             "the value is passed to the launcher as its own --driver flag, so "
             "settings.yaml context injection still happens",
    )
    parser.add_argument(
        "--session-id", metavar="ID", default=None, dest="session_id",
        help="fix the launched session identity instead of minting one; "
             "the value must match [A-Za-z0-9_-]{1,128} and must not contain a "
             "dot, because session filenames are parsed by splitting on dots",
    )
    parser.add_argument(
        "--env", metavar="KEY=VALUE", action="append", default=None,
        dest="env_overrides",
        help="set one launch environment value for the agent; repeatable, and "
             "the value outranks the target project's settings.yaml; "
             "TOPSAILAI_SESSION_ID and SESSION_ID are rejected because "
             "--session-id owns the identity",
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


def _identity_conflict(session_id: str) -> Optional[str]:
    """Return why a caller-fixed identity cannot be reused, or ``None``.

    A live session must never be silently replaced, and an unverifiable one
    must fail closed, because the caller cannot tell a stale artifact from a
    running agent. An idle identity is allowed: its artifacts are per-PID, so a
    fresh launch under the same name never overwrites the previous run's
    evidence.
    """
    from cli_topsailai.process_liveness import session_liveness

    state = session_liveness(session_id)
    if state == "live":
        return f"Session {session_id} is already running"
    if state == "unknown":
        return f"Session {session_id} liveness cannot be verified"
    return None


def _receipt_response(facts: dict, driver: Optional[str] = None,
                      env_names: Optional[list] = None) -> dict:
    """Publish only the launch facts that were actually established.

    *driver* is published only when the caller selected one, so a launch that
    inherits the settings.yaml driver keeps its historical receipt shape.
    *env_names* publishes the overridden variable names only, never their
    values, so a caller can confirm which variables it set without the receipt
    disclosing them.
    """
    response = {
        "workspace": facts.get("workspace"),
        "mode": facts.get("mode"),
        "background": facts.get("background"),
        "resumed": facts.get("resumed"),
        "launcher_pid": facts.get("launcher_pid"),
        "log_path": facts.get("log_path"),
        "startup_confirmed": facts.get("startup_confirmed", False),
        "child_exit_code": facts.get("child_exit_code"),
    }
    if env_names:
        response["env_overrides"] = list(env_names)
    if driver is not None:
        response["driver"] = driver
    return response


def _refuse_identity(session_id: str, facts: dict) -> Optional[int]:
    """Refuse a caller-fixed identity that cannot be reused.

    The refusal is recorded in *facts* so the JSON path can name the reason
    instead of reporting a generic preparation failure, and it is printed for
    the text path because the launch boundary returns the status silently.
    """
    message = _identity_conflict(session_id)
    if message is None:
        return None
    facts["identity_conflict"] = message
    print(f"[ERROR] Agent launch refused: {message}", file=sys.stderr)
    return 4


def run_workspace_agent_cli(argv, *, startup_cwd: Optional[str] = None) -> int:
    """Parse and launch one configured agent without entering the watcher."""
    json_mode = json_requested(argv)
    try:
        parser = build_parser()
        args = parser.parse_args(list(argv))
        json_mode = args.json
        if args.task is not None and not args.task.strip():
            parser.error("--task must contain a non-whitespace message")
        modes = args.agent_mode or []
        mode = modes[0] if modes else None
        target = _resolve_folder(args.folder, startup_cwd)
        # Both caller-supplied launch parameters are validated before any
        # process is spawned, so a rejected request leaves no partial launch.
        session_id = (
            validate_session_id(args.session_id)
            if args.session_id is not None else None
        )
        env_overrides = parse_env_overrides(args.env_overrides)
    except SystemExit as error:
        code = int(error.code)
        # Help stays ordinary text; only a real usage failure becomes a receipt.
        if json_mode and code != 0:
            emit_failure("agent", code, "usage_error", "Invalid agent arguments")
        return code
    except LaunchParameterError as error:
        if json_mode:
            emit_failure("agent", 2, "usage_error", str(error))
        else:
            print(f"[ERROR] Invalid agent arguments: {error}", file=sys.stderr)
        return 2
    except WorkspaceAgentError as error:
        if json_mode:
            emit_failure("agent", 3, "invalid_folder", str(error))
        else:
            print(f"[ERROR] Agent launch failed: {error}", file=sys.stderr)
        return 3

    from cli_topsailai.agent_launch import launch_configured_agent

    task_kwargs = {"task": args.task} if args.task is not None else {}
    driver_kwargs = {"launcher_driver": args.driver} if args.driver is not None else {}
    identity_kwargs = {"session_id": session_id} if session_id is not None else {}
    env_kwargs = {"env_overrides": env_overrides} if env_overrides else {}
    env_names = sorted(env_overrides) if env_overrides else None

    facts: dict = {}
    # A fixed identity is refused before preparation, and rechecked at the
    # launch boundary so a session that started in between is still protected.
    if session_id is not None:
        refusal = _refuse_identity(session_id, facts)
        if refusal is not None:
            if json_mode:
                emit_failure(
                    "agent", refusal, "identity_conflict",
                    facts["identity_conflict"], session_id=session_id,
                )
            return refusal
    prelaunch_check = (
        (lambda: _refuse_identity(session_id, facts))
        if session_id is not None else None
    )
    check_kwargs = (
        {"prelaunch_check": prelaunch_check} if prelaunch_check is not None else {}
    )

    if not json_mode:
        return launch_configured_agent(
            target,
            mode=mode,
            background=args.background,
            entrypoint_base=startup_cwd or os.getcwd(),
            non_interactive=args.non_interactive,
            **task_kwargs,
            **driver_kwargs,
            **identity_kwargs,
            **env_kwargs,
            **check_kwargs,
        )

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
            non_interactive=args.non_interactive,
            **task_kwargs,
            **driver_kwargs,
            **identity_kwargs,
            **env_kwargs,
            **check_kwargs,
        )
    if facts.get("identity_conflict"):
        # The late revalidation refused the launch, so the receipt names the
        # refusal instead of reporting a generic preparation failure.
        emit_failure(
            "agent", code, "identity_conflict", facts["identity_conflict"],
            session_id=session_id,
        )
        return code
    receipt = new_receipt(
        "agent", session_id=facts.get("session_id") or session_id,
        pid=facts.get("launcher_pid"),
    )
    settle(receipt, code, AGENT_ERROR_CODES)
    receipt["response"] = _receipt_response(facts, args.driver, env_names)
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
