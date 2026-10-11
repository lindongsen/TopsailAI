---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: framework-readiness APIs implemented; final acceptance pending; application Hook-point rollout deferred
scope: standalone framework, configured bootstrap/registration wrappers, Catalog, Executor, and decorator APIs implemented; application-domain integrations remain deferred
---

# Standalone Unified Hook Framework

## Status and scope

This document defines the authoritative target architecture clarified by the Human on 2026-10-10. Implementation evidence is recorded separately and does not override the target. U06A–U06D unified synchronous execution is committed, including configured adapter `17d9e9ac` and ordinary public entry `14d61522`. [The open architecture issue](../issues/issue-hook-point-default-script-handler-architecture.md) now tracks remaining U07–U11 lifecycle/migration acceptance; application-domain integrations remain deferred.

| Dimension | Current status |
|---|---|
| Implementation | U06A–U06D complete unified synchronous Module/default-Hook execution, configured adaptation, ordinary source registration and execution-local custody; U07–U11 remain pending. |
| Verification | U06D final affected verification: 208 passed with changed line/branch coverage 100%; two accepted provenance REDs remain separate known results. This is not full lifecycle or full-project GREEN acceptance. |
| Integration | The configured API is available at `HookRuntime`; conversation, Agent, LLM, tool, memory, and skill lifecycle integrations remain deferred. |

In scope now: the independent framework, its execution guarantees, interfaces, configuration, lifecycle, extension seams, current implementation status, and verification plan. Possible future integration families are conversation, User2Agent turns, Agent2LLM runs, LLM requests, prompt assembly, context summarization, persistence checkpoints, and task lifecycle.

Explicitly out of scope for the current implementation: all tool-specific hooks under tools/, tool invocation and approval integrations, memory hooks, skill hooks, compatibility adapters, migration of existing TOPSAILAI_HOOK_* implementations, and insertion of Hook points into application owners. Existing mechanisms remain untouched. The implemented foundation introduces no environment variable. The framework-readiness extension below implements environment-driven bootstrap and insertion APIs; its variables are synchronized to `env_template` and `docs/Environment_Variables.md`.

## Authoritative Hook Point contract

The Human clarified: “准确地说，是每个hook点都会有一个内置/默认的hook去识别脚本和执行脚本”. The latest ordering and entry requirement is: “排序方面：优先执行 modules,再执行scripts，执行顺序都是按名字排序。 执行modules的方式是每个module都会有一个main(*args, **kwargs)函数，它是执行入口。” These are Human statements; the normalized keys below are the documented deterministic interpretation, not additional verbatim quotes.

A **Hook Point** is a named extension location. A **Module Hook** is a plugin registered at that location. Each Hook Point has **0..N Module Hooks plus exactly one framework-owned built-in/default terminal Script Hook**, reserved as `hook_script`. This is one unified framework and one Hook-point execution plan, not two peer registration/dispatch models.

- Public plugin registration supports Modules only. Every Module exposes callable `main(*args, **kwargs)` as its execution entry. The framework binds detached, validated arguments through its isolated worker protocol; internal context/envelope adapters do not replace `main` with a required public `handle(context)` entry.
- Framework initialization of a Hook Point automatically supplies its one default `hook_script`, even with zero Modules or zero Scripts. It cannot be replaced, renamed, duplicated, removed, or reordered by plugins; it consumes one real binding-capacity slot. No Scripts means a successful zero-entry no-op, not absence of the default Hook.
- Modules execute sequentially in ascending module-name order. After all predecessors reach the required terminal and cleanup-safe state, the default Hook identifies the point's configured Scripts and executes them sequentially in ascending script-name order. Settled Module failure does not itself prevent Scripts; unresolved cleanup, host cancellation, or exhausted aggregate deadline does prevent unsafe continuation.
- Script files are internal entries of this default Hook, not peer Hooks, one Binding per script, or an independently dispatchable scripts-only plan. A result merely labelled `binding_id="hook_script"` does not satisfy the contract unless the default Hook is actually in the unified plan.
- `hook_name` plus `scripts` or `folder` configures the default Hook. Explicit lists select members, not execution order. Startup/lazy registration, decorators, and function-body calls are convenience wrappers and must preserve the same unified plan and lifecycle.

### Deterministic name keys

Sorting is case-sensitive ascending Unicode code-point order, without locale collation, case folding, numeric/natural sorting, or Unicode normalization. Both Module and Script keys are their final registered name strings, not binding priorities or list positions. Duplicate registered names within the same handler kind and Hook Point reject the complete candidate before publication. Module discovery can derive a logical import name using the complete interpreter-recognized suffix, but the final registered name is the ordering authority.

Script names have no framework-imposed format restriction: no required prefix, extension or basename-only rule. Executability, trust and path admission are separate safety checks, not naming restrictions. No case folding or name normalization changes the sorting key. Explicit lists select entries only; neither list position nor path is a tie-break for duplicate registered names. For directory discovery, generating a normalized root-relative path as the registered name is a proposed default to distinguish files in different subdirectories; the Human has not explicitly approved that generation rule. Display the generated names before publication rather than silently treating basename as authority.

Configured preparation discovers, captures and validates executable sources for publication. Ordinary U06D registration retains source descriptors; dispatch prepares a fresh captured candidate under its shared deadline. Execution consumes an immutable admitted snapshot: later source changes cannot alter that snapshot, but can affect a subsequent ordinary dispatch or configured reload.

```text
Hook Point trigger
  -> establish absolute deadline before discovery/capture/preparation
  -> capture and publish one unified plan
  -> module:Alpha.main(*args, **kwargs)
  -> module:beta.main(*args, **kwargs)
  -> required predecessor terminal/cleanup-safe barrier
  -> framework-owned default hook_script
       -> identify admitted Script entries
       -> a.py -> z.py (name order)
  -> one ordered report and owned cleanup
```

### Committed U06 implementation and remaining gates

U06A–U06D wire synchronous execution to `execute_hook_point`: name-ordered Modules, cleanup-safe predecessor barriers and exactly one default terminal Hook, including an empty successful terminal. Configured execution is a compatibility adapter (`17d9e9ac`), not a direct scripts-only bypass. Ordinary `register_hook_point`/`dispatch_hook_point` (`14d61522`) store scope-local source descriptors, prepare/capture under one pre-preparation absolute deadline, publish exactly and acquire the corresponding reader before replacement can occur. Generic Binding `register/dispatch` remains explicitly legacy.

Execution-local custody retains exact-reader ownership, exact-record debt query/retry authority, foreign-debt isolation and exception finalization responsibility. The [API](../docs/Hooks_API.md) documents the committed return carrier separately from target extensions. Final U06D affected tests are 208 passed; changed lines and branches are 100% covered. Two accepted provenance REDs remain unchanged; this does not establish full-project GREEN.

Remaining gates: U07 last-known-good/desired-active diagnostics; U08 async cancellation and cleanup; U09 Catalog-authorized decisions; U10 nonwaiting API removal; U11 BDD/integration/documentation acceptance. No core Hook-point rollout is approved by synchronous completion alone.

## Architectural decision

Build a generic package named hooks/ with one event model, one handler signature, one registry, one scheduler, one worker protocol, and one outcome model. Do not put observer/transformer classes, a hook-kind switch, or separate functional dispatchers into the core.

The core answers: which handlers match an event, in what order, within what resource budget, and what happened? The domain answers: when to publish, what payload is meaningful, and whether any returned value may affect its own data.

Execution policy is orthogonal to business function. Any binding can use the same protocol whether a caller ignores its value, collects results, or asks a domain extension to reduce results. Waiting versus enqueueing is a caller API choice, not a hook category.

Required application steps are not hooks. Authentication, authorization, context limits, request validation, persistence, locks, retry decisions, and cleanup remain authoritative business operations. Optional plugins cannot veto them or replace them merely by raising an exception.

## Guarantees and limits

| Property | Contract |
|---|---|
| Exception isolation | Plugin import errors, ordinary exceptions, plugin-originated control-flow exceptions, invalid output, worker crash, and protocol failure become structured outcomes, not host exceptions. |
| Timeout isolation | Queue wait, worker startup/import, execution, and output validation consume finite deadlines. Expiry abandons the result and schedules bounded worker termination. |
| Main-flow continuity | Failed hooks never change an otherwise valid application result into failure, cause provider retries, or prevent required cleanup. Overload rejects optional work rather than waiting for capacity. |
| Latency | Target dispatch waits for completion within one aggregate deadline; adispatch awaits the same execution without blocking the host loop. Fire-and-observe is excluded. |
| Delivery | Best effort, at most one execution attempt per admitted delivery, no automatic retries, no durable or exactly-once guarantee. |
| Isolation boundary | Plugins are imported and executed only in managed child processes. There is no arbitrary in-process plugin execution mode in the initial framework. |
| Limits | Process isolation is not a security sandbox or a real-time OS guarantee. OS failure, host termination, starvation, and machine-wide resource exhaustion cannot be fully masked. External side effects cannot be rolled back. |

A thread timeout or asyncio cancellation alone does not meet the guarantee: blocked code can continue executing. Strict execution requires an independently terminable worker. If a supported backend cannot safely launch and own workers, disable delivery and preserve the business flow; do not fall back to inline callbacks.

## Package and dependencies

The table distinguishes implemented modules from deferred structure.

| Module | Responsibility |
|---|---|
| hooks/contracts.py | Implemented typed event, binding, context, outcome, receipt, policy, reload, and close records |
| hooks/validation.py | Implemented bounded schema and JSON-value validation |
| hooks/registry.py | Implemented definition validation, dependency graph, and immutable registry snapshots |
| hooks/configuration.py | Implemented decoding of provided runtime settings; no deep environment reads |
| hooks/runtime.py | Implemented public lifecycle, emission, event construction, and operational reload facade |
| hooks/dispatcher.py | Implemented admission, event selection, deadlines, and stable report assembly |
| hooks/scheduler.py | Implemented bounded queues, dependency readiness, and concurrency limits |
| hooks/worker_protocol.py | Implemented bounded JSON transport and request/result validation |
| hooks/worker.py | Implemented isolated target import and sync/async handler invocation |
| hooks/process_backend.py and process state/cleanup modules | Implemented worker supervision, cancellation, and cleanup-debt ownership |
| hooks/diagnostics.py | Implemented injected non-recursive, bounded diagnostics |
| hooks/hook_script.py and HookScript discovery/planning modules | Implemented static discovery, planning, settlement, and runner-driven orchestration |
| hooks/module_discovery.py and hooks/module_discovery_worker.py | Implemented direct-child discovery and isolated import/callable-main validation |
| hooks/extensions/ | Deferred optional orchestration helpers; this directory does not currently exist |

The core depends on portable infrastructure, not ai_base, workspace, tools, skill_hub, memory, or application events. The application may inject an adapter for its event recorder. Domain schemas and reducers belong with the owning domain. Do not turn AgentRuntime into a general service locator: inject HookRuntime explicitly into owners that need it.

## Core abstractions

Use typed records internally; mappings are limited to JSON boundary encoding and explicitly schema-governed payloads.

| Abstraction | Required fields and meaning |
|---|---|
| EventDefinition | name, major_version, payload_schema, payload_limit_bytes; immutable declaration of a publishable contract |
| HookEvent | event_id, name, major_version, owner_id, scope_id, operation_id, parent_operation_id, sequence, timestamp, layer, purpose, payload |
| Binding | binding_id, exact event name/version, handler_ref, priority, after, requires_success, timeout_ms, max_concurrency, enabled, allowed_payload_fields |
| HookContext | Event snapshot plus delivery_id, binding_id, registry_generation, remaining_budget_ms, origin and depth; no live host object |
| HookOutcome | delivery_id, binding_id, status, optional JSON value, duration_ms, safe error category, started flag |
| DispatchReport | event_id, generation, ordered outcomes, elapsed_ms, deadline_exhausted; not a business result |
| DeliveryReceipt | admitted flag, event_id and rejection reason; admission is not successful execution |
| HookScope | Owner-linked registration handles and pending delivery ownership; closing is idempotent |
| HookRuntime | Registry, bounded scheduler, supervisor and diagnostic lifecycle; explicitly owned and closable |
| ReloadResult | Accepted/no-op/rejected operational settings reload result and generation metadata |
| CloseReport | Idempotent runtime-close result, including pending cleanup debt |

Event identity and subscription identity differ. Event name describes a stable boundary, binding_id identifies one registration, event_id identifies one occurrence, and delivery_id identifies one binding's attempt for that occurrence. Reusing a handler for different events does not deduplicate subscriptions. Duplicate binding IDs within a scope are rejected, never silently overwritten.

Names use dot-separated namespaces such as conversation.started and context.summary.finished. Schema major version is a separate integer; incompatible changes require a new major version. Initial matching is exact name plus major version, without wildcards or arbitrary filter callbacks. Category labels may be metadata but never choose a different execution engine.

Sequence is monotonically increasing per scope under the owner lock; it records publication order, not completion order. IDs are correlation data, not credentials or authorization. Payload schema definitions are bounded declarative schemas, not custom application callbacks invoked during core validation.

## Unified handler and public interfaces

The Runtime methods below exist; the Module entry shown is the required target, not a claim that current Binding validation enforces it. This compact sketch is not an exact call signature reference. `HookScheduler` is implemented as a module-level API and is not currently a package-level export.

```text
main(*args, **kwargs) -> Any  # Public Module entry; no business-schema restriction

runtime.register(definition, binding, scope) -> RegistrationResult
runtime.unregister(handle) -> RegistrationResult
runtime.dispatch(event, policy) -> DispatchReport
await runtime.adispatch(event, policy) -> DispatchReport
runtime.open_scope(parent, metadata) -> HookScope
runtime.reload(settings) -> ReloadResult
runtime.make_event(...) -> HookEvent
runtime.close(deadline) -> CloseReport

settle_configured_empty_hook_script(...) -> HookScriptSettlement
execute_configured_hook_script(..., runner: HookScriptRunner, ...) -> HookScriptSettlement
```

The standalone HookScript orchestration interfaces `HookScriptExecutionOptions`, `HookScriptExecutionPolicy`, `HookScriptEntryResult`, `HookScriptRunner`, and `execute_configured_hook_script` are implemented. `HookScriptRunner` is an injected trusted runner protocol. The simplified configured Runtime facade is also implemented through `register_configured()`, `dispatch_configured()`, `adispatch_configured()`, and `emit_configured()`; application-domain lifecycle integrations remain deferred.

Every public Module uses `main(*args, **kwargs)` with arbitrary arguments and arbitrary return content; the framework, not the Module, constructs the result envelope. The existing low-level worker context convention requires an adapter where necessary; it is not permission for an arbitrary public callable entry. `None`, `False`, zero, empty containers and `{"error": 1}` are normal return values, not framework errors. Values are not required to be JSON-serializable. The framework does not interpret any of them as a veto, replacement, success marker, or request to retry. Execution success is represented by outcome.status, independently of outcome.value.

Host-side admission, serialization, configuration, queue, and backend errors return diagnostic statuses. Programmer-facing registration can expose detailed validation errors through RegistrationResult without raising through normal runtime emission. Genuine host cancellation and interrupts remain host control flow, not successful empty reports.

Implemented `HookStatus` values include: success, error, timeout, invalid_output, worker_lost, cancelled, skipped_dependency, skipped_disabled, skipped_deadline, rejected_capacity. A rejected event yields an explicit receipt/report reason rather than pretending that no handlers matched. No matching bindings yields a successful empty dispatch.

Reports and diagnostics remain bounded. Dispatch owns its short-lived report. Non-waiting admission, background handles and result polling are not part of the target API; existing emit APIs are implementation-only migration gaps.

## Registration, discovery and configuration

Use an explicit manifest or typed API registration. Target Module handler references identify importable `module:main` entries; the explicitly legacy generic Binding API still accepts arbitrary `module:callable` references and is not the ordinary target registration contract. Closures, live instances, lambdas, and implicitly inherited thread-local agents are not supported. Configuration parsing must not import plugin modules.

The application reads a chosen config source once and passes settings to HookRuntime. `HookSettings.from_mapping()` accepts runtime settings (`schema_version`, `enabled`, and `limits`); definitions and bindings are registered through the typed API rather than embedded in that mapping. No new environment-variable family is prescribed. Configured module/script discovery is explicit and rooted at caller-supplied paths; there is no implicit crawling of the working directory, installed packages, or arbitrary search paths.

Illustrative configuration:

```json
{
  "schema_version": 1,
  "enabled": true,
  "limits": {
    "workers": 4,
    "queue_items": 256,
    "queue_bytes": 4194304,
    "event_bytes": 65536,
    "bindings_per_event": 32,
    "handler_timeout_ms": 1000,
    "dispatch_timeout_ms": 1000,
    "shutdown_timeout_ms": 1000
  }
}
```

These values match current finite code defaults, but they are not measured or approved production-performance budgets. Reject non-finite/negative durations, excessive graph sizes, unknown fields, incompatible versions, and undefined events. Enforce global hard caps above per-binding settings. Hook runtime disabled is a cheap no-op with no workers.

The U07 target validates a configuration candidate as a whole. Initial invalid configuration leaves the affected Hook Point unavailable with diagnostics; business blocking follows only Catalog-authorized policy. Invalid reload rejects the new revision and retains the last known good active plan for new admissions, explicitly reporting desired_revision, active_revision, update_failed and safe diagnostics. A successful reload atomically publishes an immutable new generation. An in-flight dispatch retains its captured generation. Explicit unregister affects new admissions only; scope close also cancels outstanding deliveries.

## Ordering, dependencies and concurrency

For matching bindings, resolve a directed acyclic graph. after specifies completion-before-start, regardless of predecessor success. requires_success additionally skips the dependent if the predecessor did not succeed; it implies an ordering edge. Targets must exist within the same event/version and effective scope snapshot. Cross-event dependencies and hidden lookups into previous reports are unsupported.

Reject cycles and unknown references before activation. The required Hook-point plan compiles Modules into a strict logical-name chain and appends the default `hook_script` after every Module; priority, caller dependencies, and registration order cannot override that order. The current generic Registry selects ready nodes by ascending priority then binding ID; this is an internal low-level behavior, not the target public Hook-point ordering contract.

Within a Hook Point, Modules and Script entries are sequential and name-ordered; parallel execution within either stage is not part of this contract. Separate deliveries may use bounded Runtime concurrency without changing the order inside a captured plan. Reports are always ordered by the stable topological plan, not completion timing. A failing independent handler never suppresses later independent handlers. Dependency skips and deadline exhaustion are intentional exceptions to execution, not propagation of a plugin error.

Per-binding max_concurrency defaults to one across an owning runtime. Ready deliveries for that binding use admission order. Cross-binding completion order and cross-process global ordering are not guaranteed. No dispatch holds a registry or application lock while waiting for a handler. Registration changes inside application code affect only future snapshots; workers do not receive registration authority.

Worker parallelism is bounded at runtime level, not multiplied without limit per scope. Sequential dispatch does not imply a stateful plugin singleton: initial workers use one delivery per process, preventing module globals leaking across calls. Worker reuse is a later optimization requiring an explicit reset/isolation contract and evidence; it must not silently weaken the initial guarantee.

## Dispatch algorithm and deadlines

The target requires dispatch and awaited adispatch to use this unified algorithm and logically wait for completion. Configured synchronous execution is connected in U06; async lifecycle migration and non-waiting emit removal remain U08/U10 gates. Fire-and-observe is outside the target.

```text
record absolute monotonic deadline at dispatch entry before discovery/capture/preparation
capture and publish the complete immutable plan; acquire its exact reader
validate and freeze bounded event snapshot
try admission without waiting for queue space
schedule ready graph nodes while deadline and capacity allow
for each node:
    send detached payload to owned worker
    import Module and invoke main(*args, **kwargs) through the worker adapter
    accept only matching, bounded, valid result before deadline
    convert failure to outcome and update graph readiness
finalize stable ordered report; discard every late result
```

Absolute deadline includes discovery, capture/preparation, queue residence, process launch, import, execution and result transport. Each delivery expires at min(dispatch_deadline, delivery_start + binding_timeout). Delivery start does not reset the event deadline after a long queue wait. Unstarted nodes at deadline become skipped_deadline. A deadline is never extended by retries, recursive publication, result parsing, or sequential handlers.

Serialization limits include byte count, nesting depth, collection sizes, maximum string length, maximum bindings and output size. Do not invoke arbitrary __str__, repr, deepcopy, property access or custom JSON serializers on caller objects. There is no business-schema or JSON-only requirement on main arguments or return values. A separate safe worker transport may support only a bounded subset of representations; unsupported argument transport is explicitly reported, not silently coerced or executed inline. Arbitrary host objects never bypass isolation; transport limits are not plugin business schemas.

The host owns all result acceptance. Check event ID, delivery ID, scope lifetime, captured generation, deadline, output schema, and duplicate completion before accepting a result. A newer registry generation alone does not invalidate an already admitted delivery; closed scope or expired deadline does. Host code never unpickles plugin output.

## Synchronous and asynchronous execution

Synchronous and coroutine handlers run in the same worker protocol. The worker invokes the declared callable and awaits an awaitable result on a worker-owned event loop. It never nests an event loop inside the caller's loop. A coroutine that blocks is still terminated through the process supervisor.

Only waiting execution is in target scope: dispatch is for synchronous callers; adispatch cooperatively awaits results without blocking the host loop. Fire-and-observe (including emit/aemit and execution-handle polling) is explicitly excluded by the Human decision. Calling dispatch from a running host event loop is rejected with a diagnostic report directing the caller to adispatch, rather than blocking that loop.

No automatic retry is performed for imports, plugin execution or worker loss. A timeout does not prove that no external side effect occurred. Consumers needing reliable external delivery must supply a separate durable outbox and idempotent reconciliation design; the hooks framework is not a transaction manager.

## Cancellation, process ownership and shutdown

The supervisor, not the application thread, owns launching, reading worker output, deadline monitoring and stopping workers. Bound startup handshakes, pipe reads and output buffering. Worker stdout/stderr are capped diagnostics, separate from the result channel. A worker crash or malformed output produces a terminal failure outcome.

On timeout, mark the outcome terminal immediately, reject late results, request graceful cancellation, then terminate and force-stop only exact owned processes after finite grace periods. Never use unbounded joins. Use a platform backend capable of owning descendants, such as verified process-group containment on POSIX and job containment on Windows; descendants deliberately escaping ordinary groups require a stronger sandbox and are not claimed safe.

Keep reserved worker capacity for processes not yet confirmed dead. If termination cannot be confirmed, quarantine the slot, retain an explicit cleanup-debt record and stop spawning beyond the resource cap. The main flow continues; diagnostics must not falsely report successful cleanup. Unsupported platform containment or an unavailable validated worker launcher rejects delivery instead of executing inline. Packaged/Cython launchers must be validated; do not assume the current executable is a Python interpreter.

Runtime lifecycle: created → running → closing → closed. Scope lifecycle follows its owner's actual lifetime. Conversation scope survives multiple user turns; run scope closes after one Agent2LLM run. Closing a child never closes its parent or siblings.

Shutdown stops new business emissions, optionally admits a reserved bounded terminal notification, cancels queued work, allows a finite drain, and stops owned workers. Required application teardown runs independently of plugin completion. close is idempotent and returns pending cleanup debt instead of waiting forever. No atexit callback may introduce an unbounded wait or re-open a closed diagnostics sink.

Host cancellation of adispatch cancels its pending deliveries and propagates the genuine host cancellation. A plugin raising CancelledError, KeyboardInterrupt, SystemExit, HeavyTaskError, or another domain exception in its worker yields an error outcome only. Distinguish exception origin structurally, not by swallowing every BaseException around a business operation.

## Payload and result semantics

Payloads are detached snapshots, not references to mutable agent state. Default data is metadata: identifiers, counts, stage, outcome and elapsed time. Message content and sensitive application data require explicit domain opt-in and binding field allowlists. Credential values, live database/model objects, locks, runtime handles and executable objects are prohibited.

No hook can mutate host objects merely by modifying its input. Mutating a worker copy and then raising leaves the host unchanged. Arbitrary return values are data only; no implicit merging into event payloads, environment variables, session messages or application results.

For lifecycle events, callers normally ignore values. For other capabilities, a domain extension can validate and consume values through the same DispatchReport. The core does not learn domain-specific meanings.

### Unified handler and Hook Point result envelope

This is the target framework-owned result format, not the current worker wire schema. A Module returns arbitrary content, not this envelope. A normal return of `False`, `None` or `{"error": 1}` is success; `returned.present=true` distinguishes returning None from an exception or a handler never invoked. No business meaning is inferred from the return value.

| HandlerResult field | Contract |
|---|---|
| execution_id, hook_point_name, plan_version | Correlation and the exact captured active version. |
| handler.id, handler.name, handler.kind | Stable identity and registered name; kind is module, default_script_hook or script. |
| status, not_run_reason | success, error, timeout, cancelled, not_run, or completed_with_errors for a default Hook; explain every not-run entry. Protocol/worker failures carry an error category, not fabricated return content. |
| returned.present, returned.representation | Presence of a normal return; representation is direct, transported, reference or unavailable. |
| returned.value, returned.reference | Original value where safely available, or a bounded managed reference; unavailable is explicit and does not turn a normal return into a plugin exception. |
| error.category, error.message | Safe bounded diagnostics, without arbitrary object formatting, credentials or unsafe exception deserialization. |
| timing.started_at, timing.finished_at, timing.elapsed_ms | Observed timestamps and monotonic duration; absent starts for not-run handlers. |
| cleanup.state, cleanup.diagnostic | safe, pending or failed, independently of execution status; pending cleanup prevents unsafe successors. |
| decision.action, decision.authority | continue or block; block requires a Catalog-authorized policy, never an arbitrary plugin return field. |
| children | Ordered Script HandlerResults for the default Script Hook; empty for a zero-script successful no-op. |

HookPointResult contains execution_id, hook_point_name, plan_version, ordered handlers (Modules then the single default Hook), aggregate timing, cleanup and Catalog-authorized decision. Aggregate status is success, completed_with_errors, blocked, timeout, cancelled or unavailable. No valid initial plan means unavailable. Default report policy permits business continuation after settled plugin errors; ordering dependencies require terminal/cleanup-safe predecessors, not successful returns. Host cancellation and original business exceptions retain their established propagation rules.

Arbitrary return objects do not necessarily cross a process boundary unchanged. `direct` describes an already safely owned framework value, not permission to invoke plugins in the host. `transported` uses a bounded allowlisted safe protocol, never untrusted pickle or arbitrary constructors. `reference` is permitted only if the owning isolated endpoint remains managed: the reference is scoped, expires or is explicitly released, and retirement/close cleans its resources. Reference support is a proposal, not an implemented guarantee; until available, untransportable returns use `unavailable` with a safe diagnostic. Worker exit invalidates references. Never keep unbounded workers alive merely to retain results, run arbitrary repr/serialization in the host, or weaken isolation to recover a value. Arbitrary argument content similarly has no business schema, but unsupported safe transport must be reported explicitly. A domain consumer may reject an unavailable representation without mislabelling the plugin's normal return as an exception.

### Failed configuration update and last-known-good plan

The Human chose: “新配置检查失败时:A；Fire-and-observe：A,不实现。” A build failure means a candidate cannot pass discovery/validation/capture (for example a newly added Module lacks callable main or a configured Script cannot be read), not a failure during an already admitted handler execution.

If valid v1 is active and desired v2 fails, reject and clean v2, keep v1 active for new calls, and report desired_revision=v2, active_revision=v1, state=update_failed_using_last_known_good with bounded safe diagnostics. Do not report v2 as activated or retry it on every call. Initial failure without any prior valid plan makes the Hook Point unavailable; only authorized policy decides whether business is blocked. Successful replacement publishes the complete candidate atomically; old admitted executions keep their old snapshot until leases and cleanup are settled. Startup and lazy wrappers use this same state machine and singleflight publication, not separate Script-only paths.

### Result transformation as an extension

Transformation is optional orchestration above the unified engine, not a second kind of hook. A domain-owned ResultPolicy defines allowed proposals, validation, deterministic reduction, and application. It cannot override core isolation, deadlines or resource limits.

Recommended first form: all handlers receive the same base snapshot and return JSON proposals. The caller processes successful values in stable registry order, validates each against its domain schema and invariants, and constructs a new candidate. A rejected proposal preserves the last valid candidate. The caller applies the final candidate once, only if its source revision and scope are still current. Existing required validation still runs afterward.

Example: a prompt extension accepts only an append-fragments proposal. It cannot replace trusted system instructions or rewrite roles. The framework sees ordinary JSON output; only the prompt owner knows the append contract.

If a use case truly needs sequential transformations where handler B sees handler A's result, add a Pipeline extension. It captures one binding plan, invokes the same dispatcher worker primitive for each binding once, and uses one absolute deadline across the chain. It must not re-dispatch all subscriptions at every stage or create a second registry. A failed stage keeps the last accepted candidate. This extension is deferred until a concrete use case justifies the additional complexity.

Reducers and validators executing in the host are trusted bounded application code, not dynamically loaded plugins. Catch their ordinary failures locally and preserve original data. An arbitrary plugin-provided reducer must instead execute as another isolated handler through the same protocol. No feature may reintroduce unbounded user code in the host through a custom result policy.

## Illustrative API usage

Lifecycle publication and optional result consumption use identical registrations and handlers. These are interface sketches, not an implementation prescription.

```text
runtime = HookRuntime(
    settings=settings,
    process_backend=process_backend,
    temp_root=temp_root,
    diagnostic_observer=diagnostic_observer,
)
scope = runtime.open_scope(parent=None, metadata={owner_id: conversation_id})
runtime.register(conversation_started_v1, audit_binding, scope)

report = runtime.dispatch(start_event, policy=bounded_delivery)
continue_required_conversation_work()  # Report failures do not automatically block business flow.
```

```text
base = validated_prompt_snapshot()
report = await runtime.adispatch(prompt_extension_event(base), policy=bounded_delivery)
candidate = prompt_policy.reduce_valid_proposals(base, report)
apply_if_revision_unchanged(candidate)
run_required_prompt_validation()
```

```text
plugin main(*args, **kwargs):
    read detached validated arguments supplied by the framework adapter
    return {"append_fragments": ["A permitted domain-specific fragment"]}
```

Every sketch uses one handler contract. Result consumption does not confer authorization: the application decides whether the proposed data is valid. Pipeline execution remains optional and does not change any public event into a privileged mutation channel.

## Reentrancy, recursion and security

Carry origin and depth explicitly in the worker protocol. Initial policy forbids runtime publication originating inside hook workers; workers have no host runtime reference or emission IPC endpoint. Application callbacks into TopsailAI must retain worker-origin context and disable nested hook activation. Do not rely only on a thread-local counter, which would be lost across process boundaries.

A future controlled nested-emission capability must enforce a propagated parent chain, maximum depth, repeated-event suppression and one shared budget. It is not part of initial delivery. Diagnostic events never invoke hooks, even if an application diagnostic adapter fails. External services calling back into the application need separate ingress correlation; the framework cannot stop a malicious distributed recursion loop by itself.

Allowlist handler packages at deployment boundaries; restrict worker environment and working directory; expose no ambient host references. Run with the minimum practical OS privileges. Process separation protects the host from plugin exceptions and crashes, but same-user code may still access files or network unless a sandbox restricts it. Untrusted third-party code requires an independently reviewed sandbox/container policy, not just this framework.

Do not log raw payloads, output values, exception messages, traceback locals or secrets by default. Worker output is untrusted and must be sanitized. Payload access permissions are data-minimization policy, not proof that a same-user process cannot read other files.

## Observability and resource lifecycle

Inject a non-blocking bounded sink for hook admission, start, completion, rejection, timeout, worker loss, configuration rejection and shutdown-debt summaries. Record event name/version, binding ID, generation, scope correlation, status, queue delay and duration. Safe error categories are sufficient by default.

Counters include admitted, rejected, success, error, timeout, invalid output, cancelled, late result discarded, dependency skipped, queue utilization and live/quarantined workers. Avoid metric labels containing event IDs or other unbounded values. Log identifiers may be retained only under bounded rotation/retention policy.

Rate-limit repeated diagnostics while preserving aggregate counts. Sink failures are swallowed inside the hook boundary and never recursively emitted. A slow arbitrary sink cannot run inline: use a bounded buffer with an isolated downstream consumer. State loss is allowed and reported as dropped diagnostics rather than backpressuring business execution.

Queues have item and byte bounds, registries have binding caps, worker output has byte bounds, pending reports expire, scope close releases registrations, and runtime close releases workers and buffers. The initial framework requires no durable spool. If temporary worker artifacts are needed, allocate them within the configured owner temp root and delete only owned resources with deletion logs.

## Future integration boundary catalog

The following is a planning map based on the prior repository inspection, not a statement that these events exist. Re-read each implementation before a later integration change. All rows use the same HookEvent → handler → HookOutcome protocol, with optional return values ignored unless an explicitly named domain policy consumes them.

| Proposed event family | Candidate owning boundary | Timing and minimum payload | Domain behavior |
|---|---|---|---|
| conversation.started / closing / closed | workspace/agent/agent_shell_base.py, AgentChat._run / run | After setup; before cleanup; after cleanup attempts. Conversation ID and cleanup outcomes. | Await bounded completion; failures never prevent required application cleanup. |
| user2agent.turn.started / finished | workspace/agent/agent_shell_base.py, AgentChat._run | Valid fresh input accepted; terminal branch settled. Turn ID, outcome, persistence checkpoint. | Distinguish succeeded, failed, abandoned and interrupted; no fake final answer. |
| agent2llm.run.started / finished | ai_base/agent_base.py, AgentBase.run | Internal execution entry and after owned run cleanup. Run ID and outcome. | Separate from persistent user conversation. |
| llm.attempt.started / finished | ai_base/llm_base.py, LLMModel.chat transport-attempt boundary | Actual provider attempt, not dequeue of an existing response. Attempt number, duration and safe outcome. | Cannot choose retries or change a response. |
| prompt.extension.requested | ai_base/prompt_base.py, prompt assembly before authoritative validation | Detached allowed extension fields and source revision. | Optional ResultPolicy validates append proposals. |
| context.summary.started / finished | workspace/context/agent2llm.py and workspace/context/ctx_runtime.py, respective summarize methods | After feasibility; after apply or failure. Layer, before/after counts and exact checkpoint. | Generated does not imply applied or persisted. |
| session.messages.changed | context/ctx_manager.py, add_session_message / del_session_messages | After facade result. IDs/counts and partial-backend outcome. | Notification only; no claim of transaction atomicity. |
| task.started / finished | workspace/task/task_tool.py, ctxm_process_task | After admission; after owned settlement attempts. Task ID, result and cleanup status. | Hook success never marks task done. |

User2Agent messages are persistent user/session data. Agent2LLM messages are ephemeral execution context. Never automatically insert hook events or failures into either history. The envelope carries layer and purpose, including summary or background work, rather than conflating every model request with a user turn. No tool, memory or skill integration is included in this catalog or rollout.

## Verification plan

Plan tests before each implementation or integration unit. Existing focused tests use a standalone test publisher and isolated fixture plugins without importing application owners. Test artifacts, logs, caches and worker temporary data must be confined to the workspace .tmp directory. Only owned processes/resources may be cleaned up.

| Test dimension | Required evidence |
|---|---|
| Unified API | Same handler and outcome contract for ignored values, collected values and domain proposal reduction; no hook-kind branch. |
| Registry | Exact matching, duplicate rejection, cycles, missing dependency, stable ordering, invalid initial config, atomic reload and in-flight snapshot behavior. |
| Results | Null versus false/zero/empty preserved; invalid JSON/type/size rejected; no mutable host reference or mutation-on-error leak. |
| Exceptions | Import failure and handler exceptions, including worker-originated control exceptions, do not change the host result or prevent independent deliveries. |
| Deadline | Silent worker, stalled import, blocking coroutine, full queue, slow output and chained handlers all obey one aggregate deadline. |
| Cancellation | Host cancellation still propagates; worker cancellation is an outcome; late/duplicate/mismatched results cannot apply. |
| Concurrency | Scope isolation, per-binding limits, bounded global workers, deterministic report order, reload during dispatch and concurrent close. |
| Resource ownership | Normal and forced stop clean up verified owned descendants; failed cleanup quarantines capacity and cannot trigger unlimited replacement workers. |
| Recursion | Worker-origin publication suppressed, diagnostic failures non-recursive, no nested activation from callbacks into host libraries. |
| Privacy | Metadata-only defaults, field allowlists, environment restrictions, bounded sanitized output and no secret sentinels in diagnostics. |
| Extensions | Proposal validation failure preserves valid input; stale source revision prevents apply; optional sequential extension does not multiply subscriptions or reset deadlines. |
| Main-flow invariant | Same business value/error and required cleanup with hooks disabled, successful, failing, timing out, crashing or overloaded. |
| Performance | Measure disabled/admission overhead, deadline overrun tolerance, queue memory and process-launch cost; define measured budgets before production enablement. |

Use synchronization/ready signals rather than equal-duration sleeps. Isolation canaries require real child processes and a separate loose test anti-hang watchdog. Do not confuse mocked timeout return values with proof that workers terminate. Test supported operating systems and packaged launchers separately; document unsupported environments.

Later LLM-related integrations require BDD using `tests/mock/llm_mock_server.py` over real loopback HTTP/SSE, proving unchanged provider request counts. Full project unit verification uses `tests/run_tests.py`, not a single pytest invocation over the full unit tree. Focused committed-tree evidence for earlier implemented units includes module discovery 22/22, HookScript orchestration 59/59, and Runtime/reload/diagnostics 68/68; a separate Hooks-scope run reported 277 collected and 277 passed in 20.72 seconds. For the simplified configured Runtime change, public Runtime BDD passed 4/4, interruption-sensitive validation passed 668/668 without coverage instrumentation, the prescribed complete Unit runner passed all 294 files, and authoritative commit-scoped coverage passed at 289/302 statements (95.6954%), 107/112 branches (95.5357%), and 396/414 combined (95.6522%). Cross-platform, packaged-launcher, application-integration, and production-performance acceptance remain separate.

## Phased delivery

### Standalone contract and scheduler

Implemented and committed: typed records, schema validation, configuration, immutable registry, dependency planning, no-op behavior, and deterministic scheduler coverage. Application enablement remains outside this phase; acceptance claims remain tied to specific recorded gates.

### Isolated worker execution

Implemented and committed: bounded JSON protocol, process backend, sync/async handler invocation, deadlines, cancellation, output caps, and cleanup-debt handling. Focused real-process tests exist, but deployment and cross-platform/packaged-launcher acceptance remain gated separately.

### Runtime ownership and diagnostics

Implemented and committed: bounded queues, scope lifecycle, explicit registration handles, operational settings reload, non-recursive diagnostics, and shutdown reporting. Focused lifecycle gates are recorded; application integration and broader acceptance remain separate.

### Optional result-policy extension

Implement a minimal proposal reducer example over ordinary DispatchReport values. Verify failure fallback and source-revision checks. Defer sequential Pipeline until a concrete use case requires it. Do not introduce category-specific registries or bypass execution isolation.

### Selected application integration

After separate approval, add one event family at a time from the catalog, beginning with conversation or run lifecycle. Keep core ownership and control flow unchanged. No legacy migration or tools/memory/skill work is bundled into this phase. Update factual runtime documentation only when functionality is actually shipped.

## Risks and decisions

| Risk | Decision |
|---|---|
| Strong isolation adds process-launch cost | Accept bounded cost initially; measure before adding reusable workers. Target business calls wait synchronously or through await; non-waiting emission is excluded. |
| Strict ordering lengthens dispatch | One aggregate deadline; optional explicit parallelism for independent nodes only. |
| Hook outcome mistaken for business success | Separate reports from domain values and document exact lifecycle checkpoints. |
| Optional result processing becomes another framework | Keep domain policy outside core and reuse the same registry, worker protocol and outcomes. |
| Fake non-blocking promises | State finite wait semantics and OS limits; prohibit arbitrary inline plugin execution. |
| External mutation survives timeout | No automatic retries or rollback claims; require idempotency outside this component. |
| Shutdown cannot confirm worker death | Report cleanup debt, quarantine capacity, never block main cleanup indefinitely. |
| Expansion into unrelated tooling | Exclude tool/memory/skill and old-hook migration from current scope and phases. |

## Decision summary

One framework provides registration, event delivery, ordering, isolated execution, deadlines, outcomes and lifecycle management. Functional differences live in event schemas and caller-owned result policies, not hook categories. Optional extensions may propose data but never gain implicit authority over core application flow. Build and verify this component independently first; choose lifecycle integration points only after its non-disruptive behavior is proven.

## Configuration convenience and migration boundary

`hook_name` plus exactly one of `scripts` or `folder` is a convenience interface for the Hook Point's default Script Hook, not permission to publish a second first-class plan type. Both source forms use the name key above; list order is not an execution contract. Folder enumeration remains bounded, recursive and no-symlink, with shell-free format validation and deployment-owned trust. Invalid or duplicate entries reject the whole change and preserve the previous unified plan.

Hook names retain the exact case-sensitive `^hook_[a-z][a-z0-9_]*$` contract, without event-name, path, prefix or alias fallback. Identical complete plans are successful no-ops; replacement must preserve unrelated registrations and admitted old snapshots. Execution retains existing failure, timeout and cancellation policies with no automatic retry. Scope and Runtime close own plan removal, admitted-work settlement, artifact retirement and bounded cleanup recovery.

Startup and lazy registration must atomically establish the complete Module/default-Hook plan and preserve immutable artifact capture, scope ownership, deadlines, cancellation and cleanup recovery. Callers need not manage candidates, leases, TTLs, publication or disposal. Hiding candidate mechanics does not supersede the terminal architecture.

### Retained compatibility and legacy APIs

The retained configured APIs are described in [Hooks API](../docs/Hooks_API.md). U06 synchronous dispatch is already a unified-plan adapter; U08 must verify async lifecycle equivalence, and U10 must remove/migrate nonwaiting emission. This documentation synchronization changes no production signatures.

The prior claim that terminal `hook_script` was merely historical and no longer defined the public architecture is withdrawn. Earlier task records remain historical evidence, but cannot override the Human's clarification. The default terminal Handler, per-point cardinality, Module `main` entry and Module-before-Script name ordering remain authoritative.

## Framework-readiness extension before application Hook-point rollout

The implemented extension provides preparation and insertion conveniences, but complete architecture readiness remains gated by U07–U11 before application owners add Hook points to core flows. This is a feature extension and convenience layer over the implemented Runtime, not a replacement for it. It adds environment-driven bootstrap, startup or first-use registration, a shared execution facade, and two insertion styles: decorators for ordinary callable boundaries and explicit function-body calls for precise lifecycle points.

These framework-readiness APIs are implemented and exported. The following configured compatibility calls remain; synchronous dispatch is unified, while async acceptance and nonwaiting removal remain pending:

```python
runtime.register_configured(...)
runtime.dispatch_configured(...)
await runtime.adispatch_configured(...)
runtime.emit_configured(...)
```

### Layering and ownership

The target dependency flow is:

```text
application configuration boundary
  -> ConfiguredHookBootstrap + ConfiguredTrustPolicy
  -> application-owned long-lived HookScope
  -> ConfiguredHookRegistrar
       -> startup eager registration, or lazy singleflight registration
  -> ConfiguredHookExecutor
       -> dispatch / awaited adispatch (no fire-and-observe)
  -> unified Hook-point plan (Modules -> default hook_script -> Scripts)
     U06 sync adapter is committed; U07/U08 lifecycle acceptance remains pending
```

Core business modules receive a `ConfiguredHookExecutor` explicitly. They never read environment variables, parse Hook configuration, scan script folders, build trust assertions, or mutate Runtime trust. Decorator and explicit insertion styles must call the same Executor and Registrar; neither may duplicate discovery, registration, failure caching, reload, or cleanup logic.

The first release owns configured registrations in one application-level Scope with the Runtime lifetime. Short-lived request-level configured scopes are deferred because they would repeat capture and retirement. Runtime close first closes admission, settles Registrar waiters and owned deliveries under existing deadlines, retires plans and artifacts, and reports bounded cleanup debt.

### Environment-driven bootstrap

Environment is read exactly once at the application configuration boundary and converted into a deeply detached typed snapshot. No dispatch, decorator wrapper, Registrar, or worker reads `os.environ`.

The implemented variables are:

| Variable | Default | Contract |
|---|---|---|
| `TOPSAILAI_CONFIGURED_HOOKS_ENABLED` | `0` | Enable the versioned configured-Hook bootstrap. Disabled means no config or manifest I/O. |
| `TOPSAILAI_CONFIGURED_HOOKS_CONFIG` | empty | Absolute path to a versioned Hook configuration document. |
| `TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST` | empty | Absolute path to a versioned deployment trust manifest. |
| `TOPSAILAI_CONFIGURED_HOOKS_TRUST_MANIFEST_SHA256` | empty | Deployment-pinned digest for the manifest; required when enabled. |
| `TOPSAILAI_CONFIGURED_HOOKS_REGISTRATION_MODE` | `startup` | `startup` or `lazy`. |
| `TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY` | `fail` | `fail` or explicit `disable`; silent partial enablement is prohibited. |

Environment variables locate versioned files and choose policy; they do not embed per-Hook script lists or artifact assertions. The current Hook configuration maps exact Hook names to `enabled` plus exactly one of `scripts` or `folder`. These fields configure the default Script Hook, and execution uses final registered-name order through the unified U06 adapter. Whole-plan startup/lazy/reload failure acceptance remains U07; this Script-source schema does not itself expose ordinary ModuleSource registration. Relative script paths resolve only against source roots authorized by the manifest. Configuration and manifest parsers validate shape and aggregate budgets before normalization, reject path escape and duplicate canonical files, and return immutable owned records.

The implemented public trust-manifest loader verifies the pinned digest and constructs exact source-root, interpreter/native-policy, Python runtime, deployment closure, and `ArtifactClosureAssertion` authority. Runtime code never authorizes files it has just discovered by computing assertions on demand. Missing, malformed, stale, or mismatched trust fails closed. Trust changes require a replacement Runtime and application Scope; in-place trust mutation is not supported.

In target `startup` mode, bootstrap prepares complete unified plans before Hook admission. With no valid prior plan, a failing Hook Point is unavailable and produces a structured diagnostic; business startup is blocked only by Catalog-authorized policy. A failed update retains the last known good plan, never publishes a partial candidate, and reports the desired/active revision mismatch. The existing fail/disable bootstrap behavior is implementation evidence, not an unconditional target startup-block rule.

### Lazy registration at execution

`lazy` mode loads and validates the immutable configuration and trust snapshot at startup but defers script discovery, capture, and atomic plan publication until the Hook name is first executed. It never defers environment or manifest loading.

Registrar state is keyed by `(scope incarnation, hook_name, configuration_generation)`:

```text
UNCONFIGURED -> no-op/reported absence
UNINITIALIZED -> REGISTERING -> READY
                         |-> FAILED_DETERMINISTIC
                         |-> FAILED_TRANSIENT
READY(active) -> PREPARING(desired, active retained)
PREPARING -> READY(new active) | UPDATE_FAILED(old active retained)
any state -> CLOSED
```

Exactly one caller performs discovery/capture/publication for one key. Concurrent synchronous and asynchronous first callers share the same singleflight result; they do not create separate artifacts or advance Registry generation more than once. File I/O and capture occur outside Runtime and Registrar state locks. Before publication, the winner revalidates Runtime, Scope, and configuration generation so a close or reload cannot publish stale work.

`READY` is the steady state: only an in-memory state lookup and existing configured dispatch occur, with no environment, configuration, manifest, directory, hash, or registration I/O. An identical active plan remains a no-op under existing Registry semantics.

Deterministic failures include invalid configuration, missing authority, digest or artifact mismatch, path escape, unsupported executable, invalid folder contents, and closed ownership. They are cached for the configuration generation and retried only after explicit reload. Narrowly classified transient resource or contention failures may be retried by one later caller after bounded backoff and attempt limits. Classification is typed; string matching is prohibited. There is no immediate retry loop.

Reload consumes a complete, already validated snapshot and creates a new configuration generation. Unchanged entries retain `READY`; changed lazy entries acquire a pending desired revision while retaining their active last-known-good plan; removed entries retire their plans; changed startup entries are eagerly replaced. Publication is atomic per complete Hook plan, admitted executions retain their immutable old plan, and failed replacement cannot expose a partial plan. Failed candidates are cleaned and rejected; both new and existing calls may use the last known good active revision, with explicit desired/active mismatch diagnostics. No prior valid plan means unavailable, not an empty successful execution. Trust identity changes require Runtime replacement rather than Registrar reload.

Existing `emit_configured()` and `ConfiguredHookExecutor.aemit()` are non-waiting implementation surfaces to migrate or withdraw; they are explicitly excluded from the target. Lazy dispatch and adispatch share registration singleflight and wait for the unified execution result. Failed desired-revision preparation retains the active valid revision; readiness must track both rather than erase the old plan.

### Shared execution facade

The target waiting-only facade is sketched below; it is not a claim that current code enforces the result envelope:

```python
class ConfiguredHookExecutor:
    def dispatch(self, point, *, payload, operation=None) -> HookPointResult: ...
    async def adispatch(self, point, *, payload, operation=None) -> HookPointResult: ...
```

`point` is a catalog-owned `HookPointDeclaration`, not an arbitrary caller-created name/schema pair. The Executor creates the immutable event from the declaration, owning Scope, detached payload, and supplied correlation metadata; invokes the shared Registrar according to startup/lazy mode; then calls the existing Runtime method. Sync dispatch retains the existing rejection inside a running event loop. Async first-use preparation runs blocking discovery/capture in controlled infrastructure and does not block the event loop.

An unconfigured or disabled ordinary point returns a stable no-op/report outcome. A configured registration or execution failure follows the declaration policy:

- `report` is the default and preserves host flow while recording the structured result.
- `block` is allowed only when the catalog explicitly marks a security-critical point and its owner defines the host exception contract.

No Hook return value implicitly replaces a business result. Any future transformation requires a separately reviewed domain reducer.

### Decorator Hook-point insertion

Decorators are intended only for callable boundaries whose timing aligns with function entry, successful return, or exceptional exit. They are not appropriate when the point belongs between statements, after a partial commit, around a branch, before mandatory cleanup, or when background admission is required.

Implemented shape:

```python
@hook_point(
    before=OPERATION_BEFORE,
    success=OPERATION_SUCCESS,
    error=OPERATION_ERROR,
    executor_attribute="hook_executor",
    payload_builder=build_safe_payload,
)
def operation(...): ...
```

`before`, `success`, and `error` are three optional, distinct `HookPointDeclaration` references with separate stable names, schemas, policies, and budgets. They are not labels applied to one ambiguous Hook point. At least one must be supplied. The canonical post-return phase name is `success`; an API alias named `after`, if ever provided for compatibility, must resolve only to the same success-only slot and cannot coexist with `success`.

For free functions, `executor_provider` may be supplied instead of `executor_attribute`. The provider is application dependency injection; it must return an existing Executor and must not read environment or create a Runtime. Instance methods use the explicitly named receiver attribute. `functools.wraps`, descriptor binding, annotations, and the original inspectable signature are preserved. For `classmethod` or `staticmethod`, the Hook decorator applies to the underlying function inside the descriptor decorator; ambiguous ordering is rejected or documented by validation rather than guessed.

Decorator semantics are:

- Ordinary synchronous functions use `dispatch`; coroutine functions use `adispatch`. A synchronous wrapper never starts an event loop, and an async wrapper never blocks it with sync registration.
- `before` runs immediately before invoking the original callable, after Python argument binding and payload validation. Under `report`, its Hook failure is recorded and invocation continues. An explicitly approved `block` failure raises the cataloged `HookPointBlockedError`, prevents callable entry, and does not emit `success` or `error` because the original callable did not run.
- `success` runs only after the original callable returns normally and receives that result through the safe invocation view. It never runs when the callable raises. Under `report`, Hook failure is recorded and the exact original return object is returned. Under explicitly approved `block`, Hook failure raises `HookPointBlockedError` after business work has already completed; the catalog must acknowledge that semantic risk and define caller recovery.
- `error` runs only when the original callable itself raises. It receives only an allowed detached exception summary, never the live exception or traceback. After error-Hook processing, the wrapper executes a bare `raise` in the active handler so the exact original exception instance and original traceback continue propagating. It never returns a fallback, converts the exception, or returns a Hook report.
- If the `error` Hook fails under `report`, that failure is recorded as bounded diagnostics and the original business exception still wins. Even an explicitly security-critical `block` error Hook cannot replace, chain over, or suppress an already-active business exception; its blocked outcome is recorded, while bare `raise` preserves the original. Exception precedence is therefore always original callable exception over error-Hook failure.
- For every invocation that enters the callable, `success` and `error` are mutually exclusive: normal return emits `success` once and `error` zero times; callable failure emits `error` once and `success` zero times. An enabled `before` emits once before either path.
- The payload builder receives a read-only invocation view and is denied all business data by default. A declaration's `argument_fields` may allow named bound arguments; `result_fields` may allow named keys from an exact built-in `dict` return value only for `success`; and `error_fields` may allow only the detached `type` and/or `message` tokens for `error`. Other result types expose no result fields, avoiding custom mapping execution while constructing the view. The `type` token is the exception class name. The `message` token is included only when the base exception has exactly one exact-string argument; extraction never calls `str(error)` or other exception formatting code. `sensitive_fields` remains an additional argument denylist for compatibility and cannot overlap `argument_fields`. Configuration cannot add to any declaration allowlist.
- Every authorized value is copied through bounded JSON validation before the builder runs. Builder mutation cannot affect business objects, later business mutation cannot change an existing view, and live objects, undeclared fields, credentials, raw exception objects, and tracebacks are never exposed to the builder or sent to workers. Payload schema validation and size limits still run after the builder and before dispatch.
- Recursive and nested invocations each create an occurrence with parent operation/depth metadata. Existing origin/depth suppression prevents worker-origin recursion. There is no accidental process-global recursion guard that suppresses unrelated calls.
- Applying the same before/success/error declaration tuple and versions to an already marked function is an idempotent no-op. A conflicting second decoration is rejected at definition time; deliberate nested decorators must use distinct declarations and make ordering explicit.
- Generator and async-generator functions are unsupported initially and rejected at decoration time because entry, iteration, return, close, and exception boundaries require a separate lifecycle contract.

Async example for an eligible method:

```python
@hook_point(
    before=USER_LOOKUP_BEFORE,
    success=USER_LOOKUP_SUCCESS,
    error=USER_LOOKUP_ERROR,
    executor_attribute="hook_executor",
    payload_builder=build_user_lookup_payload,
)
async def lookup_user(self, user_id: str) -> User:
    return await self.repository.get(user_id)
```

A synchronous function uses the identical declaration mapping; only its wrapper calls `dispatch` instead of awaiting `adispatch`. This convenience wrapper must compile to the same Executor calls an explicit insertion would make; it has no independent registration cache.

### Explicit function-body insertion

Explicit insertion is the default for precise core lifecycle work. The owning module selects a catalog declaration and builds a minimal detached payload at the exact checkpoint.

Synchronous before/success/error example:

```python
def save_record(record, hook_executor):
    hook_executor.dispatch(RECORD_SAVE_BEFORE, payload=safe_record_input(record))
    try:
        result = persist(record)
    except Exception as error:
        hook_executor.dispatch(RECORD_SAVE_ERROR, payload=safe_error(error))
        raise
    hook_executor.dispatch(RECORD_SAVE_SUCCESS, payload=safe_record_result(result))
    return result
```

Asynchronous example:

```python
async def run_task(task, hook_executor):
    await hook_executor.adispatch(TASK_BEFORE, payload=safe_task_input(task))
    try:
        result = await execute_task(task)
    except Exception as error:
        await hook_executor.adispatch(TASK_ERROR, payload=safe_error(error))
        raise
    await hook_executor.adispatch(TASK_SUCCESS, payload=safe_task_result(result))
    return result
```

Waiting completion example:

```python
report = await hook_executor.adispatch(
    TASK_FINISHED,
    payload=safe_task_result(result),
)
```

The explicit owner retains business ordering, branching, mutation, return, and exception authority. It must not infer success before persistence/cleanup checkpoints or place a blocking Hook inside mandatory cleanup. Both sync dispatch and async adispatch wait for completion; fire-and-observe is outside target scope.

### Hook-point declaration catalog

No core Hook point may be added before an AI-maintained catalog declaration is reviewed. Each `HookPointDeclaration` records:

| Field | Requirement |
|---|---|
| Stable name and major version | Exact immutable selector and versioned compatibility boundary. |
| Owning module and callable/checkpoint | Project-relative owner and precise publication location. |
| Phase | Exactly one of `before`, `success`, or `error`; decorator slots always reference separate declarations, even when schemas happen to match. `success` is post-normal-return only. |
| Event schema and payload budget | Detached JSON schema, required fields, maximum bytes, and example without secrets. |
| Invocation mode | `sync`, `async`, or async background admission. |
| Scope | Initially the application Scope; deviations require lifecycle justification. |
| Failure policy | Default `report`; security-critical `block` requires explicit approval and host error contract. A blocking `success` declaration must approve post-business-work failure risk; an `error` declaration can never replace an active business exception. |
| Sensitive-field policy | Allowlist, redaction, exception-summary rules, and prohibited fields. |
| Ordering and latency | Required checkpoint ordering, aggregate deadline, startup/first-use allowance, and steady-state overhead budget. |
| Ownership and cleanup | Owner of Executor, operation correlation, close ordering, and diagnostics. |

The catalog is the source of event construction truth for both decorators and explicit calls. Hook configuration selects scripts for a known declaration; it cannot invent schemas or turn an ordinary point into `block` through an environment file.

### Lifecycle, diagnostics, and performance gates

The bootstrap owner creates one Runtime, one long-lived application Scope, one Registrar, and one Executor. It publishes them only after startup registration succeeds or explicit whole-layer disablement is recorded. Shutdown prevents new ensure/dispatch admission, wakes registration waiters, settles work, closes Scope and Runtime, and reports cleanup debt without allowing a late registration to republish.

The framework currently reuses the Runtime's implemented bounded, non-recursive diagnostic path and returns typed bootstrap, registration, dispatch, and cleanup results. Dedicated lifecycle event names for bootstrap loaded/rejected/disabled, startup registration started/completed/rejected, lazy registration winner/wait/completion/rejection/retry, invalidation, and Runtime replacement are rollout observability requirements; they are not claimed as emitted by the current wrapper modules. Before a concrete core Hook point is enabled, its integration must either map those states into the owning application's bounded diagnostic sink or document the equivalent existing signal. Safe fields are Hook name, Scope ID, configuration generation, trust identity, mode, duration, attempt, and typed error category. Configuration bodies, environment values, script contents, credentials, and raw paths must not be logged.

The framework tests must prove structural performance properties: disabled bootstrap performs no config/manifest I/O, `READY` lookup performs no bootstrap filesystem I/O, and lazy async registration moves blocking preparation off the event loop. Numeric production budgets for disabled overhead, `READY` lookup, decorator wrapping, first-use discovery/capture, queue memory, process launch, and close latency depend on each concrete Hook point and deployment; they are measured and approved during core rollout rather than claimed by the framework implementation alone.

### Reachability matrix

| Condition | Startup mode | Lazy mode |
|---|---|---|
| Disabled | No config/manifest I/O; no registration. | Same. |
| Unconfigured known point | No plan; stable no-op/report. | `UNCONFIGURED`; no discovery. |
| Valid configuration/trust | Register before business admission. | Register once on first execution, then `READY`. |
| Invalid desired config or manifest | Reject candidate; retain valid active plan with mismatch diagnostics, otherwise unavailable. | Same policy; cache failure for the desired revision. |
| Artifact mismatch | Reject candidate; retain last known good, otherwise unavailable. | Same; deterministic failure cached for desired revision. |
| Concurrent first execution | Already ready. | One registration winner; all callers share result. |
| Runtime or Scope closed | No registration/admission. | `CLOSED`; waiters wake with stable rejection. |
| Config reload unchanged | No publication/generation change. | Retain `READY`. |
| Config reload changed/removed | Eager atomic replace; failure retains active; explicit removal retires. | Prepare desired revision on next use while retaining active; explicit removal retires. |
| Trust change | Replace Runtime and Scope. | Replace Runtime and Scope. |
| Non-waiting execution | Excluded from target. | Excluded from target. |

### Framework-ready acceptance criteria

The Human may schedule core-code Hook-point rollout only when all of the following are true:

- A public versioned trust-manifest loader and typed immutable bootstrap exist and fail closed against pinned deployment authority.
- Both `startup` and `lazy` modes pass lifecycle, concurrency, reload, invalidation, closure, and cleanup tests; `startup` remains the default.
- Registrar singleflight proves one discovery/capture/publication per Scope/Hook/configuration generation across sync and async first callers.
- Executor dispatch and awaited adispatch capture the same unified plan and return the target HookPointResult; no fire-and-observe API is included.
- Decorator support maps one wrapper to distinct before/success/error declarations, preserves sync/async contracts and binding, and proves phase cardinality: before once before entry, success exactly once only on normal return, and error exactly once only on callable failure.
- Decorator error-path tests prove the exact original exception object and traceback frames survive ordinary and failing `report` Hooks and an explicitly blocking error Hook; no path returns a fallback, Hook report, converted exception, or replacement exception.
- Blocking-before tests prove callable non-entry; blocking-success tests prove the catalog explicitly approved failure after completed business work. Generators and unsafe payload exposure remain rejected.
- Explicit insertion supports exact before/success/error checkpoints without changing business ownership.
- One catalog contract drives both insertion styles, with reviewed schema, sensitive fields, mode, Scope, failure policy, ordering, latency, and owner.
- Trust changes replace Runtime; graceful close prevents stale publication and reports zero unexplained cleanup debt in acceptance runs.
- Structural performance tests prove disabled and `READY` paths perform no hidden bootstrap filesystem I/O and async first use does not block the event loop; each concrete core Hook-point rollout records and approves its numeric latency and resource budgets.
- Unit coverage exceeds the project threshold, BDD proves user-visible bootstrap/decorator/explicit behavior, integration uses real isolated workers, and a non-empty configured public demo uses the supported manifest loader.
- Configured-bootstrap environment variables are synchronized in `env_template` and `docs/Environment_Variables.md`.
- Core integration remains absent until this gate is accepted.

### Readiness status and implementation roadmap

**Full architecture acceptance remains gated by U07–U11.** U06A–U06D synchronous per-point execution, `main` invocation and both name-order stages are committed and verified in their selected affected scope; the older inventory below remains historical evidence, not full lifecycle/core-rollout approval.

Already implemented and verified:

- Generic Runtime/Scope/Registry/Scheduler, process isolation, diagnostics, deadlines, cleanup, explicit binding APIs, and settings reload.
- Exact configured Hook names, ordered scripts/folder discovery, immutable capture, atomic plan replacement, sync/async/background configured execution, and Scope/Runtime cleanup.
- Public Runtime BDD, interruption validation, the 294-file Unit runner, strict commit-scoped coverage, and maintained generic real-worker demos.

Framework-readiness implementation units completed in dependency order:

1. **Versioned trust-manifest loader and typed bootstrap:** implemented in `hooks/configured_bootstrap.py` with pinned digest, strict schema/path/budget validation, and immutable authority records.
2. **Startup application-Scope registration:** implemented in `hooks/configured_registration.py` with `fail` and whole-layer `disable` behavior.
3. **Lazy Registrar singleflight:** implemented with shared sync/async state, deterministic failure caching, typed bounded transient retry, reload/invalidation, and close arbitration.
4. **ConfiguredHookExecutor facade:** implemented in `hooks/configured_executor.py` with `dispatch`, `adispatch`, and lazy-safe async `aemit` over the existing Runtime APIs.
5. **Hook-point catalog and explicit insertion contract:** implemented in `hooks/hook_point_catalog.py` with exact declaration ownership and policy validation.
6. **Decorator adapter:** implemented in `hooks/hook_point_decorator.py` with distinct before/success/error declarations, cardinality, identity-preserving error propagation, recursion metadata, idempotency, binding/metadata preservation, and generator rejection.
7. **Framework acceptance:** focused Unit, BDD, real-worker integration, a non-empty configured startup demo, scoped coverage, and environment/API/design synchronization have implementation evidence. Final full regression and per-file completion review remain pending and must pass before the framework is accepted. Production performance budgets remain a rollout-specific acceptance input rather than a reason to change framework semantics.
Prerequisites before core rollout are final acceptance of units 1–7 plus a reviewed initial Hook-point catalog. Explicitly deferred to the later core-integration phase: adding decorators or function-body calls to `workspace/`, `ai_base/`, `context/`, tasks, tools, memory, or skills; choosing concrete payloads from live business objects; and changing domain results based on Hook outputs. Each later core point is one separately reviewed logical unit with its own invariants and BDD/integration evidence.
