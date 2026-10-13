"""Read driver-owned lifecycle evidence without acquiring control authority.

Author: DawsonLin
Command identity is best-effort evidence, not an authoritative birth identity.
"""

from dataclasses import dataclass
from enum import Enum
import json
import logging
import os
from pathlib import Path
import re
import stat
from typing import Callable, Literal

import psutil

LOGGER = logging.getLogger(__name__)
MAX_METADATA_BYTES = 65536
DriverState = Literal["-", "ON", "STALE", "EXIT", "FAIL", "?"]


class ProcessEvidence(Enum):
    """Distinguish verified identity, confirmed absence, and uncertainty."""

    VERIFIED = "verified"
    ABSENT = "absent"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class DriverMetadata:
    """Retain only validated, immutable lifecycle fields."""

    version: int
    session_id: str
    pid: int
    run_id: str
    status: Literal["running", "stopped", "failed"]


@dataclass(frozen=True)
class DriverObservation:
    """Expose detached evidence and a non-sensitive diagnostic code."""

    state: DriverState
    reason: str
    metadata: DriverMetadata | None = None
    verification: ProcessEvidence = ProcessEvidence.UNKNOWN

    @property
    def driver_pid(self) -> int | None:
        """Return the driver PID, never the target-session PID."""
        return self.metadata.pid if self.metadata else None

    @property
    def run_id(self) -> str | None:
        """Return a validated run identifier when available."""
        return self.metadata.run_id if self.metadata else None


def metadata_path(topsailai_home: str | Path, session_id: str) -> Path:
    """Validate external filename syntax before composing an absolute path."""
    if (not isinstance(session_id, str) or session_id in ("topsailai", "(temp)")
            or ".." in session_id
            or re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]{0,199}", session_id) is None):
        raise ValueError("unsafe_session_id")
    home = Path(topsailai_home)
    if not home.is_absolute() or ".." in home.parts:
        raise ValueError("invalid_home")
    # The caller-configured HOME is trusted deployment authority and may be an
    # alias. Resolve only that root, never metadata-controlled descendants;
    # _read_metadata still rejects symlinks in the canonical path and subtree.
    return home.resolve() / "workspace" / "task" / "session_agent_driver" / (session_id + ".meta")


def _read_metadata(path: Path) -> bytes | None:
    """Use no-follow directory custody and bounded regular-file reads."""
    if (not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY")
            or os.open not in os.supports_dir_fd):
        raise ValueError("safe_read_unsupported")
    directory = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for component in path.parts[1:-1]:
            child = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                            dir_fd=directory)
            os.close(directory)
            directory = child
        try:
            before = os.stat(path.name, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            return None
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("metadata_not_regular")
        descriptor = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
                             dir_fd=directory)
        with os.fdopen(descriptor, "rb") as stream:
            opened = os.fstat(stream.fileno())
            if (not stat.S_ISREG(opened.st_mode)
                    or (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)):
                raise ValueError("metadata_changed")
            data = stream.read(MAX_METADATA_BYTES + 1)
        if len(data) > MAX_METADATA_BYTES:
            raise ValueError("metadata_too_large")
        return data
    finally:
        os.close(directory)


def _parse_metadata(data: bytes, session_id: str) -> DriverMetadata:
    """Validate the v1 boundary before constructing an owned domain record."""
    value = json.loads(data.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("invalid_metadata_shape")
    if type(value.get("version")) is not int or value["version"] != 1:
        raise ValueError("unsupported_metadata_version")
    if value.get("session_id") != session_id:
        raise ValueError("metadata_session_mismatch")
    if type(value.get("pid")) is not int or value["pid"] <= 0:
        raise ValueError("invalid_driver_pid")
    run_id = value.get("run_id")
    if not isinstance(run_id, str) or re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        raise ValueError("invalid_run_id")
    status = value.get("status")
    if not isinstance(status, str) or status not in ("running", "stopped", "failed"):
        raise ValueError("unsupported_metadata_status")
    return DriverMetadata(1, session_id, value["pid"], run_id, status)


def _matches_command(command: list[str], metadata: DriverMetadata,
                     entry: Path, cwd: str) -> bool:
    """Match a concrete driver entry and one explicit exact session argument."""
    if not command:
        return False
    # A script must be the executable or Python's script argument, not shell text.
    index = 1 if Path(command[0]).name.lower().startswith("python") else 0
    if len(command) <= index:
        return False
    candidate = Path(command[index])
    if not candidate.is_absolute():
        candidate = Path(cwd) / candidate
    if candidate.resolve() != entry.resolve():
        return False
    arguments = command[index + 1:]
    sessions = []
    for offset, argument in enumerate(arguments):
        if argument in ("--session", "-s"):
            sessions.append(arguments[offset + 1] if offset + 1 < len(arguments) else None)
        elif argument.startswith("--session="):
            sessions.append(argument.split("=", 1)[1])
    return sessions == [metadata.session_id]


def probe_driver_process(metadata: DriverMetadata, *,
                         driver_entry: Path | None = None) -> ProcessEvidence:
    """Require caller-validated entry authority; query identity without signals."""
    if driver_entry is None:
        return ProcessEvidence.UNKNOWN
    entry = driver_entry
    try:
        process = psutil.Process(metadata.pid)
        birth = process.create_time()
        command = process.cmdline()
        cwd = process.cwd()
        if process.status() in (psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD):
            return ProcessEvidence.ABSENT
        if not process.is_running() or process.create_time() != birth:
            return ProcessEvidence.UNKNOWN
        if _matches_command(command, metadata, entry, cwd):
            return ProcessEvidence.VERIFIED
        return ProcessEvidence.UNKNOWN
    except psutil.NoSuchProcess:
        return ProcessEvidence.ABSENT
    except (psutil.Error, OSError, ValueError, NotImplementedError):
        return ProcessEvidence.UNKNOWN


def observe_driver(topsailai_home: str | Path, session_id: str, *,
                   process_probe: Callable[[DriverMetadata], ProcessEvidence] = probe_driver_process
                   ) -> DriverObservation:
    """Observe one session without writing metadata, locks, logs, or signals."""
    metadata = None
    try:
        path = metadata_path(topsailai_home, session_id)
        try:
            data = _read_metadata(path)
        except FileNotFoundError:
            # Missing directories are absence; disappearance after lstat is uncertain.
            if not path.parent.exists():
                return DriverObservation("-", "metadata_missing")
            raise ValueError("metadata_disappeared")
        if data is None:
            return DriverObservation("-", "metadata_missing")
        metadata = _parse_metadata(data, session_id)
        evidence = process_probe(metadata)
    except (OSError, ValueError, TypeError, RecursionError) as error:
        reason = str(error) if type(error) is ValueError and str(error) in {
            "unsafe_session_id", "invalid_home", "safe_read_unsupported",
            "metadata_not_regular", "metadata_changed", "metadata_too_large",
            "invalid_metadata_shape", "unsupported_metadata_version",
            "metadata_session_mismatch", "invalid_driver_pid", "invalid_run_id",
            "unsupported_metadata_status", "metadata_disappeared",
        } else type(error).__name__
        LOGGER.warning("Driver observation rejected: reason=%s type=%s", reason, type(error).__name__)
        return DriverObservation("?", reason, metadata)
    if evidence is ProcessEvidence.UNKNOWN or not isinstance(evidence, ProcessEvidence):
        LOGGER.warning("Driver process identity unverified: pid=%s", metadata.pid)
        return DriverObservation("?", "process_unverified", metadata)
    if metadata.status == "running":
        state = "ON" if evidence is ProcessEvidence.VERIFIED else "STALE"
        return DriverObservation(state, "process_" + evidence.value, metadata, evidence)
    if evidence is ProcessEvidence.VERIFIED:
        return DriverObservation("?", "terminal_process_alive", metadata, evidence)
    state = "EXIT" if metadata.status == "stopped" else "FAIL"
    return DriverObservation(state, "terminal_process_absent", metadata, evidence)
