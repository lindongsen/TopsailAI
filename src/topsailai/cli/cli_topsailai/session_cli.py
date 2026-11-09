"""Non-interactive session operations that mirror session scope.

Session scope is a stateful interactive context, so it cannot be entered by a
one-shot subcommand.  This module exposes the stateless equivalents instead:
inspect a session, list sessions, read its context, search its context, append a
persistent message, and read its lock-based processing state.

Operations that already exist under ``topsailai runtime`` are deliberately not
duplicated here.  ``runtime`` acts on a live session (send, btw, control, logs);
``session`` reads and updates the session's stored record.

Author: DawsonLin
"""

import argparse
import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

from cli_topsailai.runtime_cli import RuntimeUsageError, UniqueValue

# Scripts that expose ``main(argv)`` and can therefore run in-process.
_SESSION_INFO = "topsailai_session_info"
_SESSIONS_INFO = "topsailai_sessions_info"
_RETRIEVE_MESSAGES = "topsailai_retrieve_messages"

# Scripts that parse ``sys.argv`` directly and must run as child processes.
_SESSION_LIST = "topsailai_session_list"
_SESSION_STATUS = "topsailai_session_status"
_AGENT_CALL_INSTRUCTION = "topsailai_agent_call_instruction"
_SESSION_ADD_MESSAGE = "topsailai_session_add_message"

# Exit status used when a required child command is not installed.
_COMMAND_MISSING = 127

# One shared explanation for ``--json``. Every subcommand that accepts the flag
# reuses this sentence so the help text states the contract once instead of
# repeating a slightly different wording per subcommand.
_JSON_HELP = "emit one structured JSON result instead of human-readable text"

class SessionUsageError(ValueError):
    """Reject syntax without exposing submitted values in diagnostics."""


class SessionParser(argparse.ArgumentParser):
    """Keep parser failures inside the structured session output contract."""

    def __init__(self, *args, **kwargs):
        """Keep epilog examples readable rather than filling terminal width."""
        kwargs.setdefault("formatter_class", argparse.RawDescriptionHelpFormatter)
        super().__init__(*args, **kwargs)

    def error(self, message):
        """Avoid argparse diagnostics that could echo message values."""
        raise SessionUsageError("Invalid session arguments")


def _run_script(command: str, argv: List[str]) -> int:
    """Run one child CLI script with inherited streams and return its status."""
    try:
        completed = subprocess.run(
            [command, *argv],
            stdin=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        print(f"[ERROR] Command not found: {command}", file=sys.stderr)
        return _COMMAND_MISSING
    except OSError as error:
        print(f"[ERROR] Unable to run {command}: {error}", file=sys.stderr)
        return _COMMAND_MISSING
    return completed.returncode


def _capture_script(command: str, argv: List[str]) -> Tuple[int, str, str]:
    """Run one child CLI script and capture its output for structured reuse."""
    try:
        completed = subprocess.run(
            [command, *argv],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return _COMMAND_MISSING, "", f"Command not found: {command}"
    except OSError as error:
        return _COMMAND_MISSING, "", f"Unable to run {command}: {error}"
    return completed.returncode, completed.stdout, completed.stderr


def _info_options(args) -> List[str]:
    """Translate shared detail options into the child script's own flags."""
    options: List[str] = []
    if getattr(args, "json", False):
        options.append("--json")
    if getattr(args, "no_color", False):
        options.append("--no-color")
    db_conn = getattr(args, "db_conn", None)
    if db_conn is not None:
        options.extend(["--db-conn", db_conn])
    home = getattr(args, "home", None)
    if home is not None:
        options.extend(["--home", home])
    return options


def _handle_info(args) -> int:
    """Show one session's detail, or several sessions' detail in one call."""
    session_ids = args.session_ids
    options = _info_options(args)
    if len(session_ids) == 1:
        import topsailai_session_info as module

        return module.main([session_ids[0], *options])
    import topsailai_sessions_info as module

    return module.main([*session_ids, *options])


def _handle_list(args) -> int:
    """List stored sessions through the existing session-list command."""
    argv: List[str] = []
    if args.json:
        argv.append("--json")
    if args.no_color:
        argv.append("--no-color")
    if args.has_project:
        argv.append("--has-project")
    category = getattr(args, "category", None)
    if category is not None:
        argv.extend(["--category", category])
    limit = getattr(args, "limit", None)
    if limit is not None:
        argv.extend(["--limit", str(limit)])
    offset = getattr(args, "offset", None)
    if offset is not None:
        argv.extend(["--offset", str(offset)])
    sort = getattr(args, "sort", None)
    if sort is not None:
        argv.extend(["--sort", sort])
    db_conn = getattr(args, "db_conn", None)
    if db_conn is not None:
        argv.extend(["--db-conn", db_conn])
    return _run_script(_SESSION_LIST, argv)


def _handle_status(args) -> int:
    """Report the lock-based idle or processing state of one session."""
    code, stdout, stderr = _capture_script(_SESSION_STATUS, ["-s", args.session_id])
    state = stdout.strip()
    if args.json:
        document = {
            "ok": code == 0,
            "exit_code": code,
            "action": "status",
            "session_id": args.session_id,
            "state": state or None,
            "error_code": None if code == 0 else "status_unavailable",
            "message": None if code == 0 else (stderr.strip() or "Status unavailable"),
        }
        print(json.dumps(document, ensure_ascii=True))
        return code
    if code != 0:
        if stderr.strip():
            print(stderr.strip(), file=sys.stderr)
        return code
    print(state)
    return 0


def _history_argv(args) -> List[str]:
    """Translate the history options into the backing script's own flags."""
    argv: List[str] = [args.session_id]
    db_conn = getattr(args, "db_conn", None)
    if db_conn is not None:
        argv.append(db_conn)
    max_chars = getattr(args, "max_chars", None)
    if max_chars is not None:
        argv.extend(["--max-chars", str(max_chars)])
    return argv


def _history_document(args, code: int, messages, error_code, message) -> dict:
    """Build the single structured result of one history read."""
    return {
        "ok": code == 0,
        "exit_code": code,
        "action": "history",
        "session_id": args.session_id,
        "message_count": None if messages is None else len(messages),
        "messages": messages,
        "error_code": error_code,
        "message": message,
    }


def _handle_history_json(args) -> int:
    """Read one session's history and print it as one structured JSON object.

    The child is asked for its own JSON array so the stored message objects are
    parsed rather than re-parsed from a human-readable report. A child failure
    or an unusable document is reported as a classified result instead of being
    printed as a partial document.
    """
    argv = [*_history_argv(args), "--json"]
    code, stdout, stderr = _capture_script(_RETRIEVE_MESSAGES, argv)
    if code == _COMMAND_MISSING:
        document = _history_document(
            args, code, None, "command_missing",
            stderr.strip() or f"Command not found: {_RETRIEVE_MESSAGES}",
        )
        print(json.dumps(document, ensure_ascii=True))
        return code
    if code != 0:
        document = _history_document(
            args, code, None, "history_unavailable",
            stderr.strip() or "Unable to read the session history",
        )
        print(json.dumps(document, ensure_ascii=True))
        return code
    try:
        messages = json.loads(stdout)
    except ValueError:
        messages = None
    if not isinstance(messages, list):
        document = _history_document(
            args, 1, None, "history_unavailable",
            "The retrieval command returned an unusable document",
        )
        print(json.dumps(document, ensure_ascii=True))
        return 1
    print(json.dumps(_history_document(args, 0, messages, None, None),
                     ensure_ascii=True))
    return 0


def _handle_history(args) -> int:
    """Print the stored context messages of one session.

    The backing script changes the working directory while it is imported and
    resolves its default database relative to that directory, so it must run as
    a child process instead of being imported into this one.
    """
    if getattr(args, "json", False):
        return _handle_history_json(args)
    return _run_script(_RETRIEVE_MESSAGES, _history_argv(args))


def _handle_search(args) -> int:
    """Search one session's context by keyword through its registered command."""
    return _run_script(
        _AGENT_CALL_INSTRUCTION,
        ["-s", args.session_id, "-i", "/ctx.search", "-p", args.keyword],
    )


def _handle_add_msg(args) -> int:
    """Append one persistent user-to-agent message to a session."""
    message = args.message
    if not message.strip():
        raise SessionUsageError("Message cannot be empty")
    code = _run_script(_SESSION_ADD_MESSAGE, ["-s", args.session_id, "-m", message])
    if args.json:
        document = {
            "ok": code == 0,
            "exit_code": code,
            "action": "add-msg",
            "session_id": args.session_id,
            "message_bytes": len(message.encode("utf-8")),
            "error_code": None if code == 0 else "append_failed",
            "message": None if code == 0 else "Unable to append the message",
        }
        print(json.dumps(document, ensure_ascii=True))
    return code


#: On-disk identity of a temporary session; the display layer shows ``(temp)``.
_TEMP_SESSION_ID = "topsailai"
_TEMP_DISPLAY_ID = "(temp)"

#: Exit status used when the exact target is not a deletable invalid stdout.
_TARGET_INVALID = 3
#: Exit status used when the file exists but removal failed.
_DELETE_FAILED = 4


def _on_disk_session_id(session_id: str) -> str:
    """Translate the display sentinel of a temporary session to its file prefix."""
    if session_id == _TEMP_DISPLAY_ID:
        return _TEMP_SESSION_ID
    return session_id


def _valid_pid(pid: object) -> bool:
    """Return whether *pid* is a usable positive process identifier."""
    if isinstance(pid, bool) or not isinstance(pid, int):
        return False
    return 0 < pid <= 2147483647


def _invalid_stdout_target(task_dir, session_id, pid, *, pid_state, in_use,
                           heartbeat=None):
    """Prove one stdout file is an invalid leftover before it is deleted.

    Returns ``(path, None, None)`` when the file may be deleted, otherwise
    ``(None, error_code, message)``.  Liveness is three-state on purpose: an
    unverifiable owner is refused, because "cannot prove it is gone" is not
    "it is gone".

    The control channel is consulted first.  A session may run in a sibling
    container that shares this filesystem, so the local process table cannot
    see its owner and would report a live session as dead.  A heartbeat that
    answers is therefore the strongest proof of liveness, and it is the only
    probe that crosses that boundary.
    """
    from cli_topsailai.process_liveness import ProcessState

    path = os.path.join(task_dir, f"{session_id}.{pid}.session.stdout")
    # A session identity is a filename component, never a path. Reject any
    # value that escapes the task directory so a crafted identity cannot
    # reach an unrelated file.
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(task_dir):
        return None, "target_not_found", "No such session stdout file"
    if not os.path.isfile(path):
        return None, "target_not_found", "No such session stdout file"
    if heartbeat is not None and heartbeat(session_id, pid) is True:
        return None, "target_alive", "The control channel answered a heartbeat"
    state = pid_state(pid)
    if state is ProcessState.ALIVE:
        return None, "target_alive", "The owning process is still alive"
    if state is not ProcessState.DEAD:
        return None, "target_identity_unavailable", "Cannot prove the owning process is gone"
    if in_use(path):
        return None, "file_in_use", "Another process still holds the file open"
    return path, None, None


def _handle_delete(args) -> int:
    """Delete one invalid session stdout located precisely by session ID and PID."""
    from cli_topsailai.log_files import is_file_in_use
    from cli_topsailai.paths import get_topsailai_home
    from cli_topsailai.process_liveness import pid_state, socket_heartbeat_alive

    if not _valid_pid(args.pid):
        raise SessionUsageError("PID must be a positive integer")
    session_id = _on_disk_session_id(args.session_id)
    home = getattr(args, "home", None) or get_topsailai_home()
    task_dir = os.path.join(home, "workspace", "task")

    def heartbeat(target_session_id, target_pid):
        """Probe the control channel of the exact target identity."""
        return socket_heartbeat_alive(target_session_id, target_pid, home=home)

    path, error_code, message = _invalid_stdout_target(
        task_dir, session_id, args.pid, pid_state=pid_state, in_use=is_file_in_use,
        heartbeat=heartbeat,
    )
    if error_code is not None:
        if args.json:
            print(json.dumps({
                "ok": False, "exit_code": _TARGET_INVALID, "action": "delete",
                "session_id": args.session_id, "pid": args.pid,
                "error_code": error_code, "message": message,
            }, ensure_ascii=True))
        else:
            print(
                f"[ERROR] Cannot delete session={args.session_id}, PID={args.pid}: {message}",
                file=sys.stderr,
            )
        return _TARGET_INVALID

    try:
        os.remove(path)
    except OSError as error:
        if args.json:
            print(json.dumps({
                "ok": False, "exit_code": _DELETE_FAILED, "action": "delete",
                "session_id": args.session_id, "pid": args.pid,
                "error_code": "delete_failed",
                "message": f"{type(error).__name__}: {error}",
            }, ensure_ascii=True))
        else:
            print(
                f"[ERROR] Failed to delete {path}: {type(error).__name__}: {error}",
                file=sys.stderr,
            )
        return _DELETE_FAILED

    # A deletion must always be logged, so the removed path stays auditable.
    # In JSON mode the log goes to stderr so stdout stays machine-parseable.
    print(
        f"[INFO] Deleted invalid session stdout: {path}",
        file=sys.stderr if args.json else sys.stdout,
    )

    from cli_topsailai.session_cleanup import find_related_files

    remaining = find_related_files(task_dir, f"{session_id}.{args.pid}")
    if args.json:
        print(json.dumps({
            "ok": True, "exit_code": 0, "action": "delete",
            "session_id": args.session_id, "pid": args.pid,
            "path": path, "error_code": None, "message": None,
            "remaining_related_files": remaining,
        }, ensure_ascii=True))
    elif remaining:
        print(
            f"[INFO] {len(remaining)} related file(s) remain and are now orphaned; "
            "the existing orphan cleanup removes them."
        )
    return 0


def _add_detail_options(parser) -> None:
    """Add the options shared by every command that reads a session record."""
    parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    parser.add_argument("--no-color", action="store_true",
                        help="disable colored output")
    parser.add_argument("--db-conn", dest="db_conn", action=UniqueValue,
                        default=argparse.SUPPRESS,
                        help="override the session database connection string")
    parser.add_argument("--home", dest="home", action=UniqueValue,
                        default=argparse.SUPPRESS,
                        help="override the TOPSAILAI_HOME directory")


def build_parser() -> SessionParser:
    """Build the offline session parser without touching any session record."""
    parser = SessionParser(
        prog="topsailai session", allow_abbrev=False,
        description="Inspect and update one session without entering session scope",
        epilog=(
            "Examples:\n"
            "  topsailai session info 20261107021807\n"
            "  topsailai session info 20261107021807 20261106093012 --json\n"
            "  topsailai session list --limit 20\n"
            "  topsailai session status 20261107021807 --json\n"
            "  topsailai session history 20261107021807 --max-chars 200\n"
            "  topsailai session history 20261107021807 --json\n"
            "  topsailai session search 20261107021807 timeout\n"
            "  topsailai session add-msg 20261107021807 -m 'please retry'\n"
            "  topsailai session delete 20261107021807 2175537\n\n"
            "--json is accepted by every command that prints a result and emits\n"
            "one structured JSON object instead of human-readable text.\n\n"
            "Session scope is interactive and stateful, so it cannot be entered "
            "by a subcommand. These commands are its stateless equivalents.\n"
            "Operations on a live session belong to: topsailai runtime\n"
            "Usage documents: topsailai docs read topsailai_session.md"
        ),
    )
    subparsers = parser.add_subparsers(dest="action", metavar="ACTION")

    info_parser = subparsers.add_parser(
        "info", help="show one session's detail, or several in one call",
        description="Show one session's detail, or several sessions' detail in one call.",
    )
    info_parser.add_argument("session_ids", nargs="+", metavar="SESSION_ID",
                             help="one or more session identifiers")
    _add_detail_options(info_parser)

    list_parser = subparsers.add_parser(
        "list", help="list stored sessions",
        description="List stored sessions from the session database.",
    )
    list_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    list_parser.add_argument("--no-color", action="store_true",
                             help="disable colored output")
    list_parser.add_argument("--has-project", dest="has_project", action="store_true",
                             help="only include sessions with a project workspace")
    list_parser.add_argument("--category", dest="category", action=UniqueValue,
                             default=argparse.SUPPRESS,
                             help="filter by exact category")
    list_parser.add_argument("--limit", type=int, action=UniqueValue,
                             default=argparse.SUPPRESS,
                             help="return at most N sessions")
    list_parser.add_argument("--offset", type=int, action=UniqueValue,
                             default=argparse.SUPPRESS,
                             help="skip the first N sessions")
    list_parser.add_argument("--sort", choices=("asc", "desc"), action=UniqueValue,
                             default=argparse.SUPPRESS,
                             help="sort by creation time (default: asc)")
    list_parser.add_argument("--db-conn", dest="db_conn", action=UniqueValue,
                             default=argparse.SUPPRESS,
                             help="override the session database connection string")

    status_parser = subparsers.add_parser(
        "status", help="report the lock-based idle or processing state",
        description=(
            "Report the lock-based idle or processing state of one session. "
            "This reads the session lock, so it answers whether a task currently "
            "holds the session; it is not the process-liveness status reported "
            "by 'session info'."
        ),
    )
    status_parser.add_argument("session_id", metavar="SESSION_ID",
                               help="the session identifier to check")
    status_parser.add_argument("--json", action="store_true", help=_JSON_HELP)

    history_parser = subparsers.add_parser(
        "history", help="print the stored context messages of one session",
        description="Print the stored context messages of one session.",
    )
    history_parser.add_argument("session_id", metavar="SESSION_ID",
                                help="the session identifier to read")
    history_parser.add_argument("--max-chars", dest="max_chars", type=int,
                                action=UniqueValue, default=argparse.SUPPRESS,
                                help="truncate each displayed message to N characters")
    history_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    history_parser.add_argument("--db-conn", dest="db_conn", action=UniqueValue,
                                default=argparse.SUPPRESS,
                                help="override the session database connection string")

    search_parser = subparsers.add_parser(
        "search", help="search one session's context by keyword",
        description=(
            "Search one session's context by keyword. This invokes the "
            "registered /ctx.search instruction, which runs one agent turn."
        ),
    )
    search_parser.add_argument("session_id", metavar="SESSION_ID",
                               help="the session identifier to search")
    search_parser.add_argument("keyword", metavar="KEYWORD",
                               help="the keyword to search for")

    add_msg_parser = subparsers.add_parser(
        "add-msg", help="append one persistent message to a session",
        description=(
            "Append one persistent user-to-agent message to a session. The "
            "message is delivered on the session's next agent run."
        ),
    )
    add_msg_parser.add_argument("session_id", metavar="SESSION_ID",
                                help="the session identifier to append to")
    add_msg_parser.add_argument("-m", "--message", dest="message", required=True,
                                action=UniqueValue, default=argparse.SUPPRESS,
                                help="the message text to append")
    add_msg_parser.add_argument("--json", action="store_true", help=_JSON_HELP)

    delete_parser = subparsers.add_parser(
        "delete", help="delete one invalid session stdout by session ID and PID",
        description=(
            "Delete exactly one invalid session stdout file, located by session "
            "ID and PID. The file is deleted only after its owning process is "
            "proven dead and no process holds it open; a live or unverifiable "
            "owner is refused. Related stderr, pipe and inject files are left "
            "for the existing orphan cleanup."
        ),
    )
    delete_parser.add_argument("session_id", metavar="SESSION_ID",
                               help="the session identifier; use (temp) for a temporary session")
    delete_parser.add_argument("pid", metavar="PID", type=int,
                               help="the exact PID embedded in the stdout filename")
    delete_parser.add_argument("--json", action="store_true", help=_JSON_HELP)
    delete_parser.add_argument("--home", dest="home", action=UniqueValue,
                               default=argparse.SUPPRESS,
                               help="override the TOPSAILAI_HOME directory")
    return parser


_HANDLERS = {
    "info": _handle_info,
    "list": _handle_list,
    "status": _handle_status,
    "history": _handle_history,
    "search": _handle_search,
    "add-msg": _handle_add_msg,
    "delete": _handle_delete,
}


def run_session_cli(argv: Optional[List[str]] = None) -> int:
    """Dispatch one non-interactive session operation and return its status."""
    arguments = list(argv or [])
    parser = build_parser()
    if not arguments or arguments[0] in ("-h", "--help"):
        # A bare invocation is a request for guidance, not an incomplete
        # operation: show the same help as --help and succeed.
        parser.print_help()
        return 0
    try:
        args = parser.parse_args(arguments)
        handler = _HANDLERS.get(args.action)
        if handler is None:
            raise SessionUsageError("Missing session action")
        return handler(args)
    except (SessionUsageError, RuntimeUsageError):
        print("Session failed: usage_error (exit 2)", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        raise
    except (OSError, ValueError) as error:
        print(f"Session failed: operation_failed (exit 4): {error}", file=sys.stderr)
        return 4
