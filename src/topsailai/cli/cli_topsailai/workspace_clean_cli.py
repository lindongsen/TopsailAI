"""Non-interactive cleanup of expired workspace session files.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from pathlib import Path
import sys
import time
from typing import Callable, List, Optional

from cli_topsailai.cleaning import (
    EXPIRED_AGE_SECONDS,
    collect_expired_files,
    delete_collected_files,
)
from cli_topsailai.colors import Colors, cprint
from cli_topsailai.formatting import format_size, format_timestamp_full
from cli_topsailai.log_files import (
    SessionSelectorError,
    discover_log_files,
    parse_pid_selector,
    parse_session_selector,
)
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_cli import RuntimeUsageError, UniqueValue
from cli_topsailai.workspace_receipt import (
    emit_failure,
    emit_receipt,
    json_requested,
    new_receipt,
)

#: Exit code for a usage error, matching the other workspace subcommands.
_USAGE_ERROR = 2
#: Exit code for a deletion that failed for at least one file.
_DELETE_FAILED = 1
#: Exit code for an inspection that could not read the task directory.
_INSPECTION_FAILED = 1


def build_parser() -> argparse.ArgumentParser:
    """Build the strict non-interactive ``workspace clean`` parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace clean",
        description=(
            "List or delete expired workspace session files. "
            "Nothing is deleted without --yes."
        ),
        allow_abbrev=False,
    )
    # ``UniqueValue`` decides conflicts by ``hasattr``, so both selectors must
    # use ``SUPPRESS``: a real default would look like an already-set value and
    # make the first occurrence of the option conflict with itself.
    parser.add_argument(
        "-s", "--session",
        dest="session", default=argparse.SUPPRESS, action=UniqueValue,
        metavar="ID1,ID2",
        help="only consider the listed comma-separated session IDs",
    )
    parser.add_argument(
        "-p", "--pid",
        dest="pid", type=str, default=argparse.SUPPRESS, action=UniqueValue,
        metavar="PID1,PID2",
        help="only consider the listed comma-separated session PIDs",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="delete the listed files instead of only previewing them",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON receipt on stdout, including failures",
    )
    return parser


def _human_stream(json_mode: bool):
    """Return the stream human diagnostics must use.

    In JSON mode every human line goes to stderr, so stdout holds exactly one
    parseable receipt and a machine consumer never has to strip text.
    """
    return sys.stderr if json_mode else sys.stdout


def _print_header(title: str, stream) -> None:
    """Print the same header shape as ``formatting.print_header`` to *stream*.

    ``print_header`` writes to stdout only, so a machine-readable caller needs
    this local variant to keep its single-document stdout contract.
    """
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}", file=stream)
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}", file=stream)
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}", file=stream)


def _age_hours(entry: dict) -> float:
    """Return the file's age in hours, computed from its modification time.

    The shared inventory helper rebuilds each record while expanding related
    files, so a precomputed ``age_hours`` field is not guaranteed to survive.
    Deriving the age from ``mtime`` keeps the table and the JSON record correct
    regardless of which path produced the entry.
    """
    mtime = entry.get("mtime")
    if not isinstance(mtime, (int, float)):
        return 0.0
    return max(0.0, (time.time() - mtime) / 3600)


def _print_candidates(entries: List[dict], stream) -> None:
    """Print the candidate table without any confirmation prompt."""
    _print_header("Clean Expired Log Files", stream)
    cprint(
        f"[WARN] The following {len(entries)} file(s) are idle "
        f"and older than {EXPIRED_AGE_SECONDS // 86400} days:\n",
        color=Colors.YELLOW,
        file=stream,
    )

    w_no = 4
    w_name = 32
    w_size = 10
    w_time = 20
    w_age = 12

    print(
        f" {'No':^{w_no}} | {'Filename':^{w_name}} | {'Size':^{w_size}} | "
        f"{'Modified':^{w_time}} | {'Age':^{w_age}} ",
        file=stream,
    )
    print(
        f"{'-' * (w_no + 1)}+{'-' * (w_name + 2)}+{'-' * (w_size + 2)}+"
        f"{'-' * (w_time + 2)}+{'-' * (w_age + 1)}",
        file=stream,
    )

    for index, entry in enumerate(entries, start=1):
        name = entry["filename"]
        if len(name) > w_name:
            name = name[:w_name - 3] + "..."
        age_hours = _age_hours(entry)
        print(
            f" {index:^{w_no}} | {name:<{w_name}} | "
            f"{format_size(entry['size']):>{w_size}} | "
            f"{format_timestamp_full(entry['mtime']):^{w_time}} | "
            f"{age_hours:>{w_age}.1f}h ",
            file=stream,
        )


def _candidate_record(entry: dict) -> dict:
    """Build one stable JSON record for a cleanup candidate."""
    return {
        "filename": entry["filename"],
        "path": entry["path"],
        "size": entry["size"],
        "mtime": entry["mtime"],
        "age_hours": round(_age_hours(entry), 2),
    }


def _emit_result(
    json_mode: bool,
    *,
    exit_code: int,
    delivery_state: str,
    message: str,
    candidates: List[dict],
    deleted: List[str],
    failed: List[dict],
    selectors: Optional[dict] = None,
    error_code: Optional[str] = None,
) -> None:
    """Emit one receipt describing exactly what was listed and deleted."""
    if not json_mode:
        return
    receipt = new_receipt("clean")
    receipt.update(
        ok=exit_code == 0,
        exit_code=exit_code,
        delivery_state=delivery_state,
        error_code=error_code,
        message=message,
        response={
            "expired_age_seconds": EXPIRED_AGE_SECONDS,
            "selectors": selectors or {"session_ids": None, "pids": None},
            "candidates": candidates,
            "candidate_count": len(candidates),
            "deleted": deleted,
            "deleted_count": len(deleted),
            "failed": failed,
            "failed_count": len(failed),
        },
    )
    emit_receipt(receipt)


def run_workspace_clean_cli(
    argv,
    *,
    home_resolver: Optional[Callable[[], str]] = None,
    discover: Callable[[str], List[dict]] = discover_log_files,
) -> int:
    """List or delete expired workspace session files without prompting.

    The command previews by default and deletes only when ``--yes`` is given,
    because a non-interactive caller must never trigger an irreversible action
    through an implicit default. Every deletion reuses the same liveness and
    launch-lease guards as the interactive ``/clean`` command.

    Args:
        argv: Arguments after ``workspace clean``.
        home_resolver: Optional ``TOPSAILAI_HOME`` resolver for tests.
        discover: Optional log-file discovery function for tests.

    Returns:
        ``0`` for a preview, an empty inventory or a complete deletion, ``1``
        when a deletion or the inspection failed, ``2`` for a usage error.
    """
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except RuntimeUsageError:
        # ``UniqueValue`` rejects a conflicting repeat of the same option.
        if json_mode:
            emit_failure("clean", _USAGE_ERROR, "usage_error",
                         "Invalid clean arguments")
        else:
            print("[ERROR] Invalid clean arguments", file=sys.stderr)
        return _USAGE_ERROR
    except SystemExit as error:
        code = int(error.code)
        if json_mode and code != 0:
            emit_failure("clean", code, "usage_error", "Invalid clean arguments")
        return code

    try:
        session_ids = parse_session_selector(getattr(args, "session", None))
        pids = parse_pid_selector(getattr(args, "pid", None))
    except SessionSelectorError as error:
        message = f"Invalid selector: {error}"
        if json_mode:
            emit_failure("clean", _USAGE_ERROR, "usage_error", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _USAGE_ERROR
    # Record the effective selectors so a machine consumer can confirm which
    # filter produced this inventory instead of inferring it from the rows.
    selectors = {"session_ids": session_ids, "pids": pids}

    home = Path((home_resolver or get_topsailai_home)()).resolve()
    task_dir = str(home / "workspace" / "task")
    stream = _human_stream(json_mode)

    try:
        files = discover(task_dir)
    except OSError as error:
        message = f"Cannot read the task directory: {type(error).__name__}: {error}"
        if json_mode:
            emit_failure("clean", _INSPECTION_FAILED, "inspection_failed", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _INSPECTION_FAILED

    # The shared inventory and deletion helpers print their own skip warnings.
    # Redirecting stdout keeps those lines out of a JSON receipt while leaving
    # the interactive command's behaviour untouched.
    with redirect_stdout(stream):
        candidates = collect_expired_files(
            task_dir, files, session_ids=session_ids, pids=pids
        )
    records = [_candidate_record(entry) for entry in candidates]

    if not candidates:
        message = (
            "No expired session files found. "
            f"Files must be idle and older than {EXPIRED_AGE_SECONDS // 86400} days."
        )
        cprint(f"[INFO] {message}", color=Colors.GREEN, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="nothing_to_delete",
            message=message, candidates=[], deleted=[], failed=[],
            selectors=selectors,
        )
        return 0

    _print_candidates(candidates, stream)

    if not args.yes:
        message = (
            f"{len(candidates)} file(s) are eligible; nothing was deleted. "
            "Re-run with --yes to delete them."
        )
        cprint(f"\n[INFO] {message}", color=Colors.YELLOW, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="preview", message=message,
            candidates=records, deleted=[], failed=[], selectors=selectors,
        )
        return 0

    with redirect_stdout(stream):
        deleted_paths, failures = delete_collected_files(task_dir, candidates)
    failed = [{"filename": name, "error": error} for name, error in failures]

    if not deleted_paths and not failures:
        # Every candidate was skipped by the mutation-time revalidation, so
        # nothing was removed. Reporting "deleted" here would claim an effect
        # that never happened.
        message = (
            "No file was deleted: every candidate was skipped because it "
            "changed or its owner became active."
        )
        cprint(f"\n[INFO] {message}", color=Colors.YELLOW, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="nothing_to_delete",
            message=message, candidates=records, deleted=[], failed=[],
            selectors=selectors,
        )
        return 0

    exit_code = _DELETE_FAILED if failures else 0
    delivery_state = "partial" if failures else "deleted"
    message = (
        f"Clean complete: {len(deleted_paths)} deleted, {len(failures)} failed."
    )
    cprint(f"\n[INFO] {message}", color=Colors.GREEN, file=stream)
    _emit_result(
        json_mode, exit_code=exit_code, delivery_state=delivery_state,
        message=message, candidates=records, deleted=deleted_paths,
        failed=failed, selectors=selectors,
        error_code="delete_failed" if failures else None,
    )
    return exit_code
