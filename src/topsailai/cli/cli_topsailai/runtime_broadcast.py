"""Best-effort same-session runtime context broadcasting."""

from dataclasses import dataclass
from pathlib import Path
import os
import stat
from typing import Callable, List, Optional

from cli_topsailai.log_files import parse_stdout_filename
from cli_topsailai.runtime_operations import write_injection
from cli_topsailai.runtime_target import ProcessState, RuntimeTargetError, probe_process

JSONL_SUFFIX = ".session.agent2llm_inject_messages.jsonl"


@dataclass(frozen=True)
class BroadcastTarget:
    """Identify one discovered live process and its original evidence."""

    session_id: str
    pid: int
    stdout_path: Path
    inject_path: Path


@dataclass(frozen=True)
class BroadcastOutcome:
    """Record one target's delivery boundary and diagnostic."""

    pid: int
    status: str
    detail: str = ""


@dataclass(frozen=True)
class BroadcastResult:
    """Aggregate per-target outcomes without claiming receiver consumption."""

    session_id: str
    outcomes: tuple[BroadcastOutcome, ...]

    @property
    def queued(self) -> int:
        """Return the number of confirmed queue appends."""
        return sum(item.status == "queued" for item in self.outcomes)

    @property
    def counts(self) -> dict[str, int]:
        """Return outcome counts grouped for the user-facing summary."""
        return {
            "queued": sum(item.status == "queued" for item in self.outcomes),
            "skipped": sum(item.status.startswith("skipped_") for item in self.outcomes),
            "failed": sum(
                item.status in (
                    "permission_denied",
                    "evidence_changed",
                    "failed_prewrite",
                    "invalid_session",
                    "task_dir_missing",
                    "task_dir_invalid",
                )
                for item in self.outcomes
            ),
            "uncertain": sum(item.status == "delivery_unknown" for item in self.outcomes),
        }

    @property
    def incomplete(self) -> bool:
        """Return whether any live candidate was not confirmed queued."""
        return (
            not self.outcomes
            or self.queued == 0
            or any(item.status not in ("queued", "skipped_exited") for item in self.outcomes)
        )


def _valid_session(session_id: object) -> bool:
    """Accept only named sessions, never temporary display sentinels."""
    return (
        isinstance(session_id, str)
        and bool(session_id)
        and session_id not in ("topsailai", "(temp)")
        and not any(char in session_id for char in ("/", "\\", "\0"))
    )


def _stdout_target(path: Path, task_dir: Path, session_id: str) -> Optional[BroadcastTarget]:
    """Convert one regular non-symlink stdout evidence file into a target."""
    if not (path.name.endswith(".session.stdout") or path.name.endswith(".task.stdout")):
        return None
    try:
        mode = path.lstat().st_mode
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(mode):
        return None
    parsed_session, pid_text = parse_stdout_filename(path.name)
    if parsed_session != session_id or pid_text is None:
        return None
    try:
        pid = int(pid_text)
    except ValueError:
        return None
    if pid <= 0:
        return None
    return BroadcastTarget(
        session_id,
        pid,
        path,
        task_dir / f"{session_id}.{pid}{JSONL_SUFFIX}",
    )


def _discover(task_dir: Path, session_id: str) -> List[BroadcastTarget]:
    """Take one deterministic, deduplicated evidence snapshot."""
    by_pid: dict[int, BroadcastTarget] = {}
    for path in sorted(task_dir.iterdir(), key=lambda item: item.name):
        target = _stdout_target(path, task_dir, session_id)
        if target is None:
            continue
        current = by_pid.get(target.pid)
        if current is None or (
            path.name.endswith(".session.stdout")
            and not current.stdout_path.name.endswith(".session.stdout")
        ):
            by_pid[target.pid] = target
    return [by_pid[pid] for pid in sorted(by_pid)]


def _revalidate(target: BroadcastTarget, process_probe: Callable[[int], ProcessState]) -> str:
    """Validate unchanged evidence and live process state before writing."""
    try:
        mode = target.stdout_path.lstat().st_mode
    except FileNotFoundError:
        return "evidence_changed"
    except PermissionError:
        return "permission_denied"
    if not stat.S_ISREG(mode):
        return "evidence_changed"
    parsed_session, pid_text = parse_stdout_filename(target.stdout_path.name)
    if parsed_session != target.session_id or pid_text != str(target.pid):
        return "evidence_changed"
    try:
        state = process_probe(target.pid)
    except PermissionError:
        return "permission_denied"
    except RuntimeTargetError as exc:
        if exc.error_code == "permission_denied":
            return "permission_denied"
        if exc.error_code in ("unsupported_transport", "stale_target"):
            return "skipped_unverifiable"
        return "permission_denied"
    if state is ProcessState.DEAD:
        return "skipped_exited"
    if state is not ProcessState.ALIVE:
        return "skipped_unverifiable"
    return ""


def broadcast_message(
    task_dir: str | Path,
    session_id: str,
    message: str,
    *,
    process_probe: Callable[[int], ProcessState] = probe_process,
    injection_writer: Callable[[str, str], bool] = write_injection,
    progress_callback: Optional[Callable[[str, object], None]] = None,
) -> BroadcastResult:
    """Queue *message* once for every discoverable live PID in a session."""
    def emit_outcome(outcome: BroadcastOutcome) -> None:
        """Report an outcome immediately when a progress callback is present."""
        if progress_callback is not None:
            progress_callback("outcome", outcome)

    if not _valid_session(session_id):
        outcome = BroadcastOutcome(0, "invalid_session")
        emit_outcome(outcome)
        return BroadcastResult(session_id, (outcome,))
    task_path = Path(task_dir)
    try:
        mode = task_path.lstat().st_mode
    except FileNotFoundError:
        outcome = BroadcastOutcome(0, "task_dir_missing")
        emit_outcome(outcome)
        return BroadcastResult(session_id, (outcome,))
    except PermissionError:
        outcome = BroadcastOutcome(0, "permission_denied")
        emit_outcome(outcome)
        return BroadcastResult(session_id, (outcome,))
    if not stat.S_ISDIR(mode):
        outcome = BroadcastOutcome(0, "task_dir_invalid")
        emit_outcome(outcome)
        return BroadcastResult(session_id, (outcome,))
    try:
        targets = _discover(task_path, session_id)
    except PermissionError:
        outcome = BroadcastOutcome(0, "permission_denied")
        emit_outcome(outcome)
        return BroadcastResult(session_id, (outcome,))

    outcomes: List[BroadcastOutcome] = []
    if progress_callback is not None:
        progress_callback("snapshot", len(targets))
    for target in targets:
        failure = _revalidate(target, process_probe)
        if failure:
            outcome = BroadcastOutcome(target.pid, failure)
            outcomes.append(outcome)
            emit_outcome(outcome)
            continue
        try:
            endpoint_mode = target.inject_path.lstat().st_mode
            if not stat.S_ISREG(endpoint_mode):
                outcome = BroadcastOutcome(target.pid, "failed_prewrite", "invalid_endpoint")
                outcomes.append(outcome)
                emit_outcome(outcome)
                continue
        except FileNotFoundError:
            pass
        except PermissionError:
            outcome = BroadcastOutcome(target.pid, "failed_prewrite", "permission_denied")
            outcomes.append(outcome)
            emit_outcome(outcome)
            continue
        try:
            queued = injection_writer(str(target.inject_path), message)
        except Exception as exc:
            outcome = BroadcastOutcome(target.pid, "delivery_unknown", type(exc).__name__)
            outcomes.append(outcome)
            emit_outcome(outcome)
            continue
        outcome = BroadcastOutcome(target.pid, "queued" if queued else "delivery_unknown")
        outcomes.append(outcome)
        emit_outcome(outcome)
    return BroadcastResult(session_id, tuple(outcomes))
