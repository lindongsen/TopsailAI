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
        "/project/hooks/01_validate.py",
        "/project/hooks/02_add_context.py",
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
    folder="/project/hooks/post_final_answer",
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
