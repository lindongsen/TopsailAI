"""State records shared by isolated hook process supervision."""

from __future__ import annotations

import subprocess
import threading
from dataclasses import dataclass, field

from topsailai.hooks.contracts import JsonValue


@dataclass(frozen=True, slots=True)
class WorkerResult:
    """Describe one isolated execution and its cleanup certainty."""

    status: str
    value: JsonValue = None
    error_category: str | None = None
    stdout: bytes = b""
    stderr: bytes = b""
    stdout_dropped: int = 0
    stderr_dropped: int = 0
    cleanup_confirmed: bool = True
    cleanup_debt: str | None = None


@dataclass(frozen=True, slots=True)
class CleanupExecutionLease:
    """Identify the exact re-entrant cleanup lease level acquired by one call."""

    owner: int
    depth: int


@dataclass(frozen=True, slots=True)
class CleanupDebt:
    """Describe one queryable cleanup obligation."""

    debt_id: str
    state: str
    pid: int | None
    detail: str


@dataclass(slots=True)
class ChannelCloseState:
    """Track one close obligation and the exact resource that still owns it."""

    state: str = "open"
    descriptor: int | None = None
    identity: tuple[int, int, int] | None = None
    resource: object | None = None
    close_owner: int | None = None
    close_started: bool = False

@dataclass(slots=True)
class CleanupState:
    """Track one authoritative cleanup transaction."""

    state: str = "owned"
    execution_owner: int | None = None
    execution_depth: int = 0
    termination_started: bool = False
    termination_confirmed: bool = False
    debt_state: str = "none"
    result: WorkerResult | None = None
    channels: dict[str, ChannelCloseState] = field(
        default_factory=lambda: {
            name: ChannelCloseState()
            for name in ("stdin", "stdout", "stderr", "result")
        }
    )
@dataclass(slots=True)
class LaunchRecord:
    """Retain process, channel, and cleanup ownership in one record."""

    debt_id: str
    condition: threading.Condition = field(default_factory=threading.Condition)
    state: str = "launching"
    process: subprocess.Popen[bytes] | None = None
    result_fd: int | None = None
    error: BaseException | None = None
    cleanup_confirmed: bool = True
    cleanup_debt: str | None = None
    cleanup: CleanupState = field(default_factory=CleanupState)


@dataclass(slots=True)
class DebtEntry:
    """Retain exclusive retry authority linked to its cleanup record."""

    process: subprocess.Popen[bytes]
    record: LaunchRecord
    state: str = "pending"
