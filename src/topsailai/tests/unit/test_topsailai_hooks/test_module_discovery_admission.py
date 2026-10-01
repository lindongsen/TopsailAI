"""Regression contracts for module-discovery admission and cleanup ownership."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import topsailai.hooks.module_discovery as discovery_module
from topsailai.hooks.process_state import CleanupDebt, WorkerResult
from topsailai.tests.unit.test_topsailai_hooks.module_discovery_helpers import write_module


class _RecordingBackend:
    """Return controlled worker results while retaining exact cleanup authority."""

    instances: list["_RecordingBackend"] = []
    result = WorkerResult("success", {"load_status": "ready", "entry_valid": True})

    def __init__(self, *, temp_root: str) -> None:
        """Record construction for zero-probe assertions."""
        self.temp_root = temp_root
        self.calls: list[str] = []
        self.debts = (
            CleanupDebt("debt-1", "process", 123, "owned cleanup not confirmed"),
        )
        type(self).instances.append(self)

    def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
        """Record one candidate and return the configured result."""
        self.calls.append(context.event.payload["logical_name"])
        return type(self).result

    def cleanup_debts(self) -> tuple[CleanupDebt, ...]:
        """Expose retained cleanup obligations."""
        return self.debts

    def retry_cleanup(self, debt_id: str) -> bool:
        """Resolve only the exact retained debt."""
        if debt_id != "debt-1":
            return False
        self.debts = ()
        return True


def _install_backend(monkeypatch: Any, result: WorkerResult) -> None:
    """Install a fresh controlled backend for one test."""
    _RecordingBackend.instances = []
    _RecordingBackend.result = result
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", _RecordingBackend)


def test_unconfirmed_cleanup_stops_probing_and_retains_recovery_owner(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """Unsettled cleanup prevents readiness and all later candidate admission."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    _install_backend(
        monkeypatch,
        WorkerResult(
            "success",
            {"load_status": "ready", "entry_valid": True},
            cleanup_confirmed=False,
            cleanup_debt="debt-1",
        ),
    )

    result = discovery_module.build_module_manifest(tmp_path, "conversation.started")

    backend = _RecordingBackend.instances[0]
    assert backend.calls == ["alpha"]
    assert [(entry.logical_name, entry.load_status, entry.entry_valid) for entry in result.entries] == [
        ("alpha", "cleanup_pending", False)
    ]
    assert result.recovery_owner is not None
    assert result.recovery_owner.cleanup_debts() == backend.debts
    assert result.recovery_owner.retry_cleanup("debt-1")
    assert result.recovery_owner.cleanup_debts() == ()


def test_interruption_propagates_with_exact_recovery_owner(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An interrupted probe exposes its exact cleanup owner without losing identity."""
    write_module(tmp_path, "alpha")
    write_module(tmp_path, "beta")
    interruption = KeyboardInterrupt("sentinel")

    class InterruptingBackend(_RecordingBackend):
        """Retain one debt before propagating the controlled host interruption."""

        def execute(self, handler_ref: str, context: Any, timeout_ms: int) -> WorkerResult:
            """Record the first candidate, retain debt, and propagate interruption."""
            self.calls.append(context.event.payload["logical_name"])
            raise interruption

    InterruptingBackend.instances = []
    monkeypatch.setattr(discovery_module, "IsolatedProcessBackend", InterruptingBackend)

    caught: BaseException | None = None
    try:
        discovery_module.build_module_manifest(tmp_path, "conversation.started")
    except BaseException as error:
        caught = error

    assert caught is interruption
    backend = InterruptingBackend.instances[0]
    assert backend.calls == ["alpha"]
    owner = discovery_module.get_interruption_recovery_owner(caught)
    assert owner is not None
    assert owner.cleanup_debts() == backend.debts
    assert owner.retry_cleanup("debt-1")
    assert owner.cleanup_debts() == ()


def test_enumeration_failure_rejects_without_backend_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """An unavailable enumeration is not published as an empty manifest."""
    _install_backend(monkeypatch, WorkerResult("success"))

    def fail_enumeration(root: Path) -> tuple[Path, ...]:
        raise OSError("sentinel")

    monkeypatch.setattr(discovery_module, "_list_children", fail_enumeration)

    result = discovery_module.build_module_manifest(tmp_path, "conversation.started")

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("module enumeration unavailable",)
    assert _RecordingBackend.instances == []


def test_readable_empty_directory_is_accepted(tmp_path: Path, monkeypatch: Any) -> None:
    """A successfully enumerated empty directory remains a valid empty manifest."""
    _install_backend(monkeypatch, WorkerResult("success"))

    result = discovery_module.build_module_manifest(tmp_path, "conversation.started")

    assert result.accepted
    assert result.entries == ()
    assert result.errors == ()
    assert _RecordingBackend.instances == []


def test_resolved_candidate_escape_rejects_without_backend_probe(
    tmp_path: Path, monkeypatch: Any
) -> None:
    """A candidate observed outside the canonical root after resolution is rejected."""
    candidate = write_module(tmp_path, "escaped")
    outside = tmp_path.parent / "outside-hook.py"
    outside.write_text("def main():\n    return None\n", encoding="utf-8")
    _install_backend(monkeypatch, WorkerResult("success"))
    original_resolve = discovery_module._resolve_candidate

    def escape_on_resolve(path: Path) -> Path:
        if path == candidate:
            return outside.resolve()
        return original_resolve(path)

    monkeypatch.setattr(discovery_module, "_resolve_candidate", escape_on_resolve)

    result = discovery_module.build_module_manifest(tmp_path, "conversation.started")

    assert not result.accepted
    assert result.entries == ()
    assert result.errors == ("module path escapes configured root",)
    assert _RecordingBackend.instances == []
