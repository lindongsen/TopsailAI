"""Unconditional resource teardown for focused Hooks process tests."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from topsailai.hooks.process_backend import IsolatedProcessBackend
from topsailai.hooks.process_state import LaunchRecord


@pytest.fixture(autouse=True)
def reap_focused_hook_processes(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Converge every exact worker, launch record, channel, and debt after each test."""
    backends: list[IsolatedProcessBackend] = []
    processes: list[subprocess.Popen[bytes]] = []
    records: dict[int, tuple[IsolatedProcessBackend, LaunchRecord]] = {}
    original_init = IsolatedProcessBackend.__init__
    original_spawn = IsolatedProcessBackend._spawn
    original_popen = subprocess.Popen

    def tracked_init(self, *args, **kwargs):
        original_init(self, *args, **kwargs)
        backends.append(self)

    def tracked_spawn(self, interpreter, deadline, record):
        records[id(record)] = (self, record)
        return original_spawn(self, interpreter, deadline, record)

    def tracked_popen(*args, **kwargs):
        process = original_popen(*args, **kwargs)
        if kwargs.get("start_new_session") is True:
            processes.append(process)
        return process

    monkeypatch.setattr(IsolatedProcessBackend, "__init__", tracked_init)
    monkeypatch.setattr(IsolatedProcessBackend, "_spawn", tracked_spawn)
    monkeypatch.setattr(subprocess, "Popen", tracked_popen)
    yield

    failures: list[str] = []
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        _attempt_all_cleanup(backends, records, processes, failures)
        if _resources_converged(backends, records, processes):
            break
        time.sleep(0.01)
    _attempt_all_cleanup(backends, records, processes, failures)
    unresolved = _resource_failures(backends, records, processes)
    if unresolved:
        unresolved.extend(failures)
    assert not unresolved, "focused Hook teardown failed:\n" + "\n".join(unresolved)


def _attempt_all_cleanup(
    backends: list[IsolatedProcessBackend],
    records: dict[int, tuple[IsolatedProcessBackend, LaunchRecord]],
    processes: list[subprocess.Popen[bytes]],
    failures: list[str],
) -> None:
    """Attempt each owned resource independently without signaling historical groups."""
    tracked_ids = {record.debt_id for _, record in records.values()}
    process_ids = {id(process) for process in processes}
    for backend in backends:
        for debt in backend.cleanup_debts():
            entry = backend._debt_processes.get(debt.debt_id)
            relevant = debt.debt_id in tracked_ids or (
                entry is not None and id(entry.process) in process_ids
            )
            if not relevant:
                continue
            try:
                backend.retry_cleanup(debt.debt_id)
            except BaseException as exc:
                failures.append(f"debt {debt.debt_id}: {type(exc).__name__}")
    for backend, record in records.values():
        process = record.process
        if process is None or process not in processes:
            continue
        try:
            with backend._cleanup_execution_lease(record) as lease:
                if lease is None:
                    continue
                try:
                    if process.poll() is None:
                        record.cleanup.termination_confirmed = backend._terminate_owned(process)
                except BaseException as exc:
                    failures.append(f"record {record.debt_id} process: {type(exc).__name__}")
                try:
                    backend._close_record_channels(record)
                except BaseException as exc:
                    failures.append(f"record {record.debt_id} channels: {type(exc).__name__}")
                if record.cleanup.termination_confirmed and not _channel_failures(record):
                    backend._resolve_debt(record.debt_id, record)
        except BaseException as exc:
            failures.append(f"record {record.debt_id} lease: {type(exc).__name__}")
    for process in processes:
        if not backends:
            continue
        try:
            if process.poll() is None and not backends[-1]._terminate_owned(process):
                failures.append(f"process group {process.pid}: termination unconfirmed")
        except BaseException as exc:
            failures.append(f"process group {process.pid}: {type(exc).__name__}")


def _channel_failures(record: LaunchRecord) -> list[str]:
    """Validate channel state and the actual descriptor or stream resource."""
    failures: list[str] = []
    process = record.process
    for name, channel in record.cleanup.channels.items():
        if channel.state != "closed" or channel.resource is not None:
            failures.append(name)
            continue
        if name == "result":
            if record.result_fd is not None:
                failures.append(name)
            continue
        stream = getattr(process, name, None) if process is not None else None
        if stream is not None and not stream.closed:
            failures.append(name)
    return failures


def _resources_converged(
    backends: list[IsolatedProcessBackend],
    records: dict[int, tuple[IsolatedProcessBackend, LaunchRecord]],
    processes: list[subprocess.Popen[bytes]],
) -> bool:
    """Return whether every exact resource created by this test has converged."""
    return not _resource_failures(backends, records, processes)


def _resource_failures(
    backends: list[IsolatedProcessBackend],
    records: dict[int, tuple[IsolatedProcessBackend, LaunchRecord]],
    processes: list[subprocess.Popen[bytes]],
) -> list[str]:
    """Describe unresolved resources without signaling identity-uncertain groups."""
    failures: list[str] = []
    for process in processes:
        backend = backends[-1] if backends else None
        if process.poll() is None:
            failures.append(f"worker {process.pid} remains alive")
        elif backend is not None and backend._group_exists(process.pid):
            failures.append(f"historical process group {process.pid} remains uncertain")
    for _, record in records.values():
        if record.process is None:
            if record.state not in ("failed", "abandoned"):
                failures.append(f"launch record {record.debt_id} remains unpublished")
            continue
        if record.process in processes:
            open_names = _channel_failures(record)
            if open_names:
                failures.append(f"record {record.debt_id} channels remain: {open_names}")
    tracked_ids = {record.debt_id for _, record in records.values()}
    process_ids = {id(process) for process in processes}
    for backend in backends:
        for debt in backend.cleanup_debts():
            entry = backend._debt_processes.get(debt.debt_id)
            if debt.debt_id in tracked_ids or (
                entry is not None and id(entry.process) in process_ids
            ):
                failures.append(f"cleanup debt remains: {debt.debt_id} ({debt.state})")
    return failures


@pytest.fixture
def trust_eligible_tmp_path() -> Iterator[Path]:
    """Provide a task-local temp root whose ancestry satisfies artifact trust.

    Artifact capture rejects any source-ancestry directory that is group- or
    other-writable, so the default pytest basetemp under ``/tmp`` (mode 1777)
    can never host a trusted source tree. This fixture yields an independent
    root created under the workspace ``.tmp`` directory, whose ancestry is
    0755. It is opt-in so tests that depend on the default basetemp,
    including privilege-dropping and socket-path cases, keep their existing
    behaviour.
    """
    workspace_tmp = Path(__file__).resolve().parents[3] / ".tmp"
    workspace_tmp.mkdir(mode=0o755, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix="trust-", dir=workspace_tmp))
    try:
        yield root
    finally:
        shutil.rmtree(root, ignore_errors=True)
