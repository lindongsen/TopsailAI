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

This document distinguishes the authoritative target public contract from the currently implemented `topsailai.hooks` APIs. U06–U10 unified waiting execution, reload diagnostics, cancellation custody and Catalog authority are committed; U11A–E have focused business/process evidence. U11H final regression and architecture acceptance remain pending, with accepted provenance REDs recorded separately. The architecture and security rationale are maintained in [`features/feature-unified-hooks-design.md`](../features/feature-unified-hooks-design.md).

## Current direct-entry architecture

Since the 2026-10-16 migration, input and the eight phase-one Summary checkpoints call named point functions which delegate to `hooks.invoke_hook_point()`. Initialization and the cached `TOPSAILAI_HOOK_POINTS` snapshot belong to `hooks/__init__.py`, not a workspace application owner. `HooksApplication` and `SummaryHooksOwner` and their production builders have been removed; business factories no longer accept Hook Executor, preparation, trust or temp-root keywords.

An empty `{}` configuration still discovers bundled point-local resources. Each invocation merges these with configured absolute external Module/Script file or direct-child folder selections, rejects duplicate same-kind filenames, then executes Modules before Scripts, each in case-sensitive filename order. Membership is discovered again on later calls; this is not immutable prepared capture or last-known-good publication. Modules are imported and invoked **in the current process** and receive detached JSON keyword arguments; Summary uses the validated metadata-only `hook_context` envelope. Scripts are executable files launched directly as subprocesses with no arguments or Summary payload and empty stdin; stdout/stderr are discarded, while observed exit codes are reported. No deployment manifest, interpreter allowlist or dependency admission is required on this path.

Summary retains one scoped operation per actual summary, with checkpoint consumption before dispatch, nested-context restoration and thread/task ownership checks. Only before-generation, generation-error, after-application and application-error points run for each layer; the two after-generation candidates remain inactive. Human rejection, local empty results and feasibility skips do not imply application success. Required persistence, pairing and token updates retain their original order; observer failures do not replace business exceptions or trigger provider retries.

The direct entry returns the existing shared **`HookPointResult`** directly (not `DispatchReport`, an `EntryResult` tuple, or an owner startup/close report). The named input and Summary entries forward this object unchanged. `input_message()` intentionally ignores the observation and continues to return the user's input string; this change does not grant plugins authority to replace input or summary data.

### Direct-entry result format

| Field | Implemented direct-entry meaning |
|---|---|
| `execution_id`, `hook_point_name`, `plan_version` | One unique execution ID shared by the point and all nested handlers; exact point name; version `0` explicitly means no prepared/versioned plan. |
| `status` | `success` (including zero resources), `completed_with_errors` (settled errors or cleanup obstruction), `timeout` (deadline prevented completion), or `unavailable` (bootstrap, discovery or platform failure). |
| `handlers` | Tuple of Module `HandlerResult`s in filename order, followed by exactly one `default_script_hook` result named `hook_script`. Its `children` are Script results in filename order. This terminal is a report grouping over existing execution, not activation of the legacy Runtime/default-Hook scheduler. Unavailable points have no handlers. |
| Handler `handler` | `id`, exact filename `name`, and `kind`; resource IDs are `module:<filename>` / `script:<filename>`, with `hook_script` reserved for the terminal group. |
| Handler `status`, `not_run_reason` | `success`, `error`, `timeout`, or `not_run`; the terminal can also be `completed_with_errors`. Discovered successors after timeout/cleanup obstruction remain listed as `not_run` with reason `timeout` / `cleanup_failed`. |
| Handler `returned` | Modules preserve the exact normal/awaited result as `present=True, representation="direct", value=<object>, reference=None`. `None`, `False`, zero, empty values and error-shaped dictionaries are normal success. Exceptions and unrun resources have `present=False, representation="unavailable"`. Successful Scripts return process facts `{"exit_code": 0}`; failed Scripts have no normal return and observed nonzero exit codes appear in the safe error diagnostic. The terminal group has no synthetic normal return. |
| `timing` | Nonnegative integer `elapsed_ms` measured with a monotonic clock, including observed execution/cleanup; optional wall timestamps are `None`. Aggregate timing includes discovery; terminal timing covers the Script stage. No strict deadline guarantee is inferred. |
| `cleanup` | `safe` when no obstruction was observed; `pending` for unresolved/uncertain cleanup or blocked admission. This is an observation, not a recovery capability or an assertion that escaped descendants are absent. Unavailable reason is a bounded category in `cleanup.diagnostic` (`initialization_failed`, `discovery_failed`, `unsupported_platform`); it is not itself a cleanup failure. |
| Handler `error` | Safe `category`/`message` plus `exception`: the exact caught ordinary Python `Exception` instance for direct-entry Module import/execution and Script launch/wait failures (including `TimeoutExpired`). No exception is fabricated for a nonzero Script exit or missing callable `main`; their diagnostic has `exception=None`. Success has `error=None`. Host `KeyboardInterrupt`, `SystemExit` and `CancelledError` still propagate. |
| `decision` | Always `action="continue", authority=None`; normal values do not grant blocking or mutation authority. |

**Human revision — 2026-10-18:** direct-entry errors intentionally expose the original live exception as `result.handlers[i].error.exception`, not a copy, string or deserialized substitute. This overrides historical no-live-exception restrictions only for this in-process result. The exception retains its traceback, frames, locals and potentially sensitive data; callers own retention and must release the result/exception when no longer needed. It is not automatically serialized, detached or sanitized. Do not blindly log, deep-copy (`dataclasses.asdict`), JSON-encode or transmit the result; explicitly project safe fields at external boundaries. Default diagnostic repr/equality/hash exclude the live exception. Isolated legacy worker transport and Summary plugin payloads remain unchanged. Script child-language exception objects cannot cross a subprocess boundary.

Direct-entry resource failures also emit an ERROR log correlated by Hook Point name, `execution_id`, handler kind/name, status, start state and Script exit code. Actual caught exceptions include their type, message and traceback through standard logging `exc_info`; logging records carry a creation timestamp (rendering depends on the application formatter). Non-exception failures retain status/code context; missing callable `main` also has its existing explicit reason log. Existing low-level path/traceback records remain, so a failure can produce more than one record. Payloads, returned values and traceback frame locals are not collected. Exception messages and traceback source lines can themselves contain sensitive text: plugins must avoid embedding secrets and deployments must protect/redact diagnostic logs. This does not change host-interruption propagation or serialize the live result exception.

Business callers may use `result.status`, `result.handlers[0].returned.present` and `.value`, or inspect `result.handlers[-1].children` for Script observations. Do not infer success from truthiness of the returned value. These frozen dataclasses are **shallow**: opaque Module values are not copied, frozen, bounded or automatically serialized. Callers own retention, validation and any later serialization; avoid logging or blindly applying arbitrary returned objects. This is a deliberate in-process direct-entry exception to the retained isolated transport discussion below. There is no managed-reference support, plan snapshot/versioning, last-known-good publication, Script output capture, automatic result transformation or Catalog blocking on this path.

POSIX process cleanup retains exact recovery records for Script children only; unresolved cleanup blocks further plugin starts. In-process Modules create no process cleanup debt and cannot be preempted, so the aggregate deadline is checked only before invoking a Module. Host `KeyboardInterrupt`, `SystemExit` and cancellation propagate by identity rather than becoming returned reports. The five-second execution budget is not a strict whole-call bound (discovery, lock waiting and cleanup can add time). This is not a sandbox, side-effect rollback or cross-platform guarantee.

Shared Runtime/Scope/Registrar/Executor, prepared/trust/deployment APIs and `hooks/application_access.py` remain available as explicitly composed legacy libraries, unchanged by the owner deletion. They are not dependencies of the current input/Summary path and are not automatically bound by AgentChat or CLI startup. The legacy architecture and deployment sections below describe those libraries and historical evidence, not current business activation requirements.

## Retained prepared framework target and current gap

Each Hook Point has 0..N public Module Hooks and exactly one framework-owned built-in/default terminal `hook_script`. Each Module exposes `main(*args, **kwargs)`. Modules execute sequentially by ascending final registered Module name, then the default Hook identifies and executes Scripts sequentially by ascending final registered Script name. Keys use case-sensitive Unicode code-point order; no locale, natural sorting or normalization. Duplicate names within each handler kind are rejected atomically, so list positions and directory prefixes are not tie-breakers. See [the precise design contract](../features/feature-unified-hooks-design.md#deterministic-name-keys).

Scripts are internal entries, not public peer Hook registrations. `scripts`/`folder`, startup/lazy, decorators and function-level calls must configure/trigger that same unified plan. The default Hook exists even without Scripts, remains last, and waits for all Module predecessors to become terminal and cleanup-safe under the same aggregate deadline.

**Committed synchronous implementation:** U06A–U06D connect complete immutable plans to the unified executor. The configured adapter (`17d9e9ac`) calls `execute_hook_point`, not a direct Script-only execution with `module_bindings=()`. Ordinary target entry points (`14d61522`) are `HookRuntime.register_hook_point` and `HookRuntime.dispatch_hook_point`. The low-level generic Binding `register/dispatch` API remains legacy and does not imply the target default-Hook invariant.

U07 last-known-good/desired-active diagnostics (`33bafa42`), U08 awaited cancellation custody (`87e756d5`), U09 Catalog authority (`3168fecd`, `0f4c6f46`) and U10 nonwaiting removal (`035b270a`, `0b6dbc4b`) are implemented. U11A–E verify real target order/returns, reload, cancellation/deadline barriers, wrappers and configured startup process exit; the latest selected affected run is 480 passed. This is not unrestricted ALL GREEN or core-rollout approval: the [architecture issue](../issues/issue-hook-point-default-script-handler-architecture.md) stays open for U11H and the accepted provenance exception decision.

## Ordinary source registration and exact dispatch

`runtime.register_hook_point(hook_name, scope, modules=(), scripts=())` validates and detaches bounded `ModuleSource` descriptors and absolute Script paths into scope-local storage; it does not import plugins or capture executable content at registration. `runtime.dispatch_hook_point(hook_name, event, policy=None, *, cancellation=None)` selects sources by the exact scope/Hook name and requires deployment-owned configured trust. Scope close removes the descriptors. Generic `register/dispatch` retains its legacy semantics.

Ordinary dispatch establishes one absolute monotonic deadline at dispatch entry **before discovery, capture or preparation**. Preparation builds an immutable candidate, performs exact publication and acquires the published reader while replacement is excluded. The same deadline flows through admission, Modules, cleanup-safe predecessor barriers and the default Hook; no stage resets it. Descriptor registration is not an immutable capture: source changes before a later dispatch can change its newly prepared candidate, while an admitted plan remains immutable.

Execution-local custody binds cleanup responsibility to that exact reader/record. Debt queries and retry authority are exact-record scoped; foreign execution debt neither becomes the current execution's debt nor grants retry authority. Exceptions after allocation retain ownership until finalization or recoverable debt publication, rather than losing the resource on an exception exit.

## Committed execution result representation

`ReturnedValue` has `present`, `representation`, `value` and `reference`. Representation is `direct`, `transported`, `reference` or `unavailable`; this inventory is not a promise of managed-reference support. `None`, `False` and error-shaped dictionaries remain successful normal Module returns when transport supports them. Status and cleanup are independent of the business value.

A successful Script child returns process facts: `exit_code`, byte-valued `stdout`/`stderr`, and `stdout_dropped`/`stderr_dropped` flags. Do not interpret its protocol business value as the child's top-level return. The default parent's returned carrier retains `settlement.entry_results`, while ordered child results preserve individual status and cleanup. Empty Script sets still produce the single successful default terminal Hook.

## Target waiting-only execution and results

Only synchronous wait and async await are supported; both execute the same immutable unified plan under one absolute deadline, including registration/preparation. U10 removed `emit`, `emit_configured`, `aemit` and `DeliveryReceipt` as a breaking change, without aliases, observers or hidden background replacement. Catalog declarations accept only `sync` or `async` and reject background mode. Awaited host cancellation propagates genuine cancellation while exact cleanup custody remains recoverable; it is not a normal completion report.

Module main(*args, **kwargs) accepts uncertain arguments and returns arbitrary content without a required business schema or JSON serializability. The framework wraps the return, not the plugin. `False`, `None` and `{"error": 1}` are successful normal returns; returning None has returned.present=true, whereas exceptions/not-run have no normal return. Arbitrary arguments still require a safe isolated transport; unsupported transport is reported without unsafe coercion or host invocation.

Target HandlerResult fields: execution_id, hook_point_name, plan_version; handler {id, name, kind}; status and not_run_reason; returned {present, representation, value, reference}; safe error {category, message}; timing {started_at, finished_at, elapsed_ms}; cleanup {state, diagnostic}; decision {action, authority}; and ordered children for the default Script Hook. Status is success/error/timeout/cancelled/not_run, or completed_with_errors for the default Hook. Cleanup safe/pending/failed is independent of status. The default Hook with no Scripts succeeds with children=[].

HookPointResult holds correlation/version, ordered handlers, aggregate status (success/completed_with_errors/blocked/timeout/cancelled/unavailable), timing, cleanup and Catalog-authorized continue/block decision. Normal return data cannot grant blocking authority. The facade returns `DispatchReport` carrying `unified_result`, not a bare `HookPointResult`, and does not rewrite its decision. A Catalog-authorized `block` raises on rejection or unified non-success status; cleanup pending/failed alone on unified success does not block. A blocking before Hook prevents business entry; a blocking success Hook cannot roll back completed mutation; an error Hook preserves the original business exception identity and traceback.

Return representation is direct/transported/reference/unavailable. No promise is made that arbitrary objects can cross a process boundary unchanged. Transport must be safe and bounded, without untrusted pickle; direct is not permission for host-process plugin invocation. A reference requires a live managed isolated owner, bounded retention and explicit release/expiration/close cleanup; this support remains proposed. Otherwise mark untransportable content unavailable, preserve the normal execution status and report a safe diagnostic. See [the complete envelope](../features/feature-unified-hooks-design.md#unified-handler-and-hook-point-result-envelope).

## Target reload failure policy

Reject a failing new candidate and continue using the last known good active plan. Example: v1 is valid; desired v2 adds a Module without main. Reject/clean v2, retain v1 for new admissions, and explicitly report desired_revision=v2, active_revision=v1 and update_failed_using_last_known_good. Initial failure without a valid prior plan yields unavailable; business blocking follows Catalog policy, not an unconditional startup failure. Successful replacement is atomic, and in-flight calls retain their captured plan. U07 implements these desired/active diagnostics and failed-revision caching; U11B supplies real Registrar/Executor reload and first-failure-unavailable evidence. This selected evidence does not replace U11H final acceptance.

Script names have no format restriction. Ordering uses the exact final registered name string with case-sensitive Unicode ascending comparison; duplicates within the same kind/Hook Point reject the candidate. Root-relative directory names are a proposal awaiting confirmation, not a basename restriction.

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

            invalid_registration = runtime.register_configured(
                "hook_demo_missing_source",
                scope,
            )
            assert not invalid_registration.accepted
            assert invalid_registration.errors == ("invalid_script_source",)

            unknown = runtime.dispatch_configured("hook_unknown", sync_event)
            assert unknown.rejection_reason == "unknown_configured_hook"
```

`asyncio.run()` is used only because this example starts in synchronous code. An application already running an event loop should directly use `await runtime.adispatch_configured(...)` and must not call `dispatch_configured()` from that loop. There is no background admission API. Exiting the Scope and Runtime context managers closes ownership; inspect retained cleanup debts and use the public exact `retry_cleanup(debt_id)` when needed before asserting complete resource convergence.

## Non-empty script deployment prerequisite

A non-empty `scripts` or `folder` registration additionally requires deployment-provisioned `ConfiguredTrustPolicy` data for every admitted executable: authorized source roots, exact interpreters or native-script policy, and matching immutable `ArtifactClosureAssertion` records. Supplying only a source root is insufficient and fails closed during artifact capture.

The public `load_configured_trust_manifest()` in `hooks/configured_bootstrap.py` verifies a deployment-pinned manifest digest. The offline Module-only generator below does not generate Script authority; non-empty Script deployments must still provision complete assertions at their trusted deployment boundary. No application runtime hashes discovered files to authorize them; tests may construct exact assertions for their own fixtures. Once that policy has been supplied to `HookRuntime(configured_trust=...)`, use one of the registration forms below.

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
        *,
        deadline: float | None = None,
        cancellation: threading.Event | None = None,
    ) -> DispatchReport: ...

    async def adispatch_configured(
        self,
        hook_name: str,
        event: HookEvent,
        policy: Any = None,
        *,
        deadline: float | None = None,
        cancellation: threading.Event | None = None,
    ) -> DispatchReport: ...

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

## Current registration of script lists

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

**Committed behavior:** the list selects entries only; the default Hook sorts them by final registered name before execution, after Modules. Caller order does not control execution. Each entry must resolve to an admitted regular script file. Passing a string as the scripts container, a directory entry, an unsupported entry, an unsafe recognized candidate, or duplicate canonical files rejects the complete registration.

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

Folder discovery is recursive and never follows file or directory symbolic links. **Committed execution:** entries are sorted by final registered name, with duplicate registered names rejected, through the terminal default Hook after Modules. Discovery path ordering is not the execution authority. A root-relative discovery name is a proposed default, not Human-approved name generation; basename-only sorting is not required. Ordinary unsupported files are ignored. A recognized executable candidate that is malformed or unsafe rejects the complete registration.

Exactly one of `scripts` and `folder` is required. Supplying neither or both rejects before Runtime mutation.

## Execute synchronously

```python
report = runtime.dispatch_configured(
    "hook_pre_tool_call",
    event,
)
```

`hook_name` is the only configured-plan selector. Lookup is exact and case-sensitive. The canonical syntax is `^hook_[a-z][a-z0-9_]*$`, with a total length of 5 through 128 characters. Event names, filenames, binding IDs, handler references, aliases, prefixes, suffixes, trimming, and case folding are never fallback selectors.

Synchronous execution uses the existing scheduler, absolute deadline, process isolation, HookScript outcome policy, diagnostics, and cleanup rules. Scripts run sequentially in final registered-name order through the default terminal Hook after cleanup-safe Module predecessors. There is no automatic retry. A synchronous call from a running event loop retains the ordinary Runtime rejection behavior; use `adispatch_configured()` in asynchronous code.

## Execute asynchronously

```python
report = await runtime.adispatch_configured(
    "hook_pre_tool_call",
    event,
)
```

Current asynchronous execution admits the same immutable registered plan and returns the existing `DispatchReport`. It shares the Runtime cancellation, deadline, settlement, and cleanup behavior; it does not use a second executor or registry.

## Removed background admission

U10 removes ordinary/configured emission, facade `aemit`, `DeliveryReceipt` and completion observers. This is a breaking removal with no alias or polling substitute. Migrate callers to `dispatch`/`dispatch_configured` for synchronous wait or awaited `adispatch`/`adispatch_configured`; Catalog background declarations are rejected.

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

Duplicate canonical scripts and duplicate registered names reject the complete submitted plan. Partial registration is never visible.

## Ownership and cleanup

The Runtime owns captured artifacts and internal reader leases. Callers do not receive candidate, TTL, generation, publication, disposal, artifact-lease, or cleanup-debt authority.

Closing a scope stops new admissions, settles or cancels its queued/running work under existing policies, removes its configured plans, and retires artifacts after the last admitted reader releases them. Closing the Runtime applies the same lifecycle to all scopes. Repeated close remains idempotent.

## Existing explicit API compatibility

The explicit binding waiting APIs remain supported; U10 removed only their nonwaiting emission surface:

```python
runtime.register(definition, binding, scope)
runtime.unregister(handle)
runtime.dispatch(event, policy=None)
await runtime.adispatch(event, policy=None)
```

Generic explicit Bindings remain in the legacy `bindings` index; target complete Hook-point plans use exact publication through the configured plan index. Separate indexes do not imply a Script-only target executor: configured waiting and ordinary synchronous target paths execute the complete Module/default-Hook plan. Configured replacement does not invalidate unrelated explicit registration handles.

## Candidate API migration

The retained configured adapters execute the unified plan. U08 awaited lifecycle and U10 breaking nonwaiting removal are committed:

```text
register_configured(hook_name, scope, scripts=... or folder=...)
  -> dispatch_configured / awaited adispatch_configured
```

The former caller-managed `PreparedConfigured` and prepare/publish/dispose lifecycle is superseded and is not exported from the package root. A fail-closed `HookRuntime.prepare_configured()` compatibility boundary and candidate record implementations remain internal historical safety surfaces only; new callers must not depend on them.

## Intentional limits

- Configured scripts are not a security sandbox against code already admitted under the worker identity.
- Registration does not perform PATH lookup, shell expansion, shell command execution, or `/usr/bin/env` interpreter resolution.
- Background admission does not create an unbounded completion-history or Receipt wait API.
- Application-domain integrations and Agent-level convenience adapters are separate future work; no parallel `run_agent()` API is introduced.

## Framework-readiness convenience APIs

The waiting Runtime methods above and the convenience layer are exported from `topsailai.hooks`. U07–U10 implement desired/active diagnostics, awaited cancellation custody, Catalog authority and waiting-only migration. U11A–E provide selected real-process evidence; U11H and core-rollout approval remain separate gates.

The `ConfiguredHookExecutor` uses one shared Registrar for startup or lazy registration and exposes:

```python
executor.dispatch(POINT, payload=safe_payload)
await executor.adispatch(POINT, payload=safe_payload)
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

Use explicit function-body calls instead when timing belongs between statements, around branches or mutation, at precise before/success/error checkpoints, with waiting completion:

```python
async def run_task(task, executor):
    await executor.adispatch(TASK_BEFORE, payload=safe_task_input(task))
    try:
        result = await execute_task(task)
    except Exception as error:
        await executor.adispatch(TASK_ERROR, payload=safe_error(error))
        raise
    await executor.adispatch(TASK_SUCCESS, payload=safe_task_result(result))
    return result
```

Both styles use the same catalog declarations, event builder, Executor, Registrar, Runtime, Scope, trust authority, diagnostics, and cleanup. A decorator maps `before`, `success`, and `error` to separate stable declarations and emits exactly one of `success` or `error` after an entered callable. Each declaration defaults to exposing no business data to `payload_builder`: `argument_fields` explicitly allows named bound arguments, `result_fields` explicitly allows named keys from an exact built-in `dict` result on `success`, and `error_fields` may allow only the detached `type` and/or `message` tokens on `error`. Other result types expose no result fields, which avoids invoking custom mapping code while constructing the view. The error `type` token is the exception class name; the `message` token is present only when the base exception has exactly one exact-string argument, so extraction never invokes exception formatting or user code. Every allowed value is copied through bounded JSON validation before the builder runs; the builder never receives raw business objects, exception instances, or tracebacks. The legacy `sensitive_fields` tuple remains an additional argument denylist and cannot overlap `argument_fields`; configuration cannot expand any declaration allowlist. After an original callable exception, Hook processing always ends with a bare `raise` of that exact exception instance and traceback; even a security-critical error Hook cannot replace an active business exception. A blocking before Hook may prevent entry, while a blocking success Hook may fail after business work has completed and therefore requires explicit catalog approval. Decorators do not support generators or async generators initially. Core code will never load environment configuration or trust manifests.

The authoritative target, implementation gaps, lifecycle and repair roadmap are maintained in [`features/feature-unified-hooks-design.md`](../features/feature-unified-hooks-design.md#framework-readiness-extension-before-application-hook-point-rollout).


## Point-local summary Module deployment

**Historical prepared deployment only:** the production builder in `workspace/summary_hooks_owner.py` was removed by U3 (`b2fa2b3`). Current Summary uses the direct entry above. The following describes the previous prepared contract; tests explicitly assemble retained components in `tests/legacy_prepared_support.py`, not a supported production owner.

The former builder explicitly bound the eight phase-one declarations to their own `hooks/points/context/<phase>_<business_action>/modules/` directories. Catalog entries identify points, not Module members. The two `after_summary_generate_*` points remain inactive. That composition required explicit builder adoption and Executor injection; it is no longer the AgentChat integration.

For an already configured point, add or remove a compliant direct-child Module file, update deployment authorization, and restart the application. A compliant Module file is a `.py` file or a compiled extension module recognized by the platform `importlib.machinery.EXTENSION_SUFFIXES` (for example `.so` on Linux, `.pyd` on Windows), excluding `__init__.py`. No Module import table, membership list, Catalog entry, or shared invocation configuration needs editing. Summary Modules use `main(*, hook_context)` with detached metadata (`event_name`, `event_version`, `operation_id`, `payload`); the generic worker does not apply summary-specific payload validation. Discovery excludes `__init__.py` and does not recurse into nested Module directories. Name-ordered Modules run before the single default `hook_script`; removing the last member from a valid directory leaves a successful empty terminal. Missing directories and failed authorization are unavailable points, not empty successful plans.

### Offline authorization interface

`hooks/deployment_authorization.py::generate_module_trust_manifest(*, module_folders, source_roots, reviewed_deployment_sha256, python_runtime)` returns `(manifest_bytes, digest)` using the existing trust manifest v1 schema. Directory and source-root inputs are tuples of absolute canonical `Path` values. `python_runtime` is an explicitly supplied `ArtifactPythonRuntimeAuthority`; the reviewed deployment digest is a deployer-provided lowercase SHA-256 assertion, not an automatically reviewed dependency closure.

The explicit offline CLI is `python -m topsailai.hooks.deployment_authorization`. Its required options are:

| Option | Purpose |
|---|---|
| `--module-folder` | Repeat for each already configured point's Module directory, not each member file. |
| `--source-root` | Repeat for authorized canonical source roots. |
| `--reviewed-deployment-sha256` | Digest supplied by the trusted deployment review process. |
| `--python-executable` | Absolute canonical executable of the target runtime running the generator. |
| `--python-sha256` | Explicit reviewed content digest of that executable; mismatch is rejected, not corrected. |
| `--output` | Absolute new manifest path; existing files are never overwritten. |

The CLI prints the generated manifest SHA-256 on success. Publish the new manifest and its pin through the deployment boundary, load with `load_configured_trust_manifest(path, digest)`, and supply the resulting policy to explicitly composed retained preparation APIs. The generator does not import candidates, prove dependency review, invoke application startup, or run from Runtime. Run it on a frozen reviewed deployment tree under the final target Python runtime; runtime fingerprints include device/inode/platform facts and are not portable authority across machines.

This is a **Module-only** generator: it does not authorize or merge Script entries. For the separate mixed-authority interface, see [Point-local summary Script deployment](#point-local-summary-script-deployment). Do not replace a mixed Module/Script manifest without separately preserving its reviewed Script authority. Missing, malformed, mismatched or stale authority remains fail-closed; one invalid point is wholly unavailable rather than partially admitted. Already captured plans remain immutable until the old application lifetime closes; file changes alone do not hot-reload or authorize new code.

Focused acceptance uses generated pinned manifests, new application-owner lifetimes and real isolated workers for add/remove/empty-point behavior and sibling isolation. Direct dispatch of unavailable points has no outcomes or handler file side effects. This evidence is not a full application CLI restart, full-project, BDD, cross-platform or production-performance acceptance claim.

## Point-local summary Script deployment

**Historical prepared deployment only:** the former `build_summary_preparation_request(*, points_root=None, settings=None, disabled_hook_names=frozenset(), script_platform_policy=None)` was removed with the workspace owner. Its default was Module-only; the retained APIs below require explicit caller composition, not a deleted production builder. The former builder accepted a deployment-owned `ExecutablePlatformPolicy` for POSIX shebang-only Scripts and rejected native suffixes and non-POSIX policies. It selected the eight fixed `hooks/points/context/<phase>_<business_action>/scripts/` paths without per-file membership lists. The two phase-two declarations remain inactive; no placeholder Script resources were added by that prepared integration.

An absent optional directory selects no Script source. An existing empty directory retains the one successful zero-child `hook_script`; an explicitly configured missing/unreadable `ConfiguredScript.target` is unavailable, not empty success. Broken symlinks and access failures fail closed. Prepared discovery includes direct children only, skips ordinary subdirectories without traversal, and rejects symlinks, special/unreadable/nonexecutable/invalid files, duplicate names/identities and unauthorized members as a whole-point failure. Exact filenames including extensions determine case-sensitive Unicode ordering. Name-ordered Modules precede exactly one terminal `hook_script` containing individually named Script children; no peer Script bindings or separate dispatch chain exists. The generic recursive `ConfiguredHookBinding.folder` API is unchanged.

### Separate offline mixed authorization

The public functions in `hooks/deployment_script_authorization.py` are:

- `generate_mixed_trust_manifest(*, module_folders, scripts, source_roots, reviewed_deployment_sha256, python_runtime=None, interpreter_digests=(), policy=ConfiguredPreparationPolicy(), cancellation=None) -> (manifest_bytes, digest)`.
- `write_mixed_trust_manifest(output, **inputs) -> digest`, with an absolute new `Path` output opened exclusively; an existing manifest is never overwritten.

Supply tuples of canonical absolute Module-folder/source-root `Path` values and `ConfiguredScript` targets with explicit platform policies. Provide independently reviewed deployment closure authority, `ArtifactPythonRuntimeAuthority` when Modules exist, and `(Path, reviewed_digest)` interpreter tuples for shebang Scripts. The supported mixed path is POSIX shebang Scripts plus single-file Python source Modules; it does not authorize native implementation or widen platform support. Generation uses bounded shared discovery/read budgets and the existing v1 manifest schema without importing/executing candidates, generating authority at Runtime, merging ambient old manifests, or certifying dependency review. No mixed CLI is implied by the unchanged Module-only CLI.

Regenerate from the complete frozen, reviewed Module+Script inventory on the target deployment, write new authority exclusively, publish its pin, load through `load_configured_trust_manifest(path, digest)`, and supply the resulting `ConfiguredTrustPolicy` to explicitly composed retained preparation/registration APIs. Inspect their per-point startup dispositions. Membership changes require authorization regeneration and application restart; old admitted snapshots remain immutable, and stale/missing authority rejects the complete affected point without partial admission, implicit allowlisting or hot reload. Runtime/interpreter fingerprints are target-specific, not portable deployment certificates; retain permission and ancestry validation rather than repairing sources at Runtime.

[Summary Scripts acceptance](../features/feature-unified-hooks-design.md#summary-scripts-acceptance) records S1–S4 committed-tree integration/BDD/unit evidence and changed-scope coverage. Real empty-provider SSE retry exhaustion and the integration-only local empty-result skip are distinct. This evidence is not unrestricted full-project GREEN or deployment acceptance; existing cleanup/deadline/cancellation and deferred gates remain unchanged. S1–S4 introduced or changed no environment variables.
