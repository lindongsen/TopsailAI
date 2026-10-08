"""Demonstrate structured hook failure isolation."""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings

from tests.demo.hooks.unified_hooks_demo_handlers import fail_intentionally, report_marker


FAIL_HANDLER = f"{fail_intentionally.__module__}:fail_intentionally"
SUCCESS_HANDLER = f"{report_marker.__module__}:report_marker"


def main() -> int:
    """Run the failure-isolation demonstration and return a process status."""
    temp_parent = PROJECT_ROOT / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    runtime_dir = tempfile.mkdtemp(prefix="unified-hooks-demo-failure-", dir=temp_parent)
    runtime = None
    scope = None
    cleanup_debts = None
    try:
        try:
            runtime = HookRuntime(
                HookSettings(limits=HookLimits(workers=2, queue_items=8, handler_timeout_ms=5_000, dispatch_timeout_ms=10_000)),
                temp_root=runtime_dir,
            )
            scope = runtime.open_scope(metadata={"owner_id": "demo-failure"})
            definition = EventDefinition("demo.failure", 1, {"type": "object", "properties": {"marker": {"type": "string"}}, "required": ["marker"]})
            for binding in (
                Binding("failing-hook", "demo.failure", 1, FAIL_HANDLER, priority=10),
                Binding("independent-hook", "demo.failure", 1, SUCCESS_HANDLER, priority=20),
            ):
                result = runtime.register(definition, binding, scope)
                if not result.accepted:
                    raise RuntimeError(f"registration failed: {result.errors}")
            event = runtime.make_event(
                scope,
                "demo.failure",
                1,
                {"marker": "independent work continued"},
                operation_id="demo-failure-operation",
                layer="demo",
                purpose="failure-isolation",
            )
            print("Host flow: before dispatch")
            report = runtime.dispatch(event)
            statuses = {outcome.binding_id: outcome.status.value for outcome in report.outcomes}
            values = {outcome.binding_id: outcome.value for outcome in report.outcomes}
            if statuses != {"failing-hook": "error", "independent-hook": "success"}:
                raise RuntimeError(f"unexpected failure-isolation result: {statuses}")
            if values["independent-hook"] != {"binding": "independent-hook", "marker": "independent work continued"}:
                raise RuntimeError("independent handler returned an unexpected value")
            print(f"Hook statuses: {statuses}")
            print("Host flow: after dispatch")
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
