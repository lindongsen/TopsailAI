"""Conservative stats maintenance, independent of metadata and application logging.

Author: DawsonLin. Portable default deliberately has no foreign deletion authority.
"""

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import re
import stat
from typing import Callable

from topsailai.workspace.session_stats_writer import Diagnostic, StorageConfig, emit

GROUP = re.compile(
    r"(?P<session>[A-Za-z0-9_-]{1,64})\.(?P<pid>[1-9][0-9]{0,19})"
    r"\.session\.stats(?:\.[1-9][0-9]*)?\.jsonl")


class ProcessState(Enum):
    """Only authoritative absence grants eligibility, not deletion capability."""

    ALIVE = "alive"
    CONFIRMED_ABSENT = "confirmed_absent"
    UNKNOWN = "unknown"


def observe_process(pid: int) -> ProcessState:
    """Portable fallback cannot prove foreign absence; PID reuse is never absence."""
    return ProcessState.ALIVE if pid == os.getpid() else ProcessState.UNKNOWN


@dataclass(frozen=True)
class FileIdentity:
    """Scanned file identity passed to a separately supplied safe deletion authority."""

    device: int
    inode: int
    size: int
    mtime_ns: int
    ctime_ns: int

    @classmethod
    def read(cls, path: Path):
        """Reject symlinks/nonregular entries and preserve identity for revalidation."""
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("not a regular file")
        return cls(info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


@dataclass(frozen=True)
class Member:
    """Immutable scan result; never sufficient by itself to authorize unlink."""

    path: Path
    identity: FileIdentity


class StatsRetention:
    """No default unlink: portable stat-then-unlink cannot preserve foreign identity.

    safe_delete(path, identity) must independently guarantee identity-preserving
    deletion under its deployment's coordination protocol and return literal True.
    A plain unlink callback is NOT a conforming production implementation. Tests
    inject a fixture-owned serialized capability. A future deployment adapter must
    receive independent review; absence alone cannot create such a capability.
    """

    def __init__(self, directory: Path, *, diagnostic: Diagnostic,
                 config: StorageConfig = StorageConfig(),
                 observer: Callable[[int], ProcessState] = observe_process,
                 safe_delete: Callable[[Path, FileIdentity], bool] | None = None):
        """Bind explicit capabilities; read no environment and start no maintenance loop."""
        if not directory.is_absolute():
            raise ValueError("stats directory must be absolute")
        self.directory = directory
        self.diagnostic = diagnostic
        self.config = config
        self.observer = observer
        self.safe_delete = safe_delete

    def _state(self, pid: int) -> ProcessState:
        """Treat observer failures and malformed answers as uncertainty."""
        if pid == os.getpid():
            return ProcessState.ALIVE
        try:
            result = self.observer(pid)
            return result if isinstance(result, ProcessState) else ProcessState.UNKNOWN
        except Exception:
            emit(self.diagnostic, "observer_failure", self.directory)
            return ProcessState.UNKNOWN

    def _scan(self) -> dict[tuple[str, int], list[Member]]:
        """Discover exact stats groups including backups-only groups; skip scan races."""
        groups = {}
        for path in self.directory.iterdir():
            match = GROUP.fullmatch(path.name)
            if match is not None and int(match["pid"]) <= 18446744073709551615:
                self._add(groups, (match["session"], int(match["pid"])), path)
        return groups

    def _add(self, groups, key, path):
        """Capture a regular entry without following symlinks."""
        try:
            member = Member(path, FileIdentity.read(path))
        except (OSError, ValueError):
            emit(self.diagnostic, "scan_skip", path)
            return
        groups.setdefault(key, []).append(member)

    def _delete(self, pid: int, member: Member) -> bool:
        """Recheck absence and identity, then delegate actual atomic authority or skip."""
        if self.safe_delete is None or self._state(pid) is not ProcessState.CONFIRMED_ABSENT:
            return False
        try:
            identity = FileIdentity.read(member.path)
        except FileNotFoundError:
            return True
        except Exception:
            emit(self.diagnostic, "delete_failed", member.path)
            return False
        if identity != member.identity:
            return False
        try:
            if not emit(self.diagnostic, "delete_attempt", member.path):
                return False
            if self._state(pid) is not ProcessState.CONFIRMED_ABSENT:
                return False
            deleted = self.safe_delete(member.path, member.identity) is True
        except Exception:
            emit(self.diagnostic, "delete_failed", member.path)
            return False
        emit(self.diagnostic, "deleted" if deleted else "delete_skipped", member.path)
        return deleted

    def sweep(self, *, now: float) -> int:
        """Age members independently, then evict oldest eligible groups for count target.

        Zero age/count disables that dimension. Live/uncertain groups can exceed
        the target indefinitely. No background thread, exit work or strict quota.
        """
        try:
            groups = self._scan()
        except OSError:
            emit(self.diagnostic, "scan_failure", self.directory)
            return 0
        deleted = self._age(groups, now)
        limit = self.config.max_groups
        if not limit:
            return deleted
        ordered = sorted(groups, key=lambda key: (
            max(member.identity.mtime_ns for member in groups[key]), key))
        for key in ordered:
            if len(groups) <= limit:
                break
            deleted += self._remove_group(groups, key)
        return deleted

    def _age(self, groups, now: float) -> int:
        """Retain failed/unsafe deletions so count enforcement cannot assume success."""
        if not self.config.retention_days:
            return 0
        cutoff = (now - self.config.retention_days * 86400) * 1_000_000_000
        deleted = 0
        for key in list(groups):
            retained = []
            for member in groups[key]:
                removed = member.identity.mtime_ns < cutoff and self._delete(key[1], member)
                deleted += bool(removed)
                if not removed:
                    retained.append(member)
            if retained:
                groups[key] = retained
            else:
                del groups[key]
        return deleted

    def _remove_group(self, groups, key) -> int:
        """Allow partial group settlement; unresolved members remain protected."""
        removed = [member for member in groups[key] if self._delete(key[1], member)]
        if len(removed) == len(groups[key]):
            del groups[key]
        return len(removed)
