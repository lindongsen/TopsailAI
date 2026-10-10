---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Hooks Python API

This document is the authoritative public Python API reference for the standalone `topsailai.hooks` Runtime, including simplified configured-script registration. The architecture and security rationale are maintained in [`features/feature-unified-hooks-design.md`](../features/feature-unified-hooks-design.md).

## Complete runnable lifecycle demo

The following example uses only symbols exported from `topsailai.hooks`. It registers a configured-empty plan, which exercises the complete public Runtime lifecycle without weakening the trust contract for executable files. An empty plan is useful for wiring and lifecycle checks: it is a known Hook that succeeds with no outcomes, unlike an unknown Hook, which is rejected.

```python
import asyncio
import tempfile
from pathlib import Path

from topsailai.hooks import ConfiguredTrustPolicy, HookRuntime, HookSettings


async def dispatch_async(runtime, scope):
    """Dispatch one configured event without blocking the active event loop."""
    event = runtime.make_event(
        scope,
        "demo.business-event",
        1,
        {"message": "async"},
        operation_id="demo-async",
        layer="demo",
        purpose="configured-hook-example",
    )
    report = await runtime.adispatch_configured("hook_demo", event)
    if report.rejection_reason is not None:
        raise RuntimeError(report.rejection_reason)
    return report


with tempfile.TemporaryDirectory() as temporary_directory:
    root = Path(temporary_directory).resolve()
    source_root = root / "configured-sources"
    runtime_root = root / "runtime"
    source_root.mkdir()
    runtime_root.mkdir()

    trust = ConfiguredTrustPolicy(source_roots=(source_root,))
    with HookRuntime(
        HookSettings(),
        temp_root=str(runtime_root),
        configured_trust=trust,
    ) as runtime:
        with runtime.open_scope(metadata={"owner_id": "demo-owner"}) as scope:
            registration = runtime.register_configured(
                "hook_demo",
                scope,
                scripts=[],
            )
            if not registration.accepted:
                raise RuntimeError(registration.errors)

            sync_event = runtime.make_event(
                scope,
                "demo.business-event",
                1,
                {"message": "sync"},
                operation_id="demo-sync",
                layer="demo",
                purpose="configured-hook-example",
            )
            sync_report = runtime.dispatch_configured("hook_demo", sync_event)
            assert sync_report.rejection_reason is None
            assert sync_report.outcomes == ()

            async_report = asyncio.run(dispatch_async(runtime, scope))
            assert async_report.outcomes == ()

            background_event = runtime.make_event(
                scope,
                "demo.business-event",
                1,
                {"message": "background"},
                operation_id="demo-background",
                layer="demo",
                purpose="configured-hook-example",
            )
            receipt = runtime.emit_configured("hook_demo", background_event)
            if not receipt.admitted:
                print(f"background work rejected: {receipt.rejection_reason}")

            invalid_registration = runtime.register_configured(
                "hook_demo_missing_source",
                scope,
            )
            assert not invalid_registration.accepted
            assert invalid_registration.errors == ("invalid_script_source",)

            unknown = runtime.dispatch_configured("hook_unknown", sync_event)
            assert unknown.rejection_reason == "unknown_configured_hook"
```

`asyncio.run()` is used only because this example starts in synchronous code. An application already running an event loop should directly use `await runtime.adispatch_configured(...)` and must not call `dispatch_configured()` from that loop. `emit_configured()` returns admission status only; there is intentionally no Receipt wait method. Exiting the Scope and Runtime context managers settles owned work and closes resources.

## Non-empty script deployment prerequisite

A non-empty `scripts` or `folder` registration additionally requires deployment-provisioned `ConfiguredTrustPolicy` data for every admitted executable: authorized source roots, exact interpreters or native-script policy, and matching immutable `ArtifactClosureAssertion` records. Supplying only a source root is insufficient and fails closed during artifact capture.

The package currently exposes the trust records but does not provide a public manifest builder or loader for ordinary callers. Therefore this document does not fabricate a helper that hashes and authorizes files at runtime. Production code should receive the complete policy from a trusted deployment/configuration boundary; tests may construct exact assertions for their own fixtures. Once that policy has been supplied to `HookRuntime(configured_trust=...)`, use one of the registration forms below.

## Existing real-worker demos

The maintained demos under [`tests/demo/hooks/`](../tests/demo/hooks/) exercise the public generic `HookRuntime` binding API with real isolated worker processes:

- `demo_basic_dispatch.py` demonstrates deterministic priority/dependency order and process isolation.
- `demo_failure_isolation.py` demonstrates structured handler failure while independent work succeeds.
- `demo_runtime_reload.py` demonstrates settings reload, binding replacement, registry generations, and rejection after Runtime close.
- `unified_hooks_demo_handlers.py` contains importable Python handlers used by those three demos.

These are runnable public-API demonstrations, but they use `EventDefinition`, `Binding`, and `runtime.register(...)`; they do not call `register_configured(...)`, discover script files, or construct configured-script trust assertions. They therefore demonstrate that the underlying Runtime executes real non-empty handlers, but they do not remove the configured-script deployment prerequisite above and are not a manifest builder or loader.

## Configured Runtime API

The implemented method signatures are:

```python
class HookRuntime:
    def register_configured(
        self,
        hook_name: str,
        scope: HookScope,
        *,
        scripts: Sequence[str | os.PathLike[str]] | None = None,
        folder: str | os.PathLike[str] | None = None,
    ) -> ConfiguredRegistrationResult: ...

    def dispatch_configured(
        self,
        hook_name: str,
        event: HookEvent,
        policy: Any = None,
    ) -> DispatchReport: ...

    async def adispatch_configured(
        self,
        hook_name: str,
        event: HookEvent,
        policy: Any = None,
    ) -> DispatchReport: ...

    def emit_configured(
        self,
        hook_name: str,
        event: HookEvent,
        policy: Any = None,
    ) -> DeliveryReceipt: ...
```

The registration result is exported from `topsailai.hooks`:

```python
@dataclass(frozen=True, slots=True)
class ConfiguredRegistrationResult:
    accepted: bool
    changed: bool = False
    script_count: int = 0
    errors: tuple[str, ...] = ()
```

`accepted=True, changed=False` means the submitted plan is identical to the active plan. `script_count` is the number of scripts in the submitted plan. `errors` contains stable safe categories on rejection.

A Runtime that admits non-empty configured plans must be constructed with a `ConfiguredTrustPolicy` authorizing the source roots, exact interpreters or native policy, and immutable artifact closure assertions. Registration fails closed when required trust authority is absent or invalid.

## Register ordered scripts

```python
result = runtime.register_configured(
    "hook_pre_tool_call",
    scope,
    scripts=[
        source_root / "01_validate.py",
        source_root / "02_add_context.py",
    ],
)
if not result.accepted:
    raise RuntimeError(result.errors)
```

The scripts execute in exactly the caller-provided order. Each entry must resolve to an admitted regular script file. Passing a string as the scripts container, a directory entry, an unsupported entry, an unsafe recognized candidate, or duplicate canonical files rejects the complete registration.

An empty `scripts=[]` is valid and registers a configured-empty plan. Executing that plan succeeds with zero script outcomes; this differs from an unknown Hook name, which is rejected.

## Register a folder

```python
result = runtime.register_configured(
    "hook_post_final_answer",
    scope,
    folder=source_root / "post_final_answer",
)
if not result.accepted:
    raise RuntimeError(result.errors)
```

Folder discovery is recursive and never follows file or directory symbolic links. Supported entries are sorted by normalized POSIX-style relative path using case-sensitive Unicode code-point ordering, so filesystem enumeration order is not observable. Ordinary unsupported files are ignored. A recognized executable candidate that is malformed or unsafe rejects the complete registration.

Exactly one of `scripts` and `folder` is required. Supplying neither or both rejects before Runtime mutation.

## Execute synchronously

```python
report = runtime.dispatch_configured(
    "hook_pre_tool_call",
    event,
)
```

`hook_name` is the only configured-plan selector. Lookup is exact and case-sensitive. The canonical syntax is `^hook_[a-z][a-z0-9_]*$`, with a total length of 5 through 128 characters. Event names, filenames, binding IDs, handler references, aliases, prefixes, suffixes, trimming, and case folding are never fallback selectors.

Synchronous execution uses the existing scheduler, absolute deadline, process isolation, HookScript outcome policy, diagnostics, and cleanup rules. Scripts run sequentially in registration order. There is no automatic retry. A synchronous call from a running event loop retains the ordinary Runtime rejection behavior; use `adispatch_configured()` in asynchronous code.

## Execute asynchronously

```python
report = await runtime.adispatch_configured(
    "hook_pre_tool_call",
    event,
)
```

Asynchronous execution admits the same immutable registered plan and returns the existing `DispatchReport`. It shares the Runtime cancellation, deadline, settlement, and cleanup behavior; it does not use a second executor or registry.

## Admit background execution

```python
receipt = runtime.emit_configured(
    "hook_post_final_answer",
    event,
)
if not receipt.admitted:
    handle_rejection(receipt.rejection_reason)
```

`DeliveryReceipt` reports admission only:

```python
@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    admitted: bool
    event_id: str
    rejection_reason: str | None = None
```

Admission does not imply successful script completion. No Receipt waiting method is provided. Completion failures use the existing bounded diagnostic path, and raw script output is not automatically logged.

## Scope selection

Registration requires the exact owning `HookScope`. Execution does not accept a second scope argument: it selects the plan using the immutable `HookEvent.scope_id` plus the exact `hook_name`.

This avoids contradictory scope inputs and avoids heuristic inference. A plan registered in one live scope incarnation is invisible to other scopes, even when they use the same Hook name. A foreign, closing, or closed event scope is rejected without launching scripts.

## Replacement and failure semantics

Registration prepares the complete plan before changing active state:

```text
discover and validate every entry
  -> capture immutable artifacts
  -> construct the complete ordered plan
  -> atomically publish the plan in the existing Registry state
  -> retire replaced resources after publication
```

For one `(scope incarnation, hook_name)`:

- the first successful registration publishes one complete plan;
- an identical registration is accepted as a no-op with `changed=False`;
- a changed successful registration atomically replaces the complete plan;
- discovery, validation, trust, capture, conflict, or capacity failure leaves the last successful plan executable;
- work admitted before replacement retains its old immutable plan until settlement;
- work admitted after replacement sees only the new plan.

Duplicate canonical scripts and duplicate basenames reject the complete submitted plan. Partial registration is never visible.

## Ownership and cleanup

The Runtime owns captured artifacts and internal reader leases. Callers do not receive candidate, TTL, generation, publication, disposal, artifact-lease, or cleanup-debt authority.

Closing a scope stops new admissions, settles or cancels its queued/running work under existing policies, removes its configured plans, and retires artifacts after the last admitted reader releases them. Closing the Runtime applies the same lifecycle to all scopes. Repeated close remains idempotent.

## Existing explicit API compatibility

The explicit binding API remains supported and unchanged:

```python
runtime.register(definition, binding, scope)
runtime.unregister(handle)
runtime.dispatch(event, policy=None)
await runtime.adispatch(event, policy=None)
runtime.emit(event, policy=None)
```

Explicit and configured plans share the same Runtime registry generation, scheduler, backend, limits, diagnostics, scope lifecycle, and close path. Configured replacement does not invalidate unrelated explicit registration handles.

## Candidate API migration

The supported configured workflow is:

```text
register_configured(hook_name, scope, scripts=... or folder=...)
  -> dispatch_configured / adispatch_configured / emit_configured
```

The former caller-managed `PreparedConfigured` and prepare/publish/dispose lifecycle is superseded and is not exported from the package root. A fail-closed `HookRuntime.prepare_configured()` compatibility boundary and candidate record implementations remain internal historical safety surfaces only; new callers must not depend on them.

## Intentional limits

- Configured scripts are not a security sandbox against code already admitted under the worker identity.
- Registration does not perform PATH lookup, shell expansion, shell command execution, or `/usr/bin/env` interpreter resolution.
- Background admission does not create an unbounded completion-history or Receipt wait API.
- Application-domain integrations and Agent-level convenience adapters are separate future work; no parallel `run_agent()` API is introduced.

## Framework-readiness convenience APIs

The Runtime methods above remain supported. The implemented convenience layer prepares the framework before Hook points are inserted into core flows while preserving every direct Runtime call above. It is exported from `topsailai.hooks`.

The `ConfiguredHookExecutor` uses one shared Registrar for startup or lazy registration and exposes:

```python
executor.dispatch(POINT, payload=safe_payload)
await executor.adispatch(POINT, payload=safe_payload)
receipt = await executor.aemit(POINT, payload=safe_payload)
```

One decorator may publish three distinct cataloged Hook points around an ordinary sync or async callable. `success` means success-only; it is never emitted when the callable raises:

```python
@hook_point(
    before=USER_LOOKUP_BEFORE,
    success=USER_LOOKUP_SUCCESS,
    error=USER_LOOKUP_ERROR,
    executor_attribute="hook_executor",
    payload_builder=build_user_lookup_payload,
)
async def lookup_user(self, user_id):
    return await self.repository.get(user_id)
```

Use explicit function-body calls instead when timing belongs between statements, around branches or mutation, at precise before/success/error checkpoints, or in background admission:

```python
async def run_task(task, executor):
    await executor.adispatch(TASK_BEFORE, payload=safe_task_input(task))
    try:
        result = await execute_task(task)
    except Exception as error:
        await executor.adispatch(TASK_ERROR, payload=safe_error(error))
        raise
    await executor.adispatch(TASK_SUCCESS, payload=safe_task_result(result))
    await executor.aemit(TASK_FINISHED, payload=safe_task_result(result))
    return result
```

Both styles use the same catalog declarations, event builder, Executor, Registrar, Runtime, Scope, trust authority, diagnostics, and cleanup. A decorator maps `before`, `success`, and `error` to separate stable declarations and emits exactly one of `success` or `error` after an entered callable. Each declaration defaults to exposing no business data to `payload_builder`: `argument_fields` explicitly allows named bound arguments, `result_fields` explicitly allows named keys from an exact built-in `dict` result on `success`, and `error_fields` may allow only the detached `type` and/or `message` tokens on `error`. Other result types expose no result fields, which avoids invoking custom mapping code while constructing the view. The error `type` token is the exception class name; the `message` token is present only when the base exception has exactly one exact-string argument, so extraction never invokes exception formatting or user code. Every allowed value is copied through bounded JSON validation before the builder runs; the builder never receives raw business objects, exception instances, or tracebacks. The legacy `sensitive_fields` tuple remains an additional argument denylist and cannot overlap `argument_fields`; configuration cannot expand any declaration allowlist. After an original callable exception, Hook processing always ends with a bare `raise` of that exact exception instance and traceback; even a security-critical error Hook cannot replace an active business exception. A blocking before Hook may prevent entry, while a blocking success Hook may fail after business work has completed and therefore requires explicit catalog approval. Decorators do not support generators or async generators initially. Core code will never load environment configuration or trust manifests.

The complete implemented contract, lifecycle, failure semantics, security boundary, readiness gate, and ordered implementation roadmap are maintained in [`features/feature-unified-hooks-design.md`](../features/feature-unified-hooks-design.md#framework-readiness-extension-before-application-hook-point-rollout).
