"""Reclaim expired task records and driver pidfiles from the task folder.

Author: DawsonLin
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import stat
import sys
import time
from pathlib import Path
from typing import Callable, Dict, List, Optional

from cli_topsailai.colors import Colors, cprint
from cli_topsailai.formatting import format_size
from cli_topsailai.paths import get_topsailai_home
from cli_topsailai.workspace_receipt import (
    emit_failure,
    emit_receipt,
    json_requested,
    new_receipt,
)

#: Exit code for a usage error, matching the other workspace subcommands.
_USAGE_ERROR = 2
#: Exit code for an inspection that could not read the task directory.
_INSPECTION_FAILED = 1
#: Exit code for a deletion that failed for at least one record.
_DELETE_FAILED = 1

#: Suffix of a JSON task record written by the agent task tool.
TASK_SUFFIX = ".task"
#: Suffix of a one-line driver pidfile written by the CLI driver launcher.
PIDFILE_SUFFIX = ".driver.pid"
#: Age in days a record must exceed before it becomes reclaimable.
DEFAULT_MIN_AGE_DAYS = 7.0
#: Archive folder created beside the records when content is reclaimed.
DEFAULT_ARCHIVE_DIRNAME = "task-record-archive"


def build_parser() -> argparse.ArgumentParser:
    """Build the strict non-interactive ``workspace delete-task-records`` parser."""
    parser = argparse.ArgumentParser(
        prog="topsailai workspace delete-task-records",
        description=(
            "List or delete expired task records and driver pidfiles. "
            "Nothing is deleted without --yes."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        dest="yes",
        help="delete the reclaimable records; without it the run is a dry run",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="report the inventory without changing anything (this is the default)",
    )
    parser.add_argument(
        "--kind",
        choices=("all", "task", "pidfile"),
        default="all",
        dest="kind",
        help="which record kind to consider (default: all)",
    )
    parser.add_argument(
        "--min-age-days",
        type=float,
        default=None,
        dest="min_age_days",
        metavar="DAYS",
        help=f"retention threshold in days (default: {DEFAULT_MIN_AGE_DAYS:g})",
    )
    parser.add_argument(
        "--allow-content",
        action="store_true",
        dest="allow_content",
        help=(
            "also reclaim task records that hold conversation content; "
            "an archive copy is written first"
        ),
    )
    parser.add_argument(
        "--archive-dir",
        default=None,
        dest="archive_dir",
        metavar="PATH",
        help="copy task records here before deleting them",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        dest="verbose",
        help="list every kept record with its own reason",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json",
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


def _min_age_days(explicit: Optional[float]) -> float:
    """Resolve the retention threshold from the argument or the default.

    A negative threshold is rejected rather than clamped, because a negative
    value would silently make every record reclaimable.
    """
    if explicit is None:
        return DEFAULT_MIN_AGE_DAYS
    if explicit < 0:
        raise ValueError("--min-age-days must not be negative")
    return float(explicit)


def _file_identity(path: Path) -> Optional[tuple]:
    """Return a stable identity for a regular file, or None when it is not one."""
    try:
        info = path.lstat()
    except OSError:
        return None
    if not stat.S_ISREG(info.st_mode):
        return None
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)


def _open_paths() -> Optional[set]:
    """Return every path currently held open by a process, or None if unknown.

    One batched scan of ``/proc/*/fd`` replaces a per-file probe, which costs
    about 11 ms per file and would dominate a large inventory. ``None`` means
    the process table could not be read, so callers must fail closed and delete
    nothing rather than assume a file is unused.
    """
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    try:
        entries = list(proc.iterdir())
    except OSError:
        return None
    held: set = set()
    readable = False
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            fds = list((entry / "fd").iterdir())
        except OSError:
            continue
        readable = True
        for fd in fds:
            try:
                target = os.readlink(fd)
            except OSError:
                continue
            if target.startswith("/"):
                held.add(target)
    return held if readable else None


def _pid_alive(pid: int) -> bool:
    """Return True when the process id currently exists."""
    if pid <= 0:
        return False
    return Path(f"/proc/{pid}").exists()


def _read_pidfile(path: Path) -> Optional[int]:
    """Read the integer process id stored in a pidfile."""
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        return None


def _task_summary(path: Path) -> dict:
    """Describe a task record without mutating it.

    A task record carries ``session_messages``, so the message count decides
    whether deleting it would destroy conversation content that the session
    store may not duplicate. A record can also be truncated: the writer caps a
    record at 48 KiB, which leaves a file that no longer parses but still holds
    conversation text. Such a file is reported as unparseable with a content
    hint, never as content-free, because treating it as empty would delete real
    conversation text.
    """
    summary: dict = {
        "empty": False,
        "parseable": False,
        "content_hint": False,
        "message_count": 0,
        "task_content_chars": 0,
        "session_id": "",
        "bytes": 0,
    }
    try:
        summary["bytes"] = path.stat().st_size
        raw = path.read_bytes()
    except OSError:
        return summary
    if not raw.strip():
        summary["empty"] = True
        return summary
    # A truncated record keeps its keys but loses its closing structure, so the
    # raw bytes are the only reliable evidence that text is present.
    summary["content_hint"] = b'"content"' in raw or b"session_messages" in raw
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return summary
    if not isinstance(data, dict):
        return summary
    summary["parseable"] = True
    messages = data.get("session_messages") or []
    if isinstance(messages, list):
        summary["message_count"] = len(messages)
    content = data.get("task_content") or ""
    if isinstance(content, str):
        summary["task_content_chars"] = len(content)
    summary["session_id"] = str(data.get("session_id") or "")
    return summary


def _age_days(path: Path, now: float) -> Optional[float]:
    """Return the file age in days, or None when it cannot be read."""
    try:
        return max(0.0, (now - path.stat().st_mtime) / 86400.0)
    except OSError:
        return None


def _decide_task(
    path: Path,
    now: float,
    min_age_days: float,
    held: Optional[set],
    allow_content: bool,
) -> tuple:
    """Decide whether one task record may be removed, with a human reason."""
    age = _age_days(path, now)
    if age is None:
        return False, "file cannot be inspected"
    if age < min_age_days:
        return False, f"within the retention window ({age:.1f}d < {min_age_days:.1f}d)"
    if held is None:
        return False, "process table is unreadable, refusing to guess"
    if str(path) in held:
        return False, "held open by a live process"
    summary = _task_summary(path)
    if summary["empty"]:
        return True, "empty file, holds no content"
    if not summary["parseable"]:
        if summary["content_hint"]:
            return False, (
                "truncated or corrupt but still holds conversation text; "
                "refusing to reclaim"
            )
        return True, "unparseable and holds no conversation text"
    if summary["message_count"] == 0 and summary["task_content_chars"] == 0:
        return True, "parsed but holds no content"
    if not allow_content:
        return False, (
            f"holds {summary['message_count']} conversation message(s); "
            "pass --allow-content to reclaim"
        )
    return True, f"holds {summary['message_count']} conversation message(s), opted in"


def _decide_pidfile(path: Path, now: float, min_age_days: float) -> tuple:
    """Decide whether one driver pidfile may be removed, with a human reason."""
    age = _age_days(path, now)
    if age is None:
        return False, "file cannot be inspected"
    if age < min_age_days:
        return False, f"within the retention window ({age:.1f}d < {min_age_days:.1f}d)"
    pid = _read_pidfile(path)
    if pid is None:
        return True, "unreadable pid, no owner to protect"
    if _pid_alive(pid):
        return False, f"recorded process {pid} is still alive"
    return True, f"recorded process {pid} is gone"


def _collect(
    task_dir: Path,
    kind: str,
    now: float,
    min_age_days: float,
    held: Optional[set],
    allow_content: bool,
) -> List[dict]:
    """Build the candidate inventory with one verdict per record."""
    try:
        entries = sorted(task_dir.iterdir())
    except OSError as error:
        raise OSError(f"cannot read the task folder: {error}") from error
    rows: List[dict] = []
    for path in entries:
        if path.is_symlink() or not path.is_file():
            continue
        name = path.name
        if kind in {"all", "task"} and name.endswith(TASK_SUFFIX):
            deletable, reason = _decide_task(
                path, now, min_age_days, held, allow_content,
            )
            summary = _task_summary(path)
            rows.append({
                "filename": name,
                "path": str(path),
                "kind": "task",
                "bytes": summary["bytes"],
                "age_days": round(_age_days(path, now) or 0.0, 1),
                "message_count": summary["message_count"],
                "deletable": deletable,
                "reason": reason,
            })
        elif kind in {"all", "pidfile"} and name.endswith(PIDFILE_SUFFIX):
            deletable, reason = _decide_pidfile(path, now, min_age_days)
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            rows.append({
                "filename": name,
                "path": str(path),
                "kind": "pidfile",
                "bytes": size,
                "age_days": round(_age_days(path, now) or 0.0, 1),
                "message_count": 0,
                "deletable": deletable,
                "reason": reason,
            })
    return rows


def _archive(path: Path, archive_dir: Path) -> Optional[Path]:
    """Copy one record into the archive folder before it is removed."""
    try:
        archive_dir.mkdir(parents=True, exist_ok=True)
        target = archive_dir / path.name
        if target.exists():
            target = archive_dir / f"{path.name}.{int(time.time())}"
        shutil.copy2(path, target)
        return target
    except OSError as error:
        print(f"[ERROR] archive failed for {path}: {error}", file=sys.stderr)
        return None


def _remove(path: Path, expected: Optional[tuple]) -> bool:
    """Remove one record after confirming its identity has not changed."""
    current = _file_identity(path)
    if current is None:
        print(f"[WARN] skip {path}: no longer a regular file", file=sys.stderr)
        return False
    if expected is not None and current != expected:
        print(f"[WARN] skip {path}: file changed since inspection", file=sys.stderr)
        return False
    try:
        os.unlink(path)
    except OSError as error:
        print(f"[ERROR] failed to remove {path}: {error}", file=sys.stderr)
        return False
    print(f"DELETED: {path}", file=sys.stderr)
    return True


def _print_rows(rows: List[dict], verbose: bool, stream) -> None:
    """Print the inventory in a readable form."""
    deletable = [row for row in rows if row["deletable"]]
    kept = [row for row in rows if not row["deletable"]]
    total_bytes = sum(row["bytes"] for row in deletable)
    cprint(
        f"{len(deletable)} of {len(rows)} record(s) are reclaimable: "
        f"{format_size(total_bytes)}.",
        color=Colors.GREEN, file=stream,
    )
    if deletable:
        _print_header("Reclaimable Records", stream)
        for row in deletable:
            extra = f" msgs={row['message_count']}" if row["kind"] == "task" else ""
            print(
                f"  {row['filename']}  [{row['kind']}] "
                f"{format_size(row['bytes'])} {row['age_days']}d{extra}",
                file=stream,
            )
            print(f"    {row['reason']}", file=stream)
    if not kept:
        return
    if verbose:
        _print_header("Kept Records", stream)
        for row in kept:
            print(
                f"  {row['filename']}  [{row['kind']}] "
                f"{format_size(row['bytes'])} {row['age_days']}d",
                file=stream,
            )
            print(f"    {row['reason']}", file=stream)
        return
    _print_header("Kept Records (use --verbose for the full list)", stream)
    reasons: Dict[str, int] = {}
    for row in kept:
        key = row["reason"].split("(")[0].strip()
        reasons[key] = reasons.get(key, 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda item: -item[1]):
        print(f"  {count:4d}  {reason}", file=stream)


def _emit_result(
    json_mode: bool,
    *,
    exit_code: int,
    delivery_state: str,
    message: str,
    rows: List[dict],
    task_dir: str,
    min_age_days: float,
    allow_content: bool,
    applied: bool,
    error_code: Optional[str] = None,
) -> None:
    """Emit one receipt describing exactly what was inspected and removed."""
    if not json_mode:
        return
    reclaimable = [row for row in rows if row["deletable"]]
    receipt = new_receipt("delete-task-records")
    receipt.update(
        ok=exit_code == 0,
        exit_code=exit_code,
        delivery_state=delivery_state,
        error_code=error_code,
        message=message,
        response={
            "task_dir": task_dir,
            "min_age_days": min_age_days,
            "allow_content": allow_content,
            "applied": applied,
            "records": rows,
            "record_count": len(rows),
            "reclaimable_records": [row["filename"] for row in reclaimable],
            "reclaimable_record_count": len(reclaimable),
            "reclaimable_bytes": sum(row["bytes"] for row in reclaimable),
        },
    )
    emit_receipt(receipt)


def run_workspace_delete_task_records_cli(
    argv,
    *,
    home_resolver: Optional[Callable[[], str]] = None,
    open_paths: Optional[Callable[[], Optional[set]]] = None,
    now: Optional[float] = None,
) -> int:
    """List or delete expired task records and driver pidfiles.

    The command previews by default and deletes only when ``--yes`` is given,
    because a non-interactive caller must never trigger an irreversible action
    through an implicit default. A task record carries conversation content, so
    a content-bearing record is kept unless the operator explicitly opts in,
    and an archive copy is written before such a record is removed.

    Args:
        argv: Arguments after ``workspace delete-task-records``.
        home_resolver: Optional ``TOPSAILAI_HOME`` resolver for tests.
        open_paths: Optional held-open-path probe for tests.
        now: Optional clock override for tests.

    Returns:
        ``0`` for a preview, an empty inventory or a complete deletion, ``1``
        when a deletion or the inspection failed, ``2`` for a usage error.
    """
    json_mode = json_requested(argv)
    try:
        args = build_parser().parse_args(list(argv))
        json_mode = args.json
    except SystemExit as error:
        code = int(error.code)
        if json_mode and code != 0:
            emit_failure("delete-task-records", code, "usage_error",
                         "Invalid delete-task-records arguments")
        return code

    stream = _human_stream(json_mode)
    try:
        min_age_days = _min_age_days(args.min_age_days)
    except ValueError as error:
        message = str(error)
        if json_mode:
            emit_failure("delete-task-records", _USAGE_ERROR, "usage_error", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _USAGE_ERROR

    resolver = home_resolver or get_topsailai_home
    task_dir = Path(resolver()) / "workspace" / "task"
    if not task_dir.is_dir():
        message = f"Task folder does not exist: {task_dir}"
        if json_mode:
            emit_failure("delete-task-records", _INSPECTION_FAILED, "inspection_failed", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _INSPECTION_FAILED

    probe = open_paths or _open_paths
    held = probe()
    clock = time.time() if now is None else now
    try:
        rows = _collect(
            task_dir, args.kind, clock, min_age_days, held, args.allow_content,
        )
    except OSError as error:
        message = f"Cannot read the task folder: {type(error).__name__}: {error}"
        if json_mode:
            emit_failure("delete-task-records", _INSPECTION_FAILED, "inspection_failed", message)
        else:
            print(f"[ERROR] {message}", file=sys.stderr)
        return _INSPECTION_FAILED

    applied = bool(args.yes) and not bool(args.dry_run)
    if not json_mode:
        print(f"task folder: {task_dir}", file=stream)
        print(
            f"retention: {min_age_days:.1f}d  "
            f"allow_content={bool(args.allow_content)}",
            file=stream,
        )
        _print_rows(rows, args.verbose, stream)

    if not applied:
        message = (
            f"{sum(1 for row in rows if row['deletable'])} of {len(rows)} "
            "record(s) are reclaimable. Dry run: nothing was deleted. "
            "Re-run with --yes to delete."
        )
        if not json_mode:
            cprint(f"\n[INFO] {message}", color=Colors.GREEN, file=stream)
        _emit_result(
            json_mode, exit_code=0, delivery_state="inspected", message=message,
            rows=rows, task_dir=str(task_dir), min_age_days=min_age_days,
            allow_content=bool(args.allow_content), applied=False,
        )
        return 0

    archive_dir: Optional[Path] = None
    if args.archive_dir:
        archive_dir = Path(args.archive_dir).expanduser().resolve()
    elif args.allow_content:
        archive_dir = task_dir / DEFAULT_ARCHIVE_DIRNAME

    removed = 0
    archived = 0
    failed = 0
    for row in rows:
        if not row["deletable"]:
            continue
        path = Path(row["path"])
        expected = _file_identity(path)
        if archive_dir is not None and row["kind"] == "task":
            if _archive(path, archive_dir) is None:
                failed += 1
                continue
            archived += 1
        if _remove(path, expected):
            removed += 1
        else:
            failed += 1

    exit_code = _DELETE_FAILED if failed else 0
    message = f"Removed {removed} record(s), archived {archived}, failed {failed}."
    if not json_mode:
        color = Colors.RED if failed else Colors.GREEN
        cprint(f"\n[INFO] {message}", color=color, file=stream)
        if archive_dir is not None:
            print(f"archive: {archive_dir}", file=stream)
    _emit_result(
        json_mode, exit_code=exit_code,
        delivery_state="applied" if not failed else "partially_applied",
        message=message, rows=rows, task_dir=str(task_dir),
        min_age_days=min_age_days, allow_content=bool(args.allow_content),
        applied=True, error_code="delete_failed" if failed else None,
    )
    return exit_code
