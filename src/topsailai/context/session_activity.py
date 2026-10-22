"""Conservative local session ownership observations (author: DawsonLin)."""

import json
import logging
import re
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)


class ActivityState(str, Enum):
    """Describe evidence, not a cross-process lifecycle lock."""

    RUNNING = "running"
    STOPPED = "stopped"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ActivityObservation:
    """Carry a bounded explanation for an ownership decision."""

    state: ActivityState
    reason: str


def observe_process(pid):
    """Protect any live PID, including reused PIDs; never signal it."""
    try:
        process = psutil.Process(pid)
        return ActivityState.RUNNING if process.is_running() else ActivityState.STOPPED
    except psutil.NoSuchProcess:
        return ActivityState.STOPPED
    except (psutil.Error, OSError, NotImplementedError):
        logger.warning("Cannot observe session PID %s", pid, exc_info=True)
        return ActivityState.UNKNOWN


class SessionActivityProbe:
    """Observe explicitly supplied local task roots without environment reads."""

    def __init__(self, task_dirs=(), process_observer=observe_process):
        """Accept boundary-resolved local roots and an injectable PID observer."""
        self.task_dirs = tuple(Path(p).absolute() for p in task_dirs)
        self.process_observer = process_observer

    def observe(self, session_id, home=None):
        """Require consistent, nonempty owner evidence in an admitted local root."""
        if not isinstance(session_id, str) or not session_id or not self.task_dirs:
            return ActivityObservation(ActivityState.UNKNOWN, "missing local authority")
        roots = self.task_dirs
        if home is not None:
            recorded = Path(home).absolute() / "workspace" / "task"
            if not home or recorded not in roots:
                return ActivityObservation(ActivityState.UNKNOWN, "unverified recorded home")
        results = [self._observe_root(root, session_id) for root in roots]
        if any(r.state == ActivityState.RUNNING for r in results):
            return ActivityObservation(ActivityState.RUNNING, "live associated PID")
        if any(r.state == ActivityState.UNKNOWN for r in results):
            return ActivityObservation(ActivityState.UNKNOWN, "incomplete owner evidence")
        return ActivityObservation(ActivityState.STOPPED, "all recorded owners absent")

    def can_clean(self, session_id, home=None):
        """Authorize cleanup only after a fresh STOPPED observation."""
        result = self.observe(session_id, home)
        if result.state != ActivityState.STOPPED:
            logger.info("Preserve session %s: %s (%s)", session_id, result.state.value, result.reason)
        return result.state == ActivityState.STOPPED

    def _observe_root(self, root, session_id):
        """Aggregate all exact owner filenames and reject unstable inventories."""
        pattern = re.compile(r"^" + re.escape(session_id) + r"\.([1-9][0-9]*)\.session\.(meta|stdout|stderr|events|pipe|agent2llm_inject_messages\.jsonl)$")
        try:
            before = tuple(sorted(p.name for p in root.iterdir()))
            matches = [(name, pattern.fullmatch(name)) for name in before]
            owners = [(name, int(match[1])) for name, match in matches if match]
            malformed = any(name.startswith(session_id + ".") and ".session." in name and not match
                            for name, match in matches)
            if not owners:
                return ActivityObservation(ActivityState.UNKNOWN, "no run records")
            states = [self._observe_owner(root / name, session_id, pid) for name, pid in owners]
            if malformed:
                states.append(ActivityState.UNKNOWN)
            if ActivityState.RUNNING in states:
                return ActivityObservation(ActivityState.RUNNING, "live owner")
            if tuple(sorted(p.name for p in root.iterdir())) != before:
                return ActivityObservation(ActivityState.UNKNOWN, "inventory changed")
            state = ActivityState.UNKNOWN if ActivityState.UNKNOWN in states else ActivityState.STOPPED
            return ActivityObservation(state, "owner inventory")
        except (OSError, ValueError, OverflowError):
            logger.warning("Cannot inspect session inventory for %s", session_id, exc_info=True)
            return ActivityObservation(ActivityState.UNKNOWN, "inventory unreadable")

    def _observe_owner(self, path, session_id, pid):
        """Validate metadata without reading pipes or trusting completion flags."""
        try:
            state = self.process_observer(pid)
            if state == ActivityState.RUNNING:
                return state
            if state != ActivityState.STOPPED:
                return ActivityState.UNKNOWN
            first = path.lstat()
            if path.suffix == ".meta":
                if not stat.S_ISREG(first.st_mode):
                    return ActivityState.UNKNOWN
                with path.open("rb") as stream:
                    data = json.loads(stream.read(65537))
                if not isinstance(data, dict) or data.get("pid") != pid:
                    return ActivityState.UNKNOWN
                if data.get("session_id") != session_id and not (session_id == "topsailai" and data.get("session_id") == ""):
                    return ActivityState.UNKNOWN
            last = path.lstat()
            if (first.st_dev, first.st_ino, first.st_mode, first.st_size, first.st_mtime_ns) != (last.st_dev, last.st_ino, last.st_mode, last.st_size, last.st_mtime_ns):
                return ActivityState.UNKNOWN
            return ActivityState.STOPPED
        except (OSError, ValueError, TypeError, psutil.Error):
            logger.warning("Cannot validate session owner %s", path.name, exc_info=True)
            return ActivityState.UNKNOWN
