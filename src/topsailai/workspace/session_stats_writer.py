"""Standalone, single-owner stats storage; no Agent wiring or shared logging.

Author: DawsonLin. Call only from the owning process's serialized storage worker.
Input is already schema-validated immutable bytes; success is not durable delivery.
"""

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import re
from typing import Callable, Iterator

from topsailai.workspace.folder_constants import FOLDER_WORKSPACE_TASK

LINE_CAP = 4096
Diagnostic = Callable[[str, str], bool]


@dataclass(frozen=True)
class StorageConfig:
    """Explicit candidate limits; invalid values fall back independently."""

    max_size_bytes: int = 1048576
    max_backups: int = 3
    retention_days: float = 7
    max_groups: int = 100
    fsync: bool = False

    def __post_init__(self):
        """Normalize configuration without reading process environment."""
        limits = (("max_size_bytes", LINE_CAP, 1048576),
                  ("max_backups", 0, 3), ("max_groups", 0, 100))
        for name, minimum, fallback in limits:
            value = getattr(self, name)
            if type(value) is not int or value < minimum:
                object.__setattr__(self, name, fallback)
        age = self.retention_days
        if (type(age) not in (int, float) or not 0 <= age <= 3650000
                or not math.isfinite(age)):
            object.__setattr__(self, "retention_days", 7)
        if type(self.fsync) is not bool:
            object.__setattr__(self, "fsync", False)


@dataclass(frozen=True)
class WriteResult:
    """Explicit storage outcome; failures are never requeued by this layer."""

    ok: bool
    reason: str


def emit(diagnostic: Diagnostic, category: str, path: Path) -> bool:
    """Emit safe bounded categories without shared logger fallback or recursion."""
    try:
        return diagnostic(category, path.name[:128]) is True
    except Exception:
        return False


def stats_path(session_id: str, *, directory=None, pid=None) -> Path:
    """Build a validated destination using the existing task-folder constant."""
    session = "topsailai" if session_id == "" else session_id
    owner = os.getpid() if pid is None else pid
    if type(session) is not str or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", session):
        raise ValueError("invalid stats session")
    if type(owner) is not int or not 1 <= owner <= 18446744073709551615:
        raise ValueError("invalid stats pid")
    root = Path(FOLDER_WORKSPACE_TASK if directory is None else directory)
    if not root.is_absolute():
        raise ValueError("stats directory must be absolute")
    return root / f"{session}.{owner}.session.stats.jsonl"


def framed(line: bytes) -> bool:
    """Check storage framing only, deliberately not the C-owned JSON schema."""
    return (type(line) is bytes and 1 < len(line) <= LINE_CAP
            and line.endswith(b"\n") and b"\n" not in line[:-1]
            and b"\r" not in line[:-1])


class StatsWriter:
    """Serialize calls externally; never share a destination between processes."""

    def __init__(self, session_id: str, *, diagnostic: Diagnostic,
                 directory=None, config: StorageConfig = StorageConfig()):
        """Bind primitives outside checkpoints; start no threads and perform no I/O."""
        self.pid = os.getpid()
        self.path = stats_path(session_id, directory=directory, pid=self.pid)
        self.config = config
        self.diagnostic = diagnostic

    def backup(self, index: int) -> Path:
        """Return the exact numbered backup name, not active.jsonl.N."""
        return self.path.with_name(f"{self.path.stem}.{index}.jsonl")

    def _delete(self, path: Path) -> None:
        """Delete owned files only after independent deletion-attempt logging."""
        if not emit(self.diagnostic, "delete_attempt", path):
            raise OSError("deletion diagnostic unavailable")
        try:
            path.unlink()
        except FileNotFoundError:
            return
        except OSError:
            emit(self.diagnostic, "delete_failed", path)
            raise
        emit(self.diagnostic, "deleted", path)

    def _indices(self) -> list[int]:
        """Re-enumerate actual names after every interrupted rotation, including gaps."""
        pattern = re.compile(re.escape(self.path.stem) + r"\.([1-9][0-9]*)\.jsonl")
        indices = []
        for path in self.path.parent.iterdir():
            match = pattern.fullmatch(path.name)
            if match:
                indices.append(int(match[1]))
        return sorted(indices, reverse=True)

    def _move(self, source: Path, target: Path) -> None:
        """Avoid silent replacement; sole-owner serialization is the authority here."""
        if target.exists():
            self._delete(target)
        try:
            source.rename(target)
        except FileNotFoundError:
            if source.exists():
                raise

    def _rotate(self, damaged: bool) -> None:
        """Stop on first failed operation; next call discovers the actual remaining names."""
        limit = self.config.max_backups
        if damaged and limit == 0:
            raise OSError("corrupt active with backups disabled")
        for index in self._indices():
            if index >= limit:
                self._delete(self.backup(index))
            else:
                self._move(self.backup(index), self.backup(index + 1))
        if limit:
            self._move(self.path, self.backup(1))
        else:
            self._delete(self.path)

    def _inspect(self) -> tuple[int, bool]:
        """Inspect only a bounded tail; refuse an unbounded incomplete fragment."""
        try:
            with self.path.open("rb") as stream:
                size = os.fstat(stream.fileno()).st_size
                stream.seek(max(0, size - LINE_CAP))
                tail = stream.read(LINE_CAP)
        except FileNotFoundError:
            return 0, False
        damaged = bool(tail) and not tail.endswith(b"\n")
        if damaged and size >= LINE_CAP and b"\n" not in tail:
            raise OSError("damaged tail exceeds inspection budget")
        return size, damaged

    def _append(self, line: bytes) -> None:
        """Close on all paths; positive short writes advance, zero writes fail immediately."""
        with self.path.open("ab", buffering=0) as stream:
            remaining = memoryview(line)
            while remaining:
                written = stream.write(remaining)
                if written is None or written <= 0 or written > len(remaining):
                    raise OSError("invalid short write")
                remaining = remaining[written:]
            if self.config.fsync:
                os.fsync(stream.fileno())

    def append(self, line: bytes) -> WriteResult:
        """Reject malformed input before any mutation, including maintenance or mkdir."""
        if not framed(line):
            return WriteResult(False, "invalid_record")
        if self.pid != os.getpid():
            return WriteResult(False, "foreign_process")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.is_symlink():
                raise OSError("symlink destination")
            size, damaged = self._inspect()
            if damaged or size + len(line) > self.config.max_size_bytes:
                self._rotate(damaged)
            self._append(line)
        except (OSError, ValueError):
            emit(self.diagnostic, "storage_failure", self.path)
            return WriteResult(False, "storage_failure")
        return WriteResult(True, "written")


def _reject_constant(value):
    """Reject JSON's nonstandard NaN/Infinity constants."""
    raise ValueError("nonfinite JSON")


def _finite_tree(value) -> bool:
    """Reject overflowed JSON floats as well as explicit nonfinite constants."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite_tree(item) for item in value.values())
    if isinstance(value, list):
        return all(_finite_tree(item) for item in value)
    return True


def read_records(path: Path, *, diagnostic: Diagnostic) -> Iterator[dict]:
    """Skip invalid complete lines in bounded memory; ignore incomplete final lines.

    This is structural storage inspection, not C's full semantic schema validator.
    Consumers must additionally validate the accepted version-1 schema before use.
    """
    with path.open("rb") as stream:
        while True:
            line = stream.readline(LINE_CAP + 1)
            if not line:
                return
            if len(line) > LINE_CAP:
                _discard_line(stream, line)
                emit(diagnostic, "overlong_line", path)
                continue
            if not line.endswith(b"\n"):
                return
            record = _decode(line, path, diagnostic)
            if record is not None:
                yield record


def _discard_line(stream, line: bytes) -> None:
    """Drain an overlong line in bounded chunks before resuming at the next record."""
    while line and not line.endswith(b"\n"):
        line = stream.readline(LINE_CAP + 1)


def _decode(line: bytes, path: Path, diagnostic: Diagnostic):
    """Validate UTF-8, JSON object/version and finite numbers without shared logging."""
    try:
        value = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
        if type(value) is not dict or type(value.get("schema_version")) is not int:
            raise ValueError("invalid record object")
        if value["schema_version"] != 1 or not _finite_tree(value):
            raise ValueError("unsupported or nonfinite record")
        return value
    except (UnicodeError, ValueError, RecursionError):
        emit(diagnostic, "invalid_line", path)
        return None
