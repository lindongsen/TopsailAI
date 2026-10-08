"""Public-runtime harness for Unified Hooks reload and admission snapshots."""

from __future__ import annotations

import os
import sys
import threading
from dataclasses import replace
from pathlib import Path

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings

from tests.bdd.unified_hooks_lifecycle_harness import UnifiedHooksLifecycleScenario

_EVENT_NAME = "bdd.host.reload"
_HANDLER_REF = "bdd_reload_worker:observe"


class UnifiedHooksReloadScenario(UnifiedHooksLifecycleScenario):
    """Own one public Runtime while observing old and new registry generations."""

    def __init__(self, scenario_path: Path) -> None:
        """Create one scenario with deterministic real-worker admission control."""
        self.runtime_root = scenario_path / "reload-runtime"
        self.worker_ledger = self.runtime_root / "worker-launches.log"
        self.handler_ledger = self.runtime_root / "handler-calls.log"
        self.ready_fifo = self.runtime_root / "ready.fifo"
        self.release_fifo = self.runtime_root / "release.fifo"
        self._ready_fd = -1
        self._release_fd = -1
        self._runtime_path = str(self.runtime_root.resolve())
        self.runtime: HookRuntime | None = None
        self.scope = None
        self.close_report = None
        self.observed_workers: tuple[tuple[int, str], ...] = ()
        self._dispatch_thread: threading.Thread | None = None
        self.dispatch_error: BaseException | None = None
        self.closed = False
        self.host_markers: list[str] = []
        self.old_report = None
        self.new_report = None
        self.unregister_result = None
        self.replacement_registration = None
        self.reload_result = None
        self.noop_reload_result = None
        self.rejected_reload_result = None
        try:
            self._initialize_reload_runtime()
        except BaseException as initialization_error:
            cleanup_error: BaseException | None = None
            try:
                self.close()
            except BaseException as exc:
                cleanup_error = exc
            if cleanup_error is None:
                raise
            if not isinstance(initialization_error, Exception):
                initialization_error.add_note(
                    f"cleanup also failed: {cleanup_error!r}"
                )
                raise initialization_error
            if not isinstance(cleanup_error, Exception):
                cleanup_error.add_note(
                    f"initialization also failed: {initialization_error!r}"
                )
                raise cleanup_error
            raise ExceptionGroup(
                "reload scenario initialization and cleanup failed",
                (initialization_error, cleanup_error),
            )

    def _initialize_reload_runtime(self) -> None:
        """Initialize owned synchronization, bindings, and the public Runtime."""
        self.runtime_root.mkdir()
        os.mkfifo(self.ready_fifo, 0o600)
        os.mkfifo(self.release_fifo, 0o600)
        self._ready_fd = os.open(self.ready_fifo, os.O_RDONLY | os.O_NONBLOCK)
        self._release_fd = os.open(self.release_fifo, os.O_RDWR | os.O_NONBLOCK)
        self._write_reload_worker_modules()
        sys.path.insert(0, self._runtime_path)
        limits = replace(
            HookLimits(),
            workers=1,
            queue_items=8,
            queue_bytes=65_536,
            handler_timeout_ms=5_000,
            dispatch_timeout_ms=5_000,
            shutdown_timeout_ms=2_000,
        )
        self.initial_settings = HookSettings(limits=limits)
        self.runtime = HookRuntime(
            self.initial_settings,
            temp_root=self._runtime_path,
        )
        self.scope = self.runtime.open_scope(metadata={"owner_id": "bdd-host"})
        self.definition = EventDefinition(
            _EVENT_NAME,
            1,
            {
                "type": "object",
                "properties": {
                    "ready_fifo": {"type": "string"},
                    "release_fifo": {"type": "string"},
                    "handler_ledger": {"type": "string"},
                    "stall": {"type": "boolean"},
                },
                "required": ["ready_fifo", "release_fifo", "handler_ledger", "stall"],
            },
        )
        self.blocker_registration = self._register(self._binding("blocker", 10))
        self.old_registration = self._register(self._binding("old-binding", 20))
        self.old_generation = self.old_registration.generation

    def _write_reload_worker_modules(self) -> None:
        """Write scenario-owned observers loaded by default isolated workers."""
        startup = f'''import os
from pathlib import Path

if os.environ.get("TOPSAILAI_HOOK_WORKER") == "1":
    fields = Path("/proc/self/stat").read_text(encoding="utf-8").split()
    descriptor = os.open({str(self.worker_ledger)!r}, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, f"{{os.getpid()}}:{{fields[21]}}\\n".encode("utf-8"))
    finally:
        os.close(descriptor)
'''
        handler = '''import os


def observe(context):
    descriptor = os.open(context.event.payload["handler_ledger"], os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o600)
    try:
        record = f"{context.binding_id},{context.registry_generation}\\n".encode("utf-8")
        os.write(descriptor, record)
    finally:
        os.close(descriptor)
    if context.binding_id == "blocker" and context.event.payload["stall"]:
        ready = os.open(context.event.payload["ready_fifo"], os.O_WRONLY)
        try:
            os.write(ready, b"1")
        finally:
            os.close(ready)
        release = os.open(context.event.payload["release_fifo"], os.O_RDONLY)
        try:
            os.read(release, 1)
        finally:
            os.close(release)
    return {"binding": context.binding_id, "generation": context.registry_generation}
'''
        (self.runtime_root / "sitecustomize.py").write_text(startup, encoding="utf-8")
        (self.runtime_root / "bdd_reload_worker.py").write_text(handler, encoding="utf-8")

    @staticmethod
    def _binding(binding_id: str, priority: int) -> Binding:
        """Build one binding for the reload behavior event."""
        return replace(
            Binding(binding_id, _EVENT_NAME, 1, _HANDLER_REF),
            priority=priority,
            timeout_ms=5_000,
        )

    def _register(self, binding: Binding):
        """Register through the public Runtime and require acceptance."""
        assert self.runtime is not None
        result = self.runtime.register(self.definition, binding, self.scope)
        if not result.accepted or result.handle is None:
            raise RuntimeError(f"BDD reload registration failed: {result.errors}")
        return result

    def _event(self, *, stall: bool, operation_id: str):
        """Create an event through the public immutable event boundary."""
        assert self.runtime is not None
        return self.runtime.make_event(
            self.scope,
            _EVENT_NAME,
            1,
            {
                "ready_fifo": str(self.ready_fifo),
                "release_fifo": str(self.release_fifo),
                "handler_ledger": str(self.handler_ledger),
                "stall": stall,
            },
            operation_id=operation_id,
            layer="bdd-host",
            purpose="reload-generation",
        )

    def run_reload_during_dispatch(self) -> None:
        """Mutate future state after one public dispatch has been admitted."""
        assert self.runtime is not None
        old_event = self._event(stall=True, operation_id="old-admission")

        def dispatch_old() -> None:
            try:
                self.old_report = self.runtime.dispatch(old_event)
            except BaseException as exc:
                self.dispatch_error = exc

        self.host_markers.append("host-before-reload")
        self._dispatch_thread = threading.Thread(
            target=dispatch_old,
            name="bdd-hook-reload-dispatch",
        )
        self._dispatch_thread.start()
        self._wait_ready()
        self.unregister_result = self.runtime.unregister(self.old_registration.handle)
        self.replacement_registration = self._register(
            self._binding("new-binding", 20)
        )
        changed_settings = replace(
            self.initial_settings,
            limits=replace(self.initial_settings.limits, dispatch_timeout_ms=4_000),
        )
        self.reload_result = self.runtime.reload(changed_settings)
        self.noop_reload_result = self.runtime.reload(changed_settings)
        invalid_settings = replace(
            changed_settings,
            limits=replace(changed_settings.limits, workers=0),
        )
        self.rejected_reload_result = self.runtime.reload(invalid_settings)
        self.host_markers.append("host-after-reload")
        self._release_worker()
        self._join_dispatch_thread()
        if self.dispatch_error is not None:
            raise self.dispatch_error

        self.host_markers.append("host-before-later-dispatch")
        self.new_report = self.runtime.dispatch(
            self._event(stall=False, operation_id="new-admission")
        )
        self.host_markers.append("host-after-later-dispatch")

    def assert_reload_and_snapshots(self) -> None:
        """Assert old admission coherence and latest-state future admission."""
        assert self.unregister_result is not None and self.unregister_result.accepted
        assert self.replacement_registration is not None
        assert self.reload_result is not None and self.reload_result.accepted
        assert self.noop_reload_result is not None and self.noop_reload_result.accepted
        assert self.rejected_reload_result is not None
        assert not self.rejected_reload_result.accepted
        latest_generation = self.reload_result.generation
        pre_reload_generation = self.replacement_registration.generation
        assert latest_generation == pre_reload_generation + 1
        assert self.noop_reload_result.generation == latest_generation
        assert self.rejected_reload_result.generation == latest_generation

        assert self.old_report is not None
        assert self.old_report.generation == self.old_generation
        assert tuple(item.binding_id for item in self.old_report.outcomes) == (
            "blocker",
            "old-binding",
        )
        assert all(item.status.value == "success" for item in self.old_report.outcomes)
        assert all(
            item.value["generation"] == self.old_generation
            for item in self.old_report.outcomes
        )

        assert self.new_report is not None
        assert self.new_report.generation == latest_generation
        assert tuple(item.binding_id for item in self.new_report.outcomes) == (
            "blocker",
            "new-binding",
        )
        assert all(item.status.value == "success" for item in self.new_report.outcomes)
        assert all(
            item.value["generation"] == latest_generation
            for item in self.new_report.outcomes
        )
        assert self._read_lines(self.handler_ledger) == [
            f"blocker,{self.old_generation}",
            f"old-binding,{self.old_generation}",
            f"blocker,{latest_generation}",
            f"new-binding,{latest_generation}",
        ]

    def assert_host_flow(self) -> None:
        """Assert reload and both dispatches leave host continuation intact."""
        assert self.host_markers == [
            "host-before-reload",
            "host-after-reload",
            "host-before-later-dispatch",
            "host-after-later-dispatch",
        ]

    def assert_closed(self) -> None:
        """Assert public closure and exact default-backend worker settlement."""
        super().assert_closed()
        assert len(self.observed_workers) == 4
        assert len(set(self.observed_workers)) == 4
