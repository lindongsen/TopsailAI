"""Stop one verified driver without owning its records or its session.

Author: DawsonLin
Metadata v1 has no birth baseline; command identity remains best-effort.
"""

from dataclasses import dataclass
import logging
import math
import os
from pathlib import Path
import signal
import time

import psutil

from cli_topsailai.session_driver import (
    DriverObservation, ProcessEvidence, _matches_command, observe_driver,
)
from cli_topsailai.session_driver_launcher import _row_identity, _target_alive

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class StopResult:
    """Separate absence proof, rejection, submission failure and uncertainty."""

    outcome: str
    reason: str
    observation: DriverObservation | None = None


def _revalidate(rows, index, home, discover, target_probe):
    """Bind an authoritative row even when its target session has exited."""
    if type(index) is not int or not 1 <= index <= len(rows):
        raise ValueError("invalid_row_index")
    identity = _row_identity(rows[index - 1], home)
    matches = 0
    live = set()
    for row in discover():
        if not isinstance(row, dict) or row.get("session_id") != identity[0]:
            continue
        try:
            candidate = _row_identity(row, home)
        except (ValueError, TypeError):
            continue
        matches += candidate == identity
        if target_probe(candidate[1]):
            live.add(candidate[1])
    if len(live) > 1:
        raise ValueError("ambiguous_session")
    if matches != 1:
        raise ValueError("target_not_current")
    return identity


def _absent(process, birth):
    """Confirm original identity absence, including zombies and PID reuse."""
    try:
        return (not process.is_running() or process.create_time() != birth
                or process.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD))
    except psutil.NoSuchProcess:
        return True


def stop_driver(rows, index, *, topsailai_home: Path, authority, discover,
                timeout=3.0, interval=0.1, target_probe=_target_alive,
                observer=observe_driver, process_factory=psutil.Process,
                clock=time.monotonic, sleep=time.sleep, platform=os.name):
    """Verify custody twice, signal once, then bound original-owner exit proof.

    No records are written, descendants signaled or forced termination attempted.
    Dependencies are explicit so tests never need process-global switches.
    """
    observation = None
    process = None
    birth = None

    def probe(metadata):
        """Bind one handle and reject any later PID or birth-identity change."""
        nonlocal process, birth
        try:
            if process is None:
                process = process_factory(metadata.pid)
                birth = process.create_time()
            if process.pid != metadata.pid:
                return ProcessEvidence.UNKNOWN
            if _absent(process, birth):
                return ProcessEvidence.ABSENT
            command, cwd = process.cmdline(), process.cwd()
            if process.create_time() != birth or not process.is_running():
                return ProcessEvidence.UNKNOWN
            return (ProcessEvidence.VERIFIED if
                    _matches_command(command, metadata, authority.entry, cwd)
                    else ProcessEvidence.UNKNOWN)
        except psutil.NoSuchProcess:
            return ProcessEvidence.ABSENT
        except (psutil.Error, OSError, ValueError, NotImplementedError):
            LOGGER.warning("Driver stop identity inspection failed", exc_info=True)
            return ProcessEvidence.UNKNOWN

    def observe():
        """Read bounded no-follow evidence with the bound process probe."""
        return observer(topsailai_home, session, process_probe=probe)

    try:
        if (isinstance(timeout, bool) or isinstance(interval, bool)
                or not math.isfinite(timeout) or not math.isfinite(interval)
                or timeout <= 0 or interval <= 0):
            raise ValueError("invalid_confirmation_bounds")
        if platform != "posix":
            raise ValueError("graceful_stop_unsupported")
        if authority is None:
            raise ValueError("authority_unavailable")
        authority.validate()
        selected_identity = _revalidate(rows, index, topsailai_home, discover, target_probe)
        session, session_pid = selected_identity
        observation = observe()
        if observation.state == "-" and observation.reason == "metadata_missing":
            return StopResult("already_stopped", "no_recorded_driver", observation)
        if observation.verification is ProcessEvidence.ABSENT and observation.state != "?":
            return StopResult("already_stopped", "original_process_absent", observation)
        if (observation.state != "ON" or observation.metadata is None
                or observation.metadata.status != "running"
                or observation.verification is not ProcessEvidence.VERIFIED
                or process is None or process.pid == session_pid):
            raise ValueError("preflight_" + observation.reason)
        original = observation.metadata
        if _revalidate(rows, index, topsailai_home, discover, target_probe) != selected_identity:
            raise ValueError("target_changed")
        observation = observe()
        if _revalidate(rows, index, topsailai_home, discover, target_probe) != selected_identity:
            raise ValueError("target_changed")
        if (observation.metadata != original
                or observation.verification is not ProcessEvidence.VERIFIED
                or observation.state != "ON"):
            raise ValueError("owner_changed")
        if _absent(process, birth):
            return StopResult("already_stopped", "original_process_absent", observation)
    except (ValueError, TypeError, OSError, psutil.Error) as error:
        LOGGER.warning("Driver stop rejected: row=%s reason=%s", index, error, exc_info=True)
        return StopResult("rejected", str(error), observation)
    try:
        process.send_signal(signal.SIGTERM)
    except psutil.NoSuchProcess:
        return StopResult("already_stopped", "original_process_absent", observation)
    except (psutil.Error, OSError, NotImplementedError) as error:
        LOGGER.warning("Driver stop signal failed: pid=%s run=%s", process.pid,
                       original.run_id, exc_info=True)
        return StopResult("failed", type(error).__name__, observation)
    deadline = clock() + timeout
    try:
        while True:
            absent = _absent(process, birth)
            observation = observe()
            if observation.metadata is not None and (
                    observation.metadata.pid != original.pid
                    or observation.metadata.run_id != original.run_id):
                return StopResult("unconfirmed", "owner_changed", observation)
            if observation.state == "?":
                return StopResult("unconfirmed", observation.reason, observation)
            if absent:
                return StopResult("stopped", "original_process_absent", observation)
            if clock() >= deadline:
                LOGGER.warning("Driver stop unconfirmed: pid=%s run=%s", process.pid, original.run_id)
                return StopResult("unconfirmed", "stop_timeout", observation)
            sleep(min(interval, max(0, deadline - clock())))
    except (psutil.Error, OSError, ValueError, TypeError, NotImplementedError):
        LOGGER.warning("Driver stop confirmation unavailable: pid=%s", process.pid, exc_info=True)
        return StopResult("unconfirmed", "inspection_unavailable", observation)
