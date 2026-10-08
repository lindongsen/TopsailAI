"""Public-runtime harness for standalone Unified Hooks behavior."""

from __future__ import annotations

import os
import sys
from dataclasses import replace
from pathlib import Path

from topsailai.hooks import (
    Binding,
    DispatchReport,
    EventDefinition,
    HookLimits,
    HookRuntime,
    HookSettings,
)

_EVENT_NAME = "bdd.host.flow"
_HANDLER_REF = "bdd_worker_observer:record_host_marker"
_FAILURE_REF = "bdd_worker_observer:raise_module_failure"
_NONZERO_REF = "bdd_worker_observer:exit_nonzero"
_MISSING_REF = "bdd_missing_worker:handle"
_STATES = {
    "empty",
    "minimal",
    "handler-failure",
    "process-failure",
    "load-failure",
    "ordered",
}


class UnifiedHooksScenario:
    """Own one standalone runtime and its scenario-local filesystem root."""

    def __init__(self, scenario_path: Path, binding_state: str) -> None:
        """Create an explicit runtime and register the selected public bindings."""
        if binding_state not in _STATES:
            raise ValueError(f"unsupported binding_state: {binding_state}")
        self.binding_state = binding_state
        self.runtime_root = scenario_path / "runtime"
        self.runtime_root.mkdir()
        self.handler_ledger = self.runtime_root / "handler-calls.log"
        self.worker_ledger = self.runtime_root / "worker-launches.log"
        self._write_worker_observer_modules()
        self._runtime_path = str(self.runtime_root.resolve())
        sys.path.insert(0, self._runtime_path)
        self.observed_workers: tuple[tuple[int, str], ...] = ()
        limits = replace(
            HookLimits(),
            workers=1,
            queue_items=8,
            queue_bytes=65_536,
            dispatch_timeout_ms=5_000,
            shutdown_timeout_ms=2_000,
        )
        self.runtime = HookRuntime(
            HookSettings(limits=limits), temp_root=self._runtime_path
        )
        self.scope = self.runtime.open_scope(metadata={"owner_id": "bdd-host"})
        self.definition = EventDefinition(
            _EVENT_NAME,
            1,
            {
                "type": "object",
                "properties": {
                    "ledger_path": {"type": "string"},
                    "marker": {"type": "string"},
                },
                "required": ["ledger_path", "marker"],
            },
        )
        self.report: DispatchReport | None = None
        self.host_markers: list[str] = []
        self.closed_scope_ids: tuple[str, ...] = ()
        self.cleanup_debts = ()
        self.closed = False
        registrations = [self._register(binding) for binding in self._bindings()]
        if binding_state == "empty":
            unregistration = self.runtime.unregister(registrations[0].handle)
            if not unregistration.accepted:
                raise RuntimeError(
                    f"BDD hook unregistration failed: {unregistration.errors}"
                )

    def _write_worker_observer_modules(self) -> None:
        """Write scenario-owned observers loaded by each real isolated worker."""
        startup_source = f'''import os
from pathlib import Path

if os.environ.get("TOPSAILAI_HOOK_WORKER") == "1":
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    record = f"{{os.getpid()}}:{{fields[21]}}\\n".encode("utf-8")
    descriptor = os.open({str(self.worker_ledger)!r}, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, record)
    finally:
        os.close(descriptor)
'''
        handler_source = '''import os
from pathlib import Path


def _identity():
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    return f"{os.getpid()}:{fields[21]}"


def _record(context):
    path = context.event.payload["ledger_path"]
    descriptor = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, f"{context.binding_id},{_identity()}\\n".encode("utf-8"))
    finally:
        os.close(descriptor)


def record_host_marker(context):
    _record(context)
    return {"binding": context.binding_id, "marker": context.event.payload["marker"]}


def raise_module_failure(context):
    _record(context)
    raise RuntimeError("BDD module hook failure")


def exit_nonzero(context):
    _record(context)
    os._exit(7)
'''
        (self.runtime_root / "sitecustomize.py").write_text(
            startup_source, encoding="utf-8"
        )
        (self.runtime_root / "bdd_worker_observer.py").write_text(
            handler_source, encoding="utf-8"
        )

    def _binding(
        self,
        binding_id: str,
        handler_ref: str = _HANDLER_REF,
        **changes: object,
    ) -> Binding:
        """Build one valid public binding for the scenario event."""
        return replace(
            Binding(binding_id, _EVENT_NAME, 1, handler_ref),
            **changes,
        )

    def _bindings(self) -> tuple[Binding, ...]:
        """Return the public binding plan for this behavior scenario."""
        if self.binding_state in {"empty", "minimal"}:
            return (self._binding("bdd-observer"),)
        if self.binding_state == "handler-failure":
            return (
                self._binding("failed", _FAILURE_REF, priority=10),
                self._binding("independent", priority=20),
            )
        if self.binding_state == "process-failure":
            return (
                self._binding("nonzero", _NONZERO_REF, priority=10),
                self._binding("independent", priority=20),
            )
        if self.binding_state == "load-failure":
            return (
                self._binding("missing", _MISSING_REF, priority=10),
                self._binding("valid", priority=20),
            )
        return (
            self._binding("gamma", priority=30),
            self._binding("beta", priority=10),
            self._binding("alpha", priority=10),
        )

    def _register(self, binding: Binding):
        """Register one binding or fail the scenario at its public boundary."""
        registration = self.runtime.register(self.definition, binding, self.scope)
        if not registration.accepted or registration.handle is None:
            raise RuntimeError(f"BDD hook registration failed: {registration.errors}")
        return registration

    def run_host_flow(self) -> DispatchReport:
        """Bracket one dispatch with markers owned by the host main flow."""
        self.host_markers.append("host-before")
        event = self.runtime.make_event(
            self.scope,
            _EVENT_NAME,
            1,
            {
                "ledger_path": str(self.handler_ledger.resolve()),
                "marker": "runtime-observed",
            },
            operation_id="bdd-operation",
            layer="bdd-host",
            purpose="runtime-behavior",
        )
        self.report = self.runtime.dispatch(event)
        self.host_markers.append("host-after")
        return self.report

    def close(self) -> None:
        """Close the exact runtime once and retain its public close report."""
        if self.closed:
            return
        try:
            close_report = self.runtime.close()
            self.closed_scope_ids = close_report.closed_scope_ids
            self.cleanup_debts = close_report.cleanup_debts
            self.observed_workers = tuple(self._worker_records())
            self.closed = True
        finally:
            if self._runtime_path in sys.path:
                sys.path.remove(self._runtime_path)

    def assert_report(self) -> None:
        """Assert the public report contract for the selected B02/B03 behavior."""
        assert self.report is not None
        assert self.report.rejection_reason is None
        if self.binding_state == "empty":
            assert self.report.outcomes == ()
            return
        outcomes = self.report.outcomes
        expected = {
            "minimal": (("bdd-observer", "success", None),),
            "handler-failure": (
                ("failed", "error", "handler_error"),
                ("independent", "success", None),
            ),
            "process-failure": (
                ("nonzero", "worker_lost", "protocol_error"),
                ("independent", "success", None),
            ),
            "load-failure": (
                ("missing", "error", "import_error"),
                ("valid", "success", None),
            ),
            "ordered": (
                ("alpha", "success", None),
                ("beta", "success", None),
                ("gamma", "success", None),
            ),
        }[self.binding_state]
        actual = tuple(
            (outcome.binding_id, outcome.status.value, outcome.error_category)
            for outcome in outcomes
        )
        assert actual == expected
        for outcome in outcomes:
            if outcome.status.value == "success":
                assert outcome.value["binding"] == outcome.binding_id
                assert outcome.value["marker"] == "runtime-observed"

    @staticmethod
    def _read_lines(path: Path) -> list[str]:
        """Read one optional scenario-owned append-only ledger."""
        return path.read_text(encoding="utf-8").splitlines() if path.exists() else []

    def _worker_records(self) -> list[tuple[int, str]]:
        """Parse exact PID/start-time identities observed at worker startup."""
        records = []
        for identity in self._read_lines(self.worker_ledger):
            pid_text, start_time = identity.split(":", 1)
            records.append((int(pid_text), start_time))
        return records

    @staticmethod
    def _worker_identity_is_gone(pid: int, start_time: str) -> bool:
        """Return whether the exact observed process identity no longer exists."""
        try:
            fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").split()
        except FileNotFoundError:
            return True
        return fields[21] != start_time

    def assert_execution_counts(self) -> None:
        """Assert separate real-worker launch and handler-call cardinalities."""
        assert self.report is not None
        outcome_ids = [outcome.binding_id for outcome in self.report.outcomes]
        assert len(outcome_ids) == len(set(outcome_ids))
        assert all(outcome.started for outcome in self.report.outcomes)
        workers = self._worker_records()
        launch_identities = {f"{pid}:{start_time}" for pid, start_time in workers}
        handler_records = self._read_lines(self.handler_ledger)
        handler_ids = [record.split(",", 1)[0] for record in handler_records]
        handler_workers = [record.split(",", 1)[1] for record in handler_records]
        expected_handler_ids = [
            binding_id for binding_id in outcome_ids if binding_id != "missing"
        ]
        assert len(workers) == len(outcome_ids)
        assert len(launch_identities) == len(workers)
        assert handler_ids == expected_handler_ids
        assert len(set(handler_workers)) == len(handler_workers)
        if self.binding_state == "load-failure":
            assert handler_ids == ["valid"]
            assert set(handler_workers) < launch_identities
            assert len(launch_identities - set(handler_workers)) == 1
            return
        assert set(handler_workers) == launch_identities

    def assert_closed(self) -> None:
        """Assert public closure and termination of exact observed workers."""
        assert self.closed
        assert self.scope.scope_id in self.closed_scope_ids
        assert self.scope.closed
        assert self.cleanup_debts == ()
        assert self.runtime.cleanup_debts() == ()
        assert all(
            self._worker_identity_is_gone(pid, start_time)
            for pid, start_time in self.observed_workers
        )
