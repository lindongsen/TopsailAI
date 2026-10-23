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
        if not isinstance(session_id, str) or not session_id:
            return ActivityObservation(ActivityState.UNKNOWN, "missing local authority")
        return self.observe_many((session_id,), home)[session_id]

    def observe_many(self, session_ids, home=None):
        """Observe multiple sessions from one stable inventory per admitted root."""
        requested = tuple(dict.fromkeys(session_ids))
        invalid = [sid for sid in requested if not isinstance(sid, str) or not sid]
        results = {
            sid: ActivityObservation(ActivityState.UNKNOWN, "missing local authority")
            for sid in invalid
        }
        valid = tuple(sid for sid in requested if sid not in results)
        if not valid or not self.task_dirs:
            results.update(
                (sid, ActivityObservation(ActivityState.UNKNOWN, "missing local authority"))
                for sid in valid
            )
            return results
        roots = self.task_dirs
        if home is not None:
            recorded = Path(home).absolute() / "workspace" / "task"
            if not home or recorded not in roots:
                results.update(
                    (sid, ActivityObservation(ActivityState.UNKNOWN, "unverified recorded home"))
                    for sid in valid
                )
                return results
        root_results = [self._observe_root_many(root, valid) for root in roots]
        for session_id in valid:
            observations = [item[session_id] for item in root_results]
            if any(item.state == ActivityState.RUNNING for item in observations):
                results[session_id] = ActivityObservation(ActivityState.RUNNING, "live associated PID")
            elif any(item.state == ActivityState.UNKNOWN for item in observations):
                results[session_id] = ActivityObservation(ActivityState.UNKNOWN, "incomplete owner evidence")
            else:
                results[session_id] = ActivityObservation(ActivityState.STOPPED, "all recorded owners absent")
        return results

    def can_clean(self, session_id, home=None):
        """Authorize cleanup only after a fresh STOPPED observation."""
        result = self.observe(session_id, home)
        if result.state != ActivityState.STOPPED:
            logger.info("Preserve session %s: %s (%s)", session_id, result.state.value, result.reason)
        return result.state == ActivityState.STOPPED

    def _observe_root(self, root, session_id):
        """Observe one session while retaining the single-session public behavior."""
        return self._observe_root_many(root, (session_id,))[session_id]

    def _observe_root_many(self, root, session_ids):
        """Aggregate requested owners from one stable root inventory."""
        unknown = ActivityObservation(ActivityState.UNKNOWN, "inventory unreadable")
        try:
            before = tuple(sorted(path.name for path in root.iterdir()))
            owners, malformed = self._index_inventory(before, session_ids)
            observations = {
                session_id: self._observe_session_owners(
                    root,
                    session_id,
                    owners.get(session_id, ()),
                    session_id in malformed,
                )
                for session_id in session_ids
            }
            if tuple(sorted(path.name for path in root.iterdir())) != before:
                return {
                    session_id: ActivityObservation(ActivityState.UNKNOWN, "inventory changed")
                    for session_id in session_ids
                }
            return observations
        except (OSError, ValueError, OverflowError):
            logger.warning("Cannot inspect session inventory", exc_info=True)
            return {session_id: unknown for session_id in session_ids}

    @staticmethod
    def _index_inventory(inventory, session_ids):
        """Index exact owner records in one pass over the captured inventory."""
        requested = set(session_ids)
        owners = {session_id: [] for session_id in session_ids}
        malformed = set()
        pattern = re.compile(r"^(.+)\.([1-9][0-9]*)\.session\.(meta|stdout|stderr|events|pipe|agent2llm_inject_messages\.jsonl)$")
        for name in inventory:
            if ".session." not in name:
                continue
            match = pattern.fullmatch(name)
            exact_session_id = match[1] if match and match[1] in requested else None
            if exact_session_id is not None:
                owners[exact_session_id].append((name, int(match[2])))
            prefixes = {
                name[:index]
                for index, character in enumerate(name)
                if character == "."
            }
            prefixes.discard(exact_session_id)
            malformed.update(prefixes & requested)
        return owners, malformed

    def _observe_session_owners(self, root, session_id, owners, malformed):
        """Evaluate one session from its indexed owner records."""
        if not owners:
            return ActivityObservation(ActivityState.UNKNOWN, "no run records")
        states = [self._observe_owner(root / name, session_id, pid) for name, pid in owners]
        if malformed:
            states.append(ActivityState.UNKNOWN)
        if ActivityState.RUNNING in states:
            return ActivityObservation(ActivityState.RUNNING, "live owner")
        state = ActivityState.UNKNOWN if ActivityState.UNKNOWN in states else ActivityState.STOPPED
        return ActivityObservation(state, "owner inventory")

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
