"""Demonstrate settings reload and binding replacement for later dispatches."""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from topsailai.hooks import Binding, EventDefinition, HookLimits, HookRuntime, HookSettings

from tests.demo.hooks.unified_hooks_demo_handlers import report_marker


HANDLER = f"{report_marker.__module__}:report_marker"


def make_event(runtime: HookRuntime, scope, value: str):
    """Create one event carrying a visible generation-demo marker."""
    return runtime.make_event(
        scope,
        "demo.reload",
        1,
        {"marker": value},
        operation_id=f"demo-reload-{value}",
        layer="demo",
        purpose="runtime-reload",
    )


def main() -> int:
    """Run the reload demonstration and return a process status."""
    temp_parent = PROJECT_ROOT / ".tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    runtime_dir = tempfile.mkdtemp(prefix="unified-hooks-demo-reload-", dir=temp_parent)
    initial_settings = HookSettings(limits=HookLimits(workers=1, queue_items=8))
    runtime = None
    scope = None
    after_close_event = None
    cleanup_debts = None
    try:
        try:
            runtime = HookRuntime(initial_settings, temp_root=runtime_dir)
            scope = runtime.open_scope(metadata={"owner_id": "demo-reload"})
            definition = EventDefinition("demo.reload", 1, {"type": "object", "properties": {"marker": {"type": "string"}}, "required": ["marker"]})
            old = runtime.register(
                definition,
                Binding("old-observer", "demo.reload", 1, HANDLER),
                scope,
            )
            if not old.accepted:
                raise RuntimeError(f"registration failed: {old.errors}")
            first = runtime.dispatch(make_event(runtime, scope, "old"))
            changed = runtime.reload(
                replace(initial_settings, limits=replace(initial_settings.limits, handler_timeout_ms=900))
            )
            removed = runtime.unregister(old.handle)
            new = runtime.register(
                definition,
                Binding("new-observer", "demo.reload", 1, HANDLER),
                scope,
            )
            if not (changed.accepted and removed.accepted and new.accepted):
                raise RuntimeError("reload or binding replacement failed")
            second = runtime.dispatch(make_event(runtime, scope, "new"))
            after_close_event = make_event(runtime, scope, "after-close")
            if len(first.outcomes) != 1 or first.outcomes[0].status.value != "success":
                raise RuntimeError("initial dispatch did not succeed")
            if first.outcomes[0].value != {"binding": "old-observer", "marker": "old"}:
                raise RuntimeError("initial dispatch returned an unexpected marker")
            if len(second.outcomes) != 1 or second.outcomes[0].status.value != "success":
                raise RuntimeError("later dispatch did not succeed")
            if second.outcomes[0].value != {"binding": "new-observer", "marker": "new"}:
                raise RuntimeError("later dispatch returned an unexpected marker")
            if first.outcomes[0].binding_id != "old-observer" or second.outcomes[0].binding_id != "new-observer":
                raise RuntimeError("old and new dispatch reports were not isolated")
            if second.generation <= first.generation:
                raise RuntimeError("reload did not advance generation")
            print(f"Initial dispatch: generation={first.generation}, bindings={[item.binding_id for item in first.outcomes]}")
            print(f"Reload accepted: {changed.accepted}, generation={changed.generation}")
            print(f"Later dispatch: generation={second.generation}, bindings={[item.binding_id for item in second.outcomes]}")
            return 0
        finally:
            primary_error = sys.exc_info()[0] is not None
            if runtime is not None:
                close_report = runtime.close()
                cleanup_debts = close_report.cleanup_debts
                if not primary_error and after_close_event is not None:
                    rejected = runtime.dispatch(after_close_event)
                    if rejected.rejection_reason != "closed":
                        raise RuntimeError(f"dispatch after close was not rejected as closed: {rejected.rejection_reason}")
                    print(f"Dispatch after close: {rejected.rejection_reason}")
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
