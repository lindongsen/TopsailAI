"""Deadline-bounded termination for framework-owned script process groups."""

from __future__ import annotations

import os
import signal
import subprocess
import time
from typing import Any

from topsailai.hooks.process_state import LaunchRecord

def terminate_record(
    backend: Any, record: LaunchRecord, process: subprocess.Popen[bytes]
) -> bool:
    """Terminate one record under immutable cleanup deadline and group authority."""
    if process.poll() is not None:
        return not backend._group_exists(process.pid)
    if record.cleanup_deadline is None:
        return bool(backend._terminate_owned(process))
    if not record.group_authorized:
        return False
    grace = record.termination_grace or backend._cleanup_grace
    pgid = process.pid
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if time.monotonic() >= record.cleanup_deadline:
            return False
        if not _authorized_group_exists(process, pgid):
            return not backend._group_exists(pgid)
        try:
            os.killpg(pgid, sig)
        except ProcessLookupError:
            process.poll()
            return not backend._group_exists(pgid)
        except OSError:
            return False
        end = min(record.cleanup_deadline, time.monotonic() + grace)
        settled = _wait_for_owned_group(backend, process, pgid, end)
        if settled is not None:
            return settled
    process.poll()
    return not backend._group_exists(pgid)


def _wait_for_owned_group(
    backend: Any,
    process: subprocess.Popen[bytes],
    pgid: int,
    deadline: float,
) -> bool | None:
    """Reap the leader while waiting and classify a settled or still-live group."""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            return not backend._group_exists(pgid)
        if not backend._group_exists(pgid):
            process.poll()
            return True
        time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
    if process.poll() is not None:
        return not backend._group_exists(pgid)
    if not backend._group_exists(pgid):
        process.poll()
        return True
    return None


def _authorized_group_exists(process: subprocess.Popen[bytes], pgid: int) -> bool:
    """Authorize signaling only while the exact recorded leader remains live."""
    try:
        if process.poll() is not None:
            return False
        return os.getpgid(process.pid) == pgid
    except (ProcessLookupError, OSError):
        return False


def terminate_unpublished_process(
    backend: Any,
    process: subprocess.Popen[bytes],
    deadline: float,
    grace: float,
) -> bool:
    """Stop one exact child and confirm its untrusted process group is absent."""
    if process.poll() is None:
        for action in (process.terminate, process.kill):
            if time.monotonic() >= deadline:
                return False
            try:
                action()
                process.wait(timeout=max(0.0, min(grace, deadline - time.monotonic())))
            except subprocess.TimeoutExpired:
                continue
            except OSError:
                process.poll()
            if process.poll() is not None:
                break
    if process.poll() is None:
        return False
    return not backend._group_exists(process.pid)
