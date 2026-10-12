"""Launch explicitly authorized drivers without owning their runtime records.

Author: DawsonLin
Deployment supplies absolute entry/interpreter paths; no layout discovery occurs.
"""

from dataclasses import dataclass, field
from functools import partial
import logging
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Callable, Mapping, Sequence

import psutil

from cli_topsailai.session_driver import (
    DriverObservation, ProcessEvidence, metadata_path, observe_driver,
    probe_driver_process,
)

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class DriverAuthority:
    """Carry installation-supplied entry and actual Python interpreter paths."""

    entry: Path
    interpreter: Path

    def validate(self) -> None:
        """Reject absent or relative authority and packaged non-Python runtimes."""
        for path in (self.entry, self.interpreter):
            if not isinstance(path, Path) or not path.is_absolute() or not path.is_file():
                raise ValueError("authority_unavailable")
        if (not self.interpreter.name.lower().startswith("python")
                or not os.access(self.interpreter, os.X_OK)):
            raise ValueError("interpreter_unavailable")
        if not os.access(self.entry, os.R_OK):
            raise ValueError("entry_unreadable")


@dataclass(frozen=True)
class LaunchResult:
    """Distinguish publication proof from pending delivery or startup failure."""

    outcome: str
    reason: str
    observation: DriverObservation | None = None
    exit_code: int | None = None
    child: object | None = field(default=None, repr=False, compare=False)


def _target_alive(pid: int) -> bool:
    """Use read-only stable process evidence, treating denied queries as unknown."""
    try:
        process = psutil.Process(pid)
        birth = process.create_time()
        return (process.is_running()
                and process.status() not in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD)
                and process.create_time() == birth)
    except (psutil.Error, OSError):
        return False


def _row_identity(row: dict, home: Path) -> tuple[str, int]:
    """Require an exact non-temporary session stdout identity before probing."""
    if not isinstance(row, dict):
        raise ValueError("invalid_row")
    session = row.get("session_id")
    metadata_path(home, session)
    pid = row.get("pid")
    if (type(pid) is not int or pid <= 0 or row.get("is_task")
            or row.get("session_pid", pid) != pid
            or type(row.get("session_pid", pid)) is not int
            or row.get("filename") != f"{session}.{pid}.session.stdout"):
        raise ValueError("ineligible_row")
    return session, pid


def _revalidate(rows: Sequence[dict], index: int, home: Path,
                discover: Callable[[], Sequence[dict]],
                target_probe: Callable[[int], bool]) -> tuple[str, int]:
    """Bind the selected display row to fresh discovery and current liveness."""
    if type(index) is not int or index < 1 or index > len(rows):
        raise ValueError("invalid_row_index")
    session, pid = _row_identity(rows[index - 1], home)
    fresh = discover()
    matching = False
    live = set()
    for row in fresh:
        if not isinstance(row, dict) or row.get("session_id") != session or row.get("is_task"):
            continue
        candidate = row.get("pid")
        if type(candidate) is not int or candidate <= 0:
            continue
        if not target_probe(candidate):
            continue
        live.add(candidate)
        if _row_identity(row, home) == (session, pid):
            matching = True
    if len(live) > 1:
        raise ValueError("ambiguous_session")
    if not matching:
        raise ValueError("target_not_current")
    return session, pid


def _confirmed(observation: DriverObservation) -> bool:
    """Require verified running metadata, not just a display label."""
    return (observation.state == "ON"
            and observation.verification is ProcessEvidence.VERIFIED
            and observation.metadata is not None
            and observation.metadata.status == "running")


def _confirm(child, before: DriverObservation, observe: Callable[[], DriverObservation],
             timeout: float, interval: float, clock: Callable[[], float],
             sleep: Callable[[float], None]) -> LaunchResult:
    """Bound publication confirmation; reap exits but never stop or retry owners."""
    deadline = clock() + timeout
    while True:
        code = child.poll()
        observation = observe()
        # Recheck exit after observation, so a departed child is not acknowledged.
        code = child.poll() if code is None else code
        expired = clock() >= deadline
        if code is not None:
            child.wait()
            if _confirmed(observation) and observation.driver_pid != child.pid:
                return LaunchResult("already_running", "competing_owner", observation, code)
            return LaunchResult("failed", "child_exited", observation, code)
        if not expired and _confirmed(observation):
            if observation.driver_pid == child.pid and observation.run_id != before.run_id:
                return LaunchResult("launched", "publication_verified", observation, child=child)
        if expired:
            LOGGER.warning("Driver startup unconfirmed: pid=%s reason=%s", child.pid, observation.reason)
            return LaunchResult("unconfirmed", observation.reason, observation, child=child)
        sleep(min(interval, max(0, deadline - clock())))


def launch_driver(rows: Sequence[dict], index: int, *, topsailai_home: Path,
                  authority: DriverAuthority | None, environment: Mapping[str, str],
                  discover: Callable[[], Sequence[dict]], timeout: float = 3.0,
                  interval: float = 0.1, target_probe: Callable[[int], bool] = _target_alive,
                  observer: Callable[..., DriverObservation] = observe_driver,
                  spawn: Callable = subprocess.Popen, clock: Callable[[], float] = time.monotonic,
                  sleep: Callable[[float], None] = time.sleep) -> LaunchResult:
    """Revalidate, detach, and acknowledge only a fresh verified child publication.

    Callers retain a returned live child handle for later poll/reap; it must not
    enter terminate-on-CLI-exit tracking. No persistent CLI ownership is created.
    """
    try:
        if (isinstance(timeout, bool) or isinstance(interval, bool)
                or not math.isfinite(timeout) or not math.isfinite(interval)
                or timeout <= 0 or interval <= 0):
            raise ValueError("invalid_confirmation_bounds")
        if authority is None:
            raise ValueError("authority_unavailable")
        authority.validate()
        home = Path(topsailai_home)
        session, _ = _revalidate(rows, index, home, discover, target_probe)
        env = dict(environment)
        if any(not isinstance(k, str) or not isinstance(v, str) for k, v in env.items()):
            raise ValueError("invalid_environment")
        env["TOPSAILAI_HOME"] = str(home)
        observe = partial(observer, home, session,
                          process_probe=partial(probe_driver_process, driver_entry=authority.entry))
        before = observe()
        if _confirmed(before):
            return LaunchResult("already_running", "verified_owner", before)
        if before.state not in ("-", "STALE"):
            return LaunchResult("rejected", "preflight_" + before.reason, before)
        # Recheck the target after fallible authority/metadata I/O.
        _revalidate(rows, index, home, discover, target_probe)
        kwargs = dict(stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                      stderr=subprocess.DEVNULL, env=env, cwd=str(home), shell=False)
        if sys.platform == "win32":
            kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        child = spawn([str(authority.interpreter), str(authority.entry), "--session", session], **kwargs)
    except (ValueError, TypeError, OSError) as error:
        LOGGER.warning("Driver launch rejected: type=%s", type(error).__name__, exc_info=True)
        return LaunchResult("rejected" if not isinstance(error, OSError) else "failed",
                            str(error) if isinstance(error, ValueError) else type(error).__name__)
    return _confirm(child, before, observe, timeout, interval, clock, sleep)
