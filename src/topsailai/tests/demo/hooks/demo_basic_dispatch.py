"""Demonstrate isolated workers and deterministic hook dispatch order."""

from __future__ import annotations

from collections.abc import Mapping
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings

from tests.demo.hooks.unified_hooks_demo_handlers import report_worker


HANDLER = f"{report_worker.__module__}:report_worker"


def main() -> int:
    """Run the basic dispatch demonstration and return a process status."""
    temp_parent = PROJECT_ROOT / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    runtime_dir = tempfile.mkdtemp(prefix="unified-hooks-demo-basic-", dir=temp_parent)
    runtime = None
    scope = None
    cleanup_debts = None
    try:
        try:
            runtime = HookRuntime(
                HookSettings(limits=HookLimits(workers=2, queue_items=8, handler_timeout_ms=2_000, dispatch_timeout_ms=5_000)),
                temp_root=runtime_dir,
            )
            scope = runtime.open_scope(metadata={"owner_id": "demo-basic"})
            definition = EventDefinition("demo.basic", 1, {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]})
            bindings = (
                Binding("prepare", "demo.basic", 1, HANDLER, priority=10),
                Binding("observe", "demo.basic", 1, HANDLER, priority=20, after=("prepare",)),
                Binding("finish", "demo.basic", 1, HANDLER, priority=30, after=("observe",)),
            )
            for binding in bindings:
                result = runtime.register(definition, binding, scope)
                if not result.accepted:
                    raise RuntimeError(f"registration failed: {result.errors}")
            event = runtime.make_event(
                scope,
                "demo.basic",
                1,
                {"message": "hello from the host"},
                operation_id="demo-basic-operation",
                layer="demo",
                purpose="basic-dispatch",
            )
            report = runtime.dispatch(event)
            order = [outcome.binding_id for outcome in report.outcomes]
            statuses = [outcome.status.value for outcome in report.outcomes]
            if statuses != ["success", "success", "success"]:
                raise RuntimeError(f"unexpected basic statuses: {statuses}")
            worker_pids = []
            for outcome in report.outcomes:
                if not isinstance(outcome.value, Mapping) or not isinstance(outcome.value.get("worker_pid"), int):
                    raise RuntimeError("basic handler returned a non-JSON worker result")
                worker_pids.append(outcome.value["worker_pid"])
            print(f"Host PID: {os.getpid()}")
            print(f"Dispatch generation: {report.generation}")
            print(f"Execution order: {' -> '.join(order)}")
            print(f"Statuses: {statuses}")
            print(f"Worker PIDs: {worker_pids}")
            if order != ["prepare", "observe", "finish"] or any(pid == os.getpid() for pid in worker_pids):
                raise RuntimeError("basic dispatch did not demonstrate the expected isolation")
            return 0
        finally:
            if runtime is not None:
                close_report = runtime.close()
                cleanup_debts = close_report.cleanup_debts
                print(f"Runtime closed: {scope is None or scope.closed}")
                print(f"Cleanup debts: {len(cleanup_debts)}")
            if cleanup_debts:
                print("Demo failed: runtime cleanup debt remains")
                raise RuntimeError("runtime cleanup debt remains")
    finally:
        try:
            shutil.rmtree(runtime_dir)
        finally:
            print(f"Deleted demo temporary directory: {runtime_dir}")
            print(f"Demo temporary directory removed: {not Path(runtime_dir).exists()}")


if __name__ == "__main__":
    raise SystemExit(main())
