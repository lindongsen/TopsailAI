"""Inspect which session owner records are reclaimable and which are blocked.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import os
import stat
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from cli_topsailai.colors import Colors, cprint
from cli_topsailai.formatting import format_size, format_timestamp_full
from cli_topsailai.log_files import SessionSelectorError, parse_session_selector
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.runtime_cli import RuntimeUsageError, UniqueValue
from cli_topsailai.workspace_receipt import (
    emit_failure,
    emit_receipt,
    json_requested,
    new_receipt,
)

from topsailai.context.session_activity import (
    ActivityState,
    SessionActivityProbe,
    _OWNER_PATTERN,
)

#: Exit code for a usage error, matching the other workspace subcommands.
_USAGE_ERROR = 2
#: Exit code for an inspection that could not read the task directory.
_INSPECTION_FAILED = 1
#: On-disk identity of a temporary session, which the selector spells "(temp)".
_TEMP_SESSION_ID = "topsailai"
_TEMP_SESSION_MARKER = "(temp)"
#: Age in days a record must exceed before it becomes reclaimable.
_DEFAULT_RETENTION_DAYS = 7
#: Default metadata count limit; zero means unlimited.
_DEFAULT_META_MAX_COUNT = 0


def build_parser() -> argparse.ArgumentParser:
    """Build the strict non-interactive ``workspace reclaim`` parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace reclaim",
        description=(
            "Report which session owner records are reclaimable and which are "
            "blocked, with the reason for every blocked session. This command "
            "never deletes anything."
        ),
        allow_abbrev=False,
    )
    # ``UniqueValue`` decides conflicts by ``hasattr``, so the selector must use
    # ``SUPPRESS``: a real default would look like an already-set value and make
    # the first occurrence of the option conflict with itself.
    parser.add_argument(
        "-s", "--session",
        dest="session", default=argparse.SUPPRESS, action=UniqueValue,
        metavar="ID1,ID2",
        help="only inspect the listed comma-separated session IDs",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="report the decision without changing anything (this is the default)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        dest="verbose",
        help="list every owner record of each session with its own expiry verdict",
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


def _retention_days() -> int:
    """Read the core retention setting once at the CLI boundary.

    The value is a core contract owned by the framework, so the unprefixed name
    is read unchanged and the CLI never renames a setting it does not own.
    """
    raw = os.environ.get("TOPSAILAI_SESSION_META_RETENTION_DAYS", "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_RETENTION_DAYS


def _meta_max_count() -> int:
    """Read the core metadata count limit once at the CLI boundary."""
    raw = os.environ.get("TOPSAILAI_SESSION_META_MAX_COUNT", "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_META_MAX_COUNT


def _normalize_selected(selected: Optional[List[str]]) -> Optional[List[str]]:
    """Map the display spelling of a temporary session to its on-disk identity.

    ``parse_session_selector`` normalizes ``topsailai`` to ``(temp)`` for display,
    while owner records carry the literal ``topsailai`` prefix. Both spellings
    must select the same rows, so the selector is mapped back before matching.
    """
    if selected is None:
        return None
    return [
        _TEMP_SESSION_ID if item == _TEMP_SESSION_MARKER else item
        for item in selected
    ]


def _owner_records(task_dir: str) -> Dict[str, List[tuple]]:
    """Group every owner record in *task_dir* by its session identifier.

    The framework's own owner-record pattern is reused so this inventory cannot
    drift from the suffixes the activity probe recognizes. A name the pattern
    rejects is not an owner record and is never reported, which keeps the report
    aligned with the population the production reclaim paths can act on.

    A missing task directory is an empty inventory, because a home that never ran
    an agent owns no record. Any other read failure propagates, so an unreadable
    directory is reported as a failed inspection instead of being presented as
    "nothing to reclaim".
    """
    grouped: Dict[str, List[tuple]] = {}
    try:
        entries = os.listdir(task_dir)
    except FileNotFoundError:
        return grouped
    for name in entries:
        match = _OWNER_PATTERN.fullmatch(name)
        if match is None:
            continue
        grouped.setdefault(match.group(1), []).append((name, int(match.group(2))))
    return grouped


def _record_rows(
    task_dir: str,
    names: List[str],
    retention_seconds: int,
    now: float,
) -> List[dict]:
    """Return every regular-file owner record with its own expiry verdict.

    A socket endpoint is not a regular file and is owned by the channel that
    created it, so it is never reported as a reclaimable record. Reporting it
    would claim a deletion the production paths deliberately do not perform.
    """
    rows: List[dict] = []
    for name in names:
        path = os.path.join(task_dir, name)
        try:
            info = os.lstat(path)
        except OSError:
            continue
        if not stat.S_ISREG(info.st_mode):
            continue
        age = now - info.st_mtime
        rows.append({
            "filename": name,
            "path": path,
            "size": info.st_size,
            "mtime": info.st_mtime,
            "age_hours": round(age / 3600, 1),
            "expired": age > retention_seconds,
        })
    return rows


def _excess_meta_names(
    grouped: Dict[str, List[tuple]],
    task_dir: str,
    max_count: int,
) -> set:
    """Return metadata names beyond the configured retention count.

    The production metadata path removes the oldest metadata files first when
    the total exceeds the configured maximum, so the same oldest-first order is
    reproduced here. A zero maximum disables the count limit entirely.
    """
    if max_count <= 0:
        return set()
    ordered: List[tuple] = []
    for records in grouped.values():
        for name, _pid in records:
            if not name.endswith(".session.meta"):
                continue
            try:
                mtime = os.lstat(os.path.join(task_dir, name)).st_mtime
            except OSError:
                continue
            ordered.append((mtime, name))
    if len(ordered) <= max_count:
        return set()
    ordered.sort()
    return {name for _mtime, name in ordered[: len(ordered) - max_count]}


def _decide(
    state: str,
    reason: str,
    has_metadata: bool,
    expired: List[dict],
    expired_metadata: List[dict],
    excess_metadata: List[str],
    has_records: bool,
) -> tuple:
    """Return the reclaim decision and its reason for one session.

    The decision mirrors the two production reclaim paths. A session that still
    owns metadata is reclaimed by the metadata retention path, which removes the
    metadata together with its artifacts. A session that lost its metadata is
    reclaimed by the orphan path, which removes only its own expired records.
    Both paths require a provably stopped owner, so the session-level gate is
    identical and is evaluated first.

    A session whose only remaining record is a socket endpoint owns no regular
    file, so neither path can remove anything. It is reported as blocked with a
    dedicated reason instead of being described as a retention-window decision.
    """
    if state == ActivityState.RUNNING.value:
        return "blocked", "owning session is still alive"
    if state != ActivityState.STOPPED.value:
        return "blocked", reason or "owning session liveness cannot be verified"
    if has_metadata:
        if expired_metadata:
            return "reclaimable", "expired metadata and its artifacts"
        if excess_metadata:
            return "reclaimable", "metadata beyond the retention count"
        return "blocked", "metadata is still within the retention window"
    if expired:
        return "reclaimable", "expired owner records without metadata"
    if not has_records:
        return "blocked", "only a socket endpoint remains"
    return "blocked", "owner records are still within the retention window"


def _inspect(
    task_dir: str,
    grouped: Dict[str, List[tuple]],
    probe: SessionActivityProbe,
    retention_seconds: int,
    max_count: int,
    now: float,
) -> List[dict]:
    """Build one decision record per session from a single batch observation.

    One ``observe_many`` call covers every session, so a directory with hundreds
    of sessions is inventoried once instead of once per session.
    """
    session_ids = tuple(sorted(grouped))
    observations = probe.observe_many(session_ids) if session_ids else {}
    excess_meta = _excess_meta_names(grouped, task_dir, max_count)

    sessions: List[dict] = []
    for session_id in session_ids:
        records = grouped[session_id]
        names = [name for name, _pid in records]
        metadata_names = [name for name in names if name.endswith(".session.meta")]
        rows = _record_rows(task_dir, names, retention_seconds, now)
        expired = [row for row in rows if row["expired"]]
        expired_metadata = [
            row for row in expired if row["filename"].endswith(".session.meta")
        ]
        observation = observations.get(session_id)
        state = (
            observation.state.value
            if observation is not None
            else ActivityState.UNKNOWN.value
        )
        reason = (
            observation.reason
            if observation is not None
            else "missing local authority"
        )
        decision, block_reason = _decide(
            state,
            reason,
            bool(metadata_names),
            expired,
            expired_metadata,
            [name for name in metadata_names if name in excess_meta],
            bool(rows),
        )
        sessions.append({
            "session_id": session_id,
            "owner_pids": sorted({pid for _name, pid in records}),
            "record_count": len(rows),
            "socket_count": len(records) - len(rows),
            "has_metadata": bool(metadata_names),
            "activity_state": state,
            "activity_reason": reason,
            "expired_count": len(expired),
            "expired_bytes": sum(row["size"] for row in expired),
            "decision": decision,
            "reason": block_reason,
            "records": rows,
        })
    return sessions


def _print_header(title: str, stream) -> None:
    """Print the same header shape as ``formatting.print_header`` to *stream*.

    ``print_header`` writes to stdout only, so a machine-readable caller needs
    this local variant to keep its single-document stdout contract.
    """
    width = 80
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}", file=stream)
    print(f"{Colors.BOLD}{Colors.CYAN}  {title}{Colors.RESET}", file=stream)
    print(f"{Colors.BOLD}{Colors.CYAN}{'=' * width}{Colors.RESET}", file=stream)


def _print_table(sessions: List[dict], stream) -> None:
    """Print one row per session with its decision and blocking reason."""
    _print_header("Reclaimable Session Owner Records", stream)

    w_session = 26
    w_files = 6
    w_expired = 8
    w_state = 8
    w_decision = 12

    print(
        f" {'Session':<{w_session}} | {'Files':^{w_files}} | "
        f"{'Expired':^{w_expired}} | {'State':^{w_state}} | "
        f"{'Decision':^{w_decision}} | Reason",
        file=stream,
    )
    print(
        f"{'-' * (w_session + 2)}+{'-' * (w_files + 2)}+"
        f"{'-' * (w_expired + 2)}+{'-' * (w_state + 2)}+"
        f"{'-' * (w_decision + 2)}+{'-' * 40}",
        file=stream,
    )

    for session in sessions:
        name = session["session_id"]
        if len(name) > w_session:
            name = name[: w_session - 3] + "..."
        print(
            f" {name:<{w_session}} | {session['record_count']:^{w_files}} | "
            f"{session['expired_count']:^{w_expired}} | "
            f"{session['activity_state']:^{w_state}} | "
            f"{session['decision']:^{w_decision}} | {session['reason']}",
            file=stream,
        )


def _print_records(session: dict, stream) -> None:
    """Print every owner record of one session with its expiry verdict."""
    print(f"\n  {session['session_id']}  ({session['activity_reason']})", file=stream)
    w_name = 46
    w_size = 10
    w_time = 20
    w_age = 10
    print(
        f"   {'Filename':<{w_name}} | {'Size':>{w_size}} | "
        f"{'Modified':^{w_time}} | {'Age':>{w_age}} | Expired",
        file=stream,
    )
    for row in session["records"]:
        name = row["filename"]
        if len(name) > w_name:
            name = name[: w_name - 3] + "..."
        print(
            f"   {name:<{w_name}} | {format_size(row['size']):>{w_size}} | "
            f"{format_timestamp_full(row['mtime']):^{w_time}} | "
            f"{row['age_hours']:>{w_age}.1f}h | "
            f"{'yes' if row['expired'] else 'no'}",
            file=stream,
        )


def _emit_result(
    json_mode: bool,
    *,
    exit_code: int,
    delivery_state: str,
    message: str,
    sessions: List[dict],
    retention_days: int,
    meta_max_count: int,
    selectors: Optional[dict] = None,
    error_code: Optional[str] = None,
) -> None:
    """Emit one receipt describing exactly what was inspected."""
    if not json_mode:
        return
    reclaimable = [item for item in sessions if item["decision"] == "reclaimable"]
    receipt = new_receipt("reclaim")
    receipt.update(
        ok=exit_code == 0,
        exit_code=exit_code,
        delivery_state=delivery_state,
        error_code=error_code,
        message=message,
        response={
            "retention_days": retention_days,
            "meta_max_count": meta_max_count,
            "selectors": selectors or {"session_ids": None},
            "sessions": sessions,
            "session_count": len(sessions),
            "reclaimable_sessions": [item["session_id"] for item in reclaimable],
            "reclaimable_session_count": len(reclaimable),
            "blocked_session_count": len(sessions) - len(reclaimable),
            "reclaimable_record_count": sum(
                item["expired_count"] for item in reclaimable
            ),
            "reclaimable_bytes": sum(
                item["expired_bytes"] for item in reclaimable
            ),
        },
    )
    emit_receipt(receipt)


def run_workspace_reclaim_cli(
    argv,
    *,
    home_resolver: Optional[Callable[[], str]] = None,
    probe_factory: Optional[Callable[[str], SessionActivityProbe]] = None,
) -> int:
    """Report which session owner records are reclaimable and which are blocked.

    The command is read-only by design. It reuses the framework's owner-record
    pattern and the framework's activity probe, so the report describes the same
    population and the same authorization the production reclaim paths use. It
    never deletes, because the metadata retention path resolves its directory
    from an import-time constant and a second deletion implementation would
    drift from the one that actually runs.

    Args:
        argv: Arguments after ``workspace reclaim``.
        home_resolver: Optional ``TOPSAILAI_HOME`` resolver for tests.
        probe_factory: Optional probe factory for tests.

    Returns:
        ``0`` for a completed inspection, ``1`` when the task directory could
        not be read, ``2`` for a usage error.
    """
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except RuntimeUsageError:
        # ``UniqueValue`` rejects a conflicting repeat of the same option.
        if json_mode:
            emit_failure("reclaim", _USAGE_ERROR, "usage_error",
                         "Invalid reclaim arguments")
        else:
            print("[ERROR] Invalid reclaim arguments", file=sys.stderr)
        return _USAGE_ERROR
    except SystemExit as error:
        code = int(error.code)
        if json_mode and code != 0:
            emit_failure("reclaim", code, "usage_error", "Invalid reclaim arguments")
        return code

    try:
        session_ids = _normalize_selected(
            parse_session_selector(getattr(args, "session", None))
        )
    except SessionSelectorError as error:
        message = f"Invalid selector: {error}"
        if json_mode:
            emit_failure("reclaim", _USAGE_ERROR, "usage_error", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _USAGE_ERROR

    selectors = {"session_ids": session_ids}
    home = Path((home_resolver or get_topsailai_home)()).resolve()
    task_dir = str(home / "workspace" / "task")
    stream = _human_stream(json_mode)
    retention_days = _retention_days()
    max_count = _meta_max_count()

    try:
        grouped = _owner_records(task_dir)
    except OSError as error:
        message = f"Cannot read the task directory: {type(error).__name__}: {error}"
        if json_mode:
            emit_failure("reclaim", _INSPECTION_FAILED, "inspection_failed", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _INSPECTION_FAILED

    if session_ids is not None:
        selected = set(session_ids)
        grouped = {
            session_id: records
            for session_id, records in grouped.items()
            if session_id in selected
        }

    if not grouped:
        message = (
            "No session owner records found. "
            f"Records must be older than {retention_days} day(s) to be reclaimable."
        )
        cprint(f"[INFO] {message}", color=Colors.GREEN, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="nothing_to_inspect",
            message=message, sessions=[], retention_days=retention_days,
            meta_max_count=max_count, selectors=selectors,
        )
        return 0

    if retention_days <= 0:
        # A non-positive retention disables the production reclaim paths, so no
        # record can be reclaimable and reporting otherwise would be a lie.
        message = (
            "Retention is disabled "
            "(TOPSAILAI_SESSION_META_RETENTION_DAYS <= 0), so no record is "
            "reclaimable."
        )
        cprint(f"[INFO] {message}", color=Colors.YELLOW, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="nothing_to_inspect",
            message=message, sessions=[], retention_days=retention_days,
            meta_max_count=max_count, selectors=selectors,
        )
        return 0

    probe = (
        probe_factory(task_dir)
        if probe_factory is not None
        else SessionActivityProbe((task_dir,))
    )
    sessions = _inspect(
        task_dir, grouped, probe, retention_days * 86400, max_count, time.time(),
    )
    sessions.sort(key=lambda item: (item["decision"] != "reclaimable",
                                    item["session_id"]))

    _print_table(sessions, stream)
    if args.verbose:
        for session in sessions:
            _print_records(session, stream)

    reclaimable = [item for item in sessions if item["decision"] == "reclaimable"]
    record_count = sum(item["expired_count"] for item in reclaimable)
    byte_count = sum(item["expired_bytes"] for item in reclaimable)
    message = (
        f"{len(reclaimable)} of {len(sessions)} session(s) are reclaimable: "
        f"{record_count} record(s), {format_size(byte_count)}. "
        "This command never deletes; the agent reclaims them at startup."
    )
    cprint(f"\n[INFO] {message}", color=Colors.GREEN, file=stream)
    _emit_result(
        json_mode, exit_code=0, delivery_state="inspected", message=message,
        sessions=sessions, retention_days=retention_days,
        meta_max_count=max_count, selectors=selectors,
    )
    return 0
