"""Conservative local session ownership observations (author: DawsonLin)."""

import json
import logging
import os
import re
import socket
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import psutil

logger = logging.getLogger(__name__)

# Owner record suffixes produced by the framework. Every entry must have a
# production writer; unknown suffixes stay malformed evidence and fail closed.
_OWNER_SUFFIXES = (
    "meta",
    "meta.tmp",
    "stdout",
    "stderr",
    "events",
    "pipe",
    "sock",
    "stats.jsonl",
    "agent2llm_inject_messages.jsonl",
    "agent2llm_interrupt.flag",
    "agent2llm_interrupt.fbt_waiting",
    "agent2llm_interrupt.fbt_retry",
    "agent2llm_pause.flag",
)
_OWNER_PATTERN = re.compile(
    r"^(.+)\.([1-9][0-9]*)\.session\.((?:"
    + "|".join(re.escape(suffix) for suffix in _OWNER_SUFFIXES)
    + r"|stats\.[1-9][0-9]*\.jsonl))$"
)


# Only metadata finalized by the owner can help authorize destructive cleanup.
# Running, missing, or future unknown states remain protected.
_CLEANABLE_OWNER_STATUSES = frozenset({"completed", "error", "interrupted"})


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


def observe_control_endpoint(path):
    """Return endpoint liveness while preserving uncertain connection failures."""
    try:
        endpoint = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISSOCK(endpoint.st_mode):
        return False
    socket_path = str(path)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as probe:
            probe.settimeout(0.5)
            probe.connect(socket_path)
            return True
    except (FileNotFoundError, ConnectionRefusedError):
        return False


def local_hostname():
    """Return the local host identity, or an empty value when unavailable."""
    try:
        return socket.gethostname().strip()
    except (OSError, RuntimeError):
        logger.warning("Cannot resolve local hostname for session cleanup", exc_info=True)
        return ""


def normalize_home_path(value):
    """Normalize a home path exactly as the folder constants define it.

    The folder constants are the single authority for the home spelling and
    they use ``os.path.abspath``, which collapses ``..`` but deliberately keeps
    symbolic links unresolved. Cleanup authorization compares a recorded home
    against an admitted root, so both sides must use this one spelling:
    ``Path.resolve`` would follow a symlinked home and never match the recorded
    value, which silently refuses every deletion.

    Returns:
        str: The normalized path, or ``""`` when the value is empty.
    """
    if not value:
        return ""
    return os.path.abspath(os.path.expanduser(str(value)))


class SessionActivityProbe:
    """Authorize cleanup only from strict, host-local ownership evidence."""

    def __init__(self, task_dirs=(), process_observer=observe_process,
                 endpoint_observer=observe_control_endpoint, hostname=None):
        """Accept boundary-resolved roots and injectable liveness authorities."""
        self.task_dirs = tuple(Path(normalize_home_path(p)) for p in task_dirs)
        self.process_observer = process_observer
        self.endpoint_observer = endpoint_observer
        self.hostname = local_hostname() if hostname is None else hostname

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
            normalized = normalize_home_path(home)
            recorded = Path(normalized) / "workspace" / "task" if normalized else None
            if recorded is None or recorded not in roots:
                results.update(
                    (sid, ActivityObservation(ActivityState.UNKNOWN, "unverified recorded home"))
                    for sid in valid
                )
                return results
        root_results = [self._observe_root_many(root, valid) for root in roots]
        for session_id in valid:
            observations = [item[session_id] for item in root_results]
            if any(item.state == ActivityState.RUNNING for item in observations):
                results[session_id] = ActivityObservation(ActivityState.RUNNING, "live associated owner")
            elif any(item.state == ActivityState.UNKNOWN for item in observations):
                results[session_id] = ActivityObservation(ActivityState.UNKNOWN, "incomplete owner evidence")
            else:
                results[session_id] = ActivityObservation(ActivityState.STOPPED, "all verified local owners absent")
        return results

    def can_clean(self, session_id, home=None):
        """Authorize cleanup only after a fresh strict STOPPED observation."""
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
        pattern = _OWNER_PATTERN
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
        """Require one strict metadata record for every discovered owner PID."""
        if not owners:
            return ActivityObservation(ActivityState.UNKNOWN, "no run records")
        grouped = {}
        for name, pid in owners:
            grouped.setdefault(pid, []).append(name)
        states = [
            self._observe_owner(root, session_id, pid, names)
            for pid, names in grouped.items()
        ]
        if malformed:
            states.append(ActivityState.UNKNOWN)
        if ActivityState.RUNNING in states:
            return ActivityObservation(ActivityState.RUNNING, "live owner")
        state = ActivityState.UNKNOWN if ActivityState.UNKNOWN in states else ActivityState.STOPPED
        return ActivityObservation(state, "strict owner inventory")

    def _observe_owner(self, root, session_id, pid, names):
        """Protect live owners; authorize stopped only from stable local metadata."""
        socket_path = root / f"{session_id}.{pid}.session.sock"
        try:
            if self.endpoint_observer(socket_path):
                return ActivityState.RUNNING
        except (OSError, ValueError, TypeError, RuntimeError):
            logger.warning("Cannot probe session endpoint %s", socket_path, exc_info=True)
            return ActivityState.UNKNOWN
        try:
            state = self.process_observer(pid)
        except (OSError, ValueError, TypeError, RuntimeError, psutil.Error):
            logger.warning("Cannot observe session PID %s", pid, exc_info=True)
            state = ActivityState.UNKNOWN
        if state == ActivityState.RUNNING:
            return state
        if state != ActivityState.STOPPED:
            return ActivityState.UNKNOWN

        metadata = [name for name in names if name.endswith(".session.meta")]
        if len(metadata) != 1:
            return ActivityState.UNKNOWN
        path = root / metadata[0]
        try:
            first = path.lstat()
            if not stat.S_ISREG(first.st_mode):
                return ActivityState.UNKNOWN
            with path.open("rb") as stream:
                data = json.loads(stream.read(65537))
            if not isinstance(data, dict) or data.get("pid") != pid:
                return ActivityState.UNKNOWN
            if data.get("session_id") != session_id and not (
                    session_id == "topsailai" and data.get("session_id") == ""):
                return ActivityState.UNKNOWN
            owner_hostname = data.get("hostname")
            if not isinstance(owner_hostname, str) or not owner_hostname.strip():
                return ActivityState.UNKNOWN
            if not self.hostname or owner_hostname.strip() != self.hostname:
                return ActivityState.UNKNOWN
            if data.get("status") not in _CLEANABLE_OWNER_STATUSES:
                return ActivityState.UNKNOWN
            last = path.lstat()
            identity = (first.st_dev, first.st_ino, first.st_mode, first.st_size, first.st_mtime_ns)
            if identity != (last.st_dev, last.st_ino, last.st_mode, last.st_size, last.st_mtime_ns):
                return ActivityState.UNKNOWN
            return ActivityState.STOPPED
        except (OSError, ValueError, TypeError, psutil.Error):
            logger.warning("Cannot validate session owner %s", path.name, exc_info=True)
            return ActivityState.UNKNOWN
