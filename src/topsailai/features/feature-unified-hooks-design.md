---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: input and Summary direct-entry migration accepted through U4; U5 overall acceptance pending
scope: direct input and eight ACTIVE Summary Hook Points (plus two inactive phase-two candidates) plus retained legacy libraries; broader rollout deferred
---

# Standalone Unified Hook Framework

## Human revision and accepted generic-entry prototype

**Decision precedence — 2026-10-16:** the following Human decisions supersede conflicting execution-authorization, public-entry and initialization/lifecycle requirements for the generic Hook Point target. The older sections remain historical architecture and describe retained legacy implementations; they must not be used to require trust admission, an observer adapter or workspace application owners on the current input/Summary path. This is a scoped prototype acceptance, not a migration of the complete framework or broader production rollout.

**Maintenance scope — 2026-10-17:** Only the `point_entry` direct-entry approach (`TOPSAILAI_HOOK_POINTS` -> `hooks/point_entry.py`) is currently supported and maintained. All other resource-selection paths described in this document — the generic configured bootstrap (`ConfiguredHookBinding`), the selected-resources contract (`ConfiguredSelectedResources` / `HookPointResourceSelection`), and the historical prepared/trust summary path — are retained legacy libraries only: they are not wired into production, are not maintained, and must not be treated as supported configuration surfaces. New work and tests target `point_entry` exclusively.

Human corrections, verbatim:

> 不需要所谓的“部署信任、解释器与依赖准入”，判定文件有可执行权限，直接执行就可以了。

> 我看到input_message引入了这个方法 observe_before_input，这个不对啊，我要求的是 引入 hook point，observe_before_input 太过具体了。

> 那个HookApplication 完全不需要存在！初始启动方 直接写在 hooks/__init__.py 就可以了。

Human acceptance and commit authorization: “达到预期了：请更新文档并commit”.

The target is a native business function calling `hook_point_xxx()` directly (`def func_native(): hook_point_xxx(); ...`), without Hook-specific arguments, constructor fields, observer adapters or application-binding objects. The point automatically loads bundled point-local and environment-configured external Modules/Scripts. `input_message()` now calls the zero-argument `hook__workspace__before__input_message()` after input-mode selection and before reading; input signatures, command interception and exit behavior remain unchanged.

| Revised group | Accepted target and implemented prototype boundary |
|---|---|
| Execution authorization | Scripts with executable permission are attempted directly; no deployment manifest, interpreter allowlist or dependency-closure admission. Ordinary OS execution failure is reported. This does not make subprocesses a sandbox or roll back side effects. |
| Hook Point public entry | A named point delegates to the generic `invoke_hook_point()` entry. It automatically merges local and external resources, runs Modules before Scripts, and sorts each kind by filename. The prototype uses a small separate executor, not the legacy Runtime/default `hook_script` result plan. |
| Initialization and lifecycle ownership | Bootstrap is in `hooks/__init__.py`; first invocation reads `TOPSAILAI_HOOK_POINTS` into a cached detached snapshot. No HookApplication is required. The two workspace owners are deleted; shared application-access and prepared/trust APIs remain explicitly composed legacy libraries. |

`TOPSAILAI_HOOK_POINTS` maps exact point names to `modules` and/or `scripts`, each an absolute file/folder string or list. Membership is rediscovered per invocation, directories use direct children only, and duplicate same-kind filenames reject the whole point. Modules are `.py` files or compiled extension modules recognized by the platform `importlib.machinery.EXTENSION_SUFFIXES` (for example `.so` on Linux, `.pyd` on Windows), excluding `__init__.py`, imported and invoked **in the current process** as `main(**kwargs)` entries; return values/output are discarded. Scripts are launched directly as subprocesses without a shell wrapper. See the configuration reference for the environment contract; no additional variable is introduced.

Implementation: `hooks/__init__.py`, `hooks/point_entry.py`, `hooks/points/workspace/before_input_message/__init__.py` and `workspace/input_tool.py`. gpt-astra recorded the design, ds-coder implemented/repaired, and gpt-sol independently reviewed. First review REJECTED two cleanup defects: cleanup replacing a host interruption, and loss of child recovery ownership. Both were repaired and independently reproduced; final verdict **ACCEPTED WITH MINOR ISSUES**. Independent focused evidence: **43 passed in 2.57s, exit 0; `hooks/point_entry.py` 179/179 statements and 62/62 branches, 100%**. This evidence is scoped, not full-project coverage.

**Module execution revision — 2026-10-17:** Modules are now imported and invoked **in the current process** (`importlib` import of the selected file, resolve `main`, call `main(**kwargs)`); the former child-process worker `hooks/point_entry_worker.py` was removed as dead code. Only Scripts still run as subprocesses and retain the exact cleanup-record/process-group custody. Because in-process code cannot be preempted, the aggregate deadline is checked only **before** invoking a Module; an overrunning Module is not killed. Ordinary Module import/execution failures become a structured `EntryResult(status="error")`, while host control flow (`KeyboardInterrupt`/`SystemExit`/`CancelledError`) still propagates.

Original KeyboardInterrupt/SystemExit/CancelledError identity propagates through cleanup failures. Exact cleanup records retain process responsibility; group-signal failure still attempts direct-child reaping, unresolved ownership blocks new plugin starts, and reaped historical PGIDs are never re-signalled. A group whose settlement cannot be confirmed may keep execution blocked indefinitely; no explicit operator settlement API exists. Restart does not prove escaped descendants have exited.

Limits: POSIX only, no new decorator integration, no full regression/cross-platform/production-lifecycle acceptance. The five-second execution budget is not a strict total-duration bound: discovery and global-lock waiting are not bounded by that timer, and cleanup may add a one-second wait per child. Process-creation handoff interruptions, escaped descendants and machine failure remain outside prototype guarantees. Plugin stderr is discarded; path/exit diagnostics are limited. No real bell execution or audibility is claimed. The residual stale task-document statuses are synchronized by this documentation update.

## Current direct-entry architecture

Since the 2026-10-16 migration, input and the eight phase-one Summary checkpoints call named point functions which delegate to `hooks.invoke_hook_point()`. Initialization and the cached `TOPSAILAI_HOOK_POINTS` snapshot belong to `hooks/__init__.py`, not a workspace application owner. `HooksApplication` and `SummaryHooksOwner` and their production builders have been removed; business factories no longer accept Hook Executor, preparation, trust or temp-root keywords.

The current contract is documented in [Hooks API](../docs/Hooks_API.md#current-direct-entry-architecture): `{}` still activates internal discovery; Modules receive validated metadata, while directly executed Scripts receive no Summary payload. Per-operation checkpoint and exception semantics remain intact. Dynamic discovery, `EntryResult` results, POSIX cleanup and budget limits are not the legacy prepared snapshot, last-known-good or owner lifecycle contract.

Shared prepared/trust and application-access libraries remain unchanged and explicitly composable; the historical sections below do not impose those APIs on current business activation.

### Current implementation inventory

Eleven Hook Points are declared: ten Summary points under `hooks/points/context/` and one workspace point `hook__workspace__before__input_message` under `hooks/points/workspace/before_input_message/`.

| Group | Points | Modules |
|---|---|---|
| ACTIVE Summary (phase one) | `before_summary_generate_{user2agent,agent2llm}`, `after_summary_apply_{user2agent,agent2llm}`, `error_summary_generate_{user2agent,agent2llm}`, `error_summary_apply_{user2agent,agent2llm}` | one `modules/observer.py` each (8 total), all delegating to `hooks/points/context/summary_events_observer/observer.py` |
| INACTIVE Summary (phase-two candidate) | `after_summary_generate_user2agent`, `after_summary_generate_agent2llm` | none (no `modules/` directory) |
| Workspace | `hook__workspace__before__input_message` | none (no `modules/` directory) |

No `scripts/` directory exists under `hooks/points/`; `TOPSAILAI_HOOK_POINTS` defaults to `"{}"` in `env_template`, so only bundled point-local Modules execute unless external resources are configured.

## Historical prepared framework status and scope

The following historical specification records the architecture clarified by the Human on 2026-10-10 and the subsequently approved [Summarize Hooks Application](#summarize-hooks-application) design. The former summarize application used explicitly opted-in preparation, ownership and point-local Module/Script wiring; broader rollout and final acceptance remain separately gated. See the implemented file-membership baseline below. Implementation evidence is recorded separately and does not override the target. U06–U10 unified waiting execution, desired/active reload diagnostics, async cancellation custody, Catalog authority and breaking nonwaiting removal are committed. U11A–E add real target business/process evidence. [The open architecture issue](../issues/issue-hook-point-default-script-handler-architecture.md) still requires U11H final acceptance and a Human decision on accepted provenance REDs; application-domain integrations beyond the opt-in summary path remain deferred.

| Dimension | Current status |
|---|---|
| Implementation | U06A–U06D complete unified synchronous Module/default-Hook execution, configured adaptation, ordinary source registration and execution-local custody; U07–U10 are committed; U11A–E are verified in selected scope, with U11H final acceptance pending. |
| Verification | U11E latest selected affected verification: 480 passed, no skipped/xfail; two accepted provenance REDs remain separate known results. This is not full lifecycle or full-project GREEN acceptance. |
| Integration | Explicit summary composition, prepared-plan handoff, point-local Module/Script discovery and per-point failure isolation are implemented; S1–S4 acceptance is recorded in [Summary Scripts acceptance](#summary-scripts-acceptance); conversation, Agent, LLM, tool, memory, and skill lifecycle integrations remain deferred. |

In scope now: the independent framework, its execution guarantees, interfaces, configuration, lifecycle, extension seams, current implementation status, and verification plan. Possible future integration families are conversation, User2Agent turns, Agent2LLM runs, LLM requests, prompt assembly, context summarization, persistence checkpoints, and task lifecycle.

Explicitly out of scope for the current implementation: all tool-specific hooks under tools/, tool invocation and approval integrations, memory hooks, skill hooks, compatibility adapters, migration of existing TOPSAILAI_HOOK_* implementations, and insertion of additional Hook points into application owners beyond the implemented summary path. Existing mechanisms remain untouched. The implemented foundation introduces no environment variable. The framework-readiness extension below implements environment-driven bootstrap and insertion APIs; its variables are synchronized to `env_template` and `docs/Environment_Variables.md`.

## Authoritative Hook Point contract

Human clarified that every Hook point has a built-in/default Hook to identify and execute Scripts; Modules execute first, then Scripts, with both stages ordered by name, and every Module exposes `main(*args, **kwargs)` as its entry. This is an English rendering of the Human statements; the normalized keys below are the documented deterministic interpretation, not additional verbatim quotes.

A **Hook Point** is a named extension location. A **Module Hook** is a plugin registered at that location. Each Hook Point has **0..N Module Hooks plus exactly one framework-owned built-in/default terminal Script Hook**, reserved as `hook_script`. This is one unified framework and one Hook-point execution plan, not two peer registration/dispatch models.

- Public plugin registration supports Modules only. Every Module exposes callable `main(*args, **kwargs)` as its execution entry. The framework binds detached, validated arguments through its isolated worker protocol; internal context/envelope adapters do not replace `main` with a required public `handle(context)` entry.
- Framework initialization of a Hook Point automatically supplies its one default `hook_script`, even with zero Modules or zero Scripts. It cannot be replaced, renamed, duplicated, removed, or reordered by plugins; it consumes one real binding-capacity slot. No Scripts means a successful zero-entry no-op, not absence of the default Hook.
- Modules execute sequentially in ascending module-name order. After all predecessors reach the required terminal and cleanup-safe state, the default Hook identifies the point's configured Scripts and executes them sequentially in ascending script-name order. Settled Module failure does not itself prevent Scripts; unresolved cleanup, host cancellation, or exhausted aggregate deadline does prevent unsafe continuation.
- Script files are internal entries of this default Hook, not peer Hooks, one Binding per script, or an independently dispatchable scripts-only plan. A result merely labelled `binding_id="hook_script"` does not satisfy the contract unless the default Hook is actually in the unified plan.
- `hook_name` plus `scripts` or `folder` configures the default Hook. Explicit lists select members, not execution order. Startup/lazy registration, decorators, and function-body calls are convenience wrappers and must preserve the same unified plan and lifecycle.

### Configurable local and external resources

**Revision note:** trust admission and explicit-only bundled activation below are superseded for the generic-entry target by [Human revision](#human-revision-and-accepted-generic-entry-prototype); retained prepared/summary paths keep their existing behavior.

**Human requirement (2026-10-15):** “把这个要求明确地写到设计文档里面，这个要求不仅用在scripts,同样也适用于modules。 scripts/modules 不仅仅是 point 文件夹里面的系统自带，也可以外部扩展”. Configuration determines which resources execute; adding a point must not require Hook-specific parameters, constructor fields or call-chain plumbing in the original function/class. Use an exact-position unified dispatch/access call or a decorator at a true function boundary; see [Layering and ownership](#layering-and-ownership).

Both Module and Script resources may be system-provided resources conventionally organized under a point's local `modules/` and `scripts/`, or deployment-authorized external extension files/folders outside the point tree. Local folders are organizational defaults, not exclusive sources; mere placement does not register, authorize or activate anything. No resource is implicitly enabled merely because it is bundled with the application.

Local and external resources share deployment trust and security admission, bounded discovery, immutable capture, duplicate final-name rejection, deterministic ordering, aggregate deadlines, cancellation, lifecycle ownership, cleanup-debt accounting and last-known-good replacement guarantees. External Modules still expose `main(*args, **kwargs)` and run first; external Scripts remain entries of the exactly one terminal `hook_script`, never peer Hooks or a separate dispatcher. No inline import/execution shortcut or trust exemption is permitted.

### Deterministic name keys

Sorting is case-sensitive ascending Unicode code-point order, without locale collation, case folding, numeric/natural sorting, or Unicode normalization. Both Module and Script keys are their final registered name strings, not binding priorities or list positions. Duplicate registered names within the same handler kind and Hook Point reject the complete candidate before publication. Module discovery enumerates eligible direct children by suffix (`.py` plus the platform `importlib.machinery.EXTENSION_SUFFIXES`) and then probes and executes them through the import system; it can derive a logical import name using the complete interpreter-recognized suffix, but the final registered name is the ordering authority.

Script names have no framework-imposed format restriction: no required prefix, extension or basename-only rule. Executability, trust and path admission are separate safety checks, not naming restrictions. No case folding or name normalization changes the sorting key. Explicit lists select entries only; neither list position nor path is a tie-break for duplicate registered names. For directory discovery, generating a normalized root-relative path as the registered name is a proposed default to distinguish files in different subdirectories; the Human has not explicitly approved that generation rule. Display the generated names before publication rather than silently treating basename as authority.

For both local and external Modules and Scripts, explicit lists select resources, never execution order. Folder selections discover eligible resources under declared finite depth/count/byte and admission rules, then sort by final registered name. Filename order applies where the admitted name is the filename; nested external basename versus root-relative name generation remains an unresolved policy decision, not approval for recursive Module discovery or silent name normalization. Duplicate names reject the complete candidate rather than using paths or list position as tie-breaks.

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
| Isolation boundary | In the retained generic framework, plugins are imported and executed only in managed child processes. The supported `point_entry` direct-entry path instead imports and invokes Modules in the current process and runs only Scripts as subprocesses. |
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
| hooks/module_discovery.py and hooks/module_discovery_worker.py | Implemented direct-child discovery and isolated import/callable-main validation for both Python source and compiled extension modules |
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

Legacy event declarations may use dot-separated namespaces such as conversation.started. New unified Hook points use `hook__<module>__<before|after|error>__<business_action>`, with identical point and event names from one NAME constant; see [Naming, Phases, and Framework Validation](#naming-phases-and-framework-validation) for phase mapping and implemented strict new-name validation. Legacy independent point/event names remain compatible. Schema major version is a separate integer; incompatible changes require a new major version. For SummarySnapshot, event major version and snapshot schema version MUST remain equal; see [Data Contract](#data-contract) for the phase-one equality and evolution rules. Initial matching is exact name plus major version, without wildcards or arbitrary filter callbacks. Category labels may be metadata but never choose a different execution engine.

Sequence is monotonically increasing per scope under the owner lock; it records publication order, not completion order. IDs are correlation data, not credentials or authorization. Payload schema definitions are bounded declarative schemas, not custom application callbacks invoked during core validation.

## Unified handler and public interfaces

The target Module entry is enforced by unified source capture/execution; generic Binding validation remains a legacy contract. This compact sketch is not an exact call signature reference. `HookScheduler` is implemented as a module-level API and is not currently a package-level export.

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

The standalone HookScript orchestration interfaces `HookScriptExecutionOptions`, `HookScriptExecutionPolicy`, `HookScriptEntryResult`, `HookScriptRunner`, and `execute_configured_hook_script` are implemented. `HookScriptRunner` is an injected trusted runner protocol. The simplified configured Runtime facade is also implemented through `register_configured()`, `dispatch_configured()`, `adispatch_configured()`; application-domain lifecycle integrations beyond the explicitly adopted summary path remain deferred.

Every public Module uses `main(*args, **kwargs)` with arbitrary arguments and arbitrary return content; the framework, not the Module, constructs the result envelope. The existing low-level worker context convention requires an adapter where necessary; it is not permission for an arbitrary public callable entry. `None`, `False`, zero, empty containers and `{"error": 1}` are normal return values, not framework errors. Values are not required to be JSON-serializable. The framework does not interpret any of them as a veto, replacement, success marker, or request to retry. Execution success is represented by outcome.status, independently of outcome.value.

Host-side admission, serialization, configuration, queue, and backend errors return diagnostic statuses. Programmer-facing registration can expose detailed validation errors through RegistrationResult without raising through normal runtime emission. Genuine host cancellation and interrupts remain host control flow, not successful empty reports.

Implemented `HookStatus` values include: success, error, timeout, invalid_output, worker_lost, cancelled, skipped_dependency, skipped_disabled, skipped_deadline, rejected_capacity. A rejected event yields an explicit receipt/report reason rather than pretending that no handlers matched. No matching bindings yields a successful empty dispatch.

Reports and diagnostics remain bounded. Dispatch owns its short-lived report. Non-waiting admission, background handles and result polling are not part of the target API; U10 removed emission APIs and receipts without aliases or background substitutes.

## Registration, discovery and configuration

**Revision note:** manifest-based registration below describes the retained framework, not a prerequisite for the accepted auto-loading generic input entry; see [Human revision](#human-revision-and-accepted-generic-entry-prototype).

Use an explicit manifest or typed API registration. Target Module handler references identify importable `module:main` entries; the explicitly legacy generic Binding API still accepts arbitrary `module:callable` references and is not the ordinary target registration contract. Closures, live instances, lambdas, and implicitly inherited thread-local agents are not supported. Configuration parsing must not import plugin modules.

The application reads a chosen config source once and passes settings to HookRuntime. `HookSettings.from_mapping()` accepts runtime settings (`schema_version`, `enabled`, and `limits`); definitions and bindings are registered through the typed API rather than embedded in that mapping. No new environment-variable family is prescribed. Configured module/script discovery is explicit and rooted at caller-supplied paths; there is no implicit crawling of the working directory, installed packages, or arbitrary search paths.

Target source selection is symmetrical for both handler kinds: a single external file, an explicit list of files, or a configured folder of eligible resources. A single file is a one-member selection. Local defaults are selected through the same trusted preparation path. Exact schema keys, combination/override rules for local and external selections, and external nested discovery/name generation must be specified before implementation; this target does not introduce an already accepted JSON schema. Modules need callable-main admission, while Scripts need platform executable/format admission; symmetry of configuration does not erase those distinct safety checks.

**Current implementation boundary:** the generic environment bootstrap/configuration principally exposes Script `scripts` or `folder`. The selected-resource preparation path and summary prepared-plan handoff now provide committed Module/Script resource preparation, including explicit selected resources, but they do not constitute the complete external Module file/list/folder bootstrap contract. Reuse that handoff rather than claiming it is absent; extending it to symmetrical configurable external sources remains work. Evidence: `884c5140` (`hooks/configured_contracts.py`, `hooks/configured_preparation.py`, `hooks/configured_resource_contracts.py`, `hooks/configured_resource_preparation.py`, `hooks/configured_resource_sources.py`).

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

The implemented U07 path validates a configuration candidate as a whole. Initial invalid configuration leaves the affected Hook Point unavailable with diagnostics; business blocking follows only Catalog-authorized policy. Invalid reload rejects the new revision and retains the last known good active plan for new admissions, explicitly reporting desired_revision, active_revision, update_failed and safe diagnostics. A successful reload atomically publishes an immutable new generation. An in-flight dispatch retains its captured generation. Explicit unregister affects new admissions only; scope close also cancels outstanding deliveries.

## Ordering, dependencies and concurrency

For matching bindings, resolve a directed acyclic graph. after specifies completion-before-start, regardless of predecessor success. requires_success additionally skips the dependent if the predecessor did not succeed; it implies an ordering edge. Targets must exist within the same event/version and effective scope snapshot. Cross-event dependencies and hidden lookups into previous reports are unsupported.

Reject cycles and unknown references before activation. The required Hook-point plan compiles Modules into a strict logical-name chain and appends the default `hook_script` after every Module; priority, caller dependencies, and registration order cannot override that order. The current generic Registry selects ready nodes by ascending priority then binding ID; this is an internal low-level behavior, not the target public Hook-point ordering contract.

Within a Hook Point, Modules and Script entries are sequential and name-ordered; parallel execution within either stage is not part of this contract. Separate deliveries may use bounded Runtime concurrency without changing the order inside a captured plan. Reports are always ordered by the stable topological plan, not completion timing. A failing independent handler never suppresses later independent handlers. Dependency skips and deadline exhaustion are intentional exceptions to execution, not propagation of a plugin error.

Per-binding max_concurrency defaults to one across an owning runtime. Ready deliveries for that binding use admission order. Cross-binding completion order and cross-process global ordering are not guaranteed. No dispatch holds a registry or application lock while waiting for a handler. Registration changes inside application code affect only future snapshots; workers do not receive registration authority.

Worker parallelism is bounded at runtime level, not multiplied without limit per scope. Sequential dispatch does not imply a stateful plugin singleton: initial workers use one delivery per process, preventing module globals leaking across calls. Worker reuse is a later optimization requiring an explicit reset/isolation contract and evidence; it must not silently weaken the initial guarantee.

## Dispatch algorithm and deadlines

The target requires dispatch and awaited adispatch to use this unified algorithm and logically wait for completion. U06 synchronous and U08 awaited configured paths execute the same immutable plan under one absolute budget; cancellation propagates while exact cleanup custody is retained. U10 removes nonwaiting emission without aliases. Fire-and-observe is outside the target.

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

Keep reserved worker capacity for processes not yet confirmed dead. If termination cannot be confirmed, quarantine the slot, retain an explicit cleanup-debt record and stop spawning beyond the resource cap. The main flow continues; diagnostics must not falsely report successful cleanup. Unsupported platform containment or an unavailable validated worker launcher rejects delivery instead of executing inline. Packaged/Cython worker launchers must be validated; do not assume the current executable is a Python interpreter. This launcher concern is distinct from Module admission, which accepts Python source and compiled extension modules as described above.

Runtime lifecycle: created → running → closing → closed. Scope lifecycle follows its owner's actual lifetime. Conversation scope survives multiple user turns; run scope closes after one Agent2LLM run. Closing a child never closes its parent or siblings. The approved summarize application instead shares application-lifetime resources across AgentChats/sessions; its [composition and shutdown decisions](#integration-and-division-of-responsibilities-with-existing-mechanisms) do not let a session close the shared Runtime.

Shutdown stops new business emissions, optionally admits a reserved bounded terminal notification, cancels queued work, allows a finite drain, and stops owned workers. Required application teardown runs independently of plugin completion. close is idempotent and returns pending cleanup debt instead of waiting forever. No atexit callback may introduce an unbounded wait or re-open a closed diagnostics sink.

Host cancellation of adispatch cancels its pending deliveries and propagates the genuine host cancellation. A plugin raising CancelledError, KeyboardInterrupt, SystemExit, HeavyTaskError, or another domain exception in its worker yields an error outcome only. Distinguish exception origin structurally, not by swallowing every BaseException around a business operation.

## Payload and result semantics

Payloads are detached snapshots, not references to mutable agent state. The summarize application freezes a narrower metadata-only, versioned SummarySnapshot v1 with point-specific allowlists; see its [Data Contract](#data-contract). Default data is metadata: identifiers, counts, stage, outcome and elapsed time. Message content and sensitive application data require explicit domain opt-in and binding field allowlists. Credential values, live database/model objects, locks, runtime handles and executable objects are prohibited.

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

Human selected Option A for failed configuration updates (retain the last known good plan) and Option A for fire-and-observe (do not implement it). A build failure means a candidate cannot pass discovery/validation/capture (for example a newly added Module lacks callable main or a configured Script cannot be read), not a failure during an already admitted handler execution.

If valid v1 is active and desired v2 fails, reject and clean v2, keep v1 active for new calls, and report desired_revision=v2, active_revision=v1, state=update_failed_using_last_known_good with bounded safe diagnostics. Do not report v2 as activated or retry it on every call. Initial failure without any prior valid plan makes the Hook Point unavailable; only authorized policy decides whether business is blocked. Successful replacement publishes the complete candidate atomically; old admitted executions keep their old snapshot until leases and cleanup are settled. Startup and lazy wrappers use this same state machine and singleflight publication, not separate Script-only paths.

### Result transformation as an extension

Transformation is optional orchestration above the unified engine, not a second kind of hook. A domain-owned ResultPolicy defines allowed proposals, validation, deterministic reduction, and application. It cannot override core isolation, deadlines or resource limits.

Recommended first form: all handlers receive the same base snapshot and return JSON proposals. The caller processes successful values in stable registry order, validates each against its domain schema and invariants, and constructs a new candidate. A rejected proposal preserves the last valid candidate. The caller applies the final candidate once, only if its source revision and scope are still current. Existing required validation still runs afterward.

Example: a prompt extension accepts only an append-fragments proposal. It cannot replace trusted system instructions or rewrite roles. The framework sees ordinary JSON output; only the prompt owner knows the append contract.

If a use case truly needs sequential transformations where handler B sees handler A's result, add a Pipeline extension. It captures one binding plan, invokes the same dispatcher worker primitive for each binding once, and uses one absolute deadline across the chain. It must not re-dispatch all subscriptions at every stage or create a second registry. A failed stage keeps the last accepted candidate. This extension is deferred until a concrete use case justifies the additional complexity.

Reducers and validators executing in the host are trusted bounded application code, not dynamically loaded plugins. Catch their ordinary failures locally and preserve original data. An arbitrary plugin-provided reducer must instead execute as another isolated handler through the same protocol. No feature may reintroduce unbounded user code in the host through a custom result policy.

## Illustrative API usage

Lifecycle publication and optional result consumption use identical registrations and handlers. These are interface sketches, not an implementation prescription. The business-side constructor name assumes `HookRuntime` is imported as `Hook__HookRuntime`, following the mandatory aliases in [Layering and ownership](#layering-and-ownership).

```text
runtime = Hook__HookRuntime(
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
| Summarize lifecycle: `hook__context__before__summary_generate_user2agent` / `hook__context__before__summary_generate_agent2llm`, layer-specific after-apply and generation/application error points | workspace/context/agent2llm.py and workspace/context/ctx_runtime.py, respective summarize methods; shared generation in workspace/context/base.py | Exact checkpoints and minimal v1 metadata in [Summarize Hooks Application](#summarize-hooks-application); generation-success observation is a phase-two candidate. | Generated does not imply applied or persisted; replaces the earlier illustrative context.summary.started / finished names for this application, not a legacy migration. |
| session.messages.changed | context/ctx_manager.py, add_session_message / del_session_messages | After facade result. IDs/counts and partial-backend outcome. | Notification only; no claim of transaction atomicity. |
| task.started / finished | workspace/task/task_tool.py, ctxm_process_task | After admission; after owned settlement attempts. Task ID, result and cleanup status. | Hook success never marks task done. |

User2Agent messages are persistent user/session data. Agent2LLM messages are ephemeral execution context. Never automatically insert hook events or failures into either history. The envelope carries layer and purpose, including summary or background work, rather than conflating every model request with a user turn. No tool, memory or skill integration is included in this catalog or rollout.

## Summarize Hooks Application

This chapter integrates the approved summarize design into the framework specification. Its naming rules govern new unified points; its business checkpoints, metadata contract, activation choices, and application owner specialize the generic framework without claiming implementation readiness.

### Historical prepared file-membership baseline

**Superseded business wiring:** U1–U3 migrated Summary to direct named entries and removed both workspace owners. This section records the earlier deployment-authorized/restart baseline and its evidence, not the current activation procedure. The old production builder mentioned here no longer exists; retained library tests use a test-only helper. Current `{}` activation and per-invocation discovery are specified above.

Human goal: “我要达到的效果是 增减modules 只需要 增减对应的 代码文件 就行。” Human confirmed baseline A: “A:只增减文件 + 部署授权更新 + 应用重启生效；” This is restart-based membership activation, not hot reload or implicit trust.

Units 1–6 implement valid zero-resource plans, generic detached worker context, caller-owned Catalog selection, point-name-derived envelope layer, point-local Module directories and offline deployment authorization. The former `workspace/summary_hooks_owner.py::build_summary_preparation_request()` (now deleted) binds the eight phase-one points to their own `modules/` directories without listing members. Each point's `observer.py` delegates to the shared observer through `main(*, hook_context)`. The two phase-two points remain inactive. Applications must explicitly adopt this builder; ordinary AgentChat construction does not silently enable Hooks.

`hooks/deployment_authorization.py` enumerates configured directories offline, requires an explicitly reviewed deployment closure digest and Python Runtime authority, and emits the existing v1 manifest plus its pin. It never imports candidates or certifies dependency review. Regenerate on the frozen target deployment tree, publish authority/pin and restart before new membership is prepared. Missing/stale authority rejects the complete affected point; valid empty directories retain the unique terminal `hook_script`. Scripts are not generated or merged by this Module-only entry. [The API deployment guide](../docs/Hooks_API.md#point-local-summary-module-deployment) records options, target-runtime restrictions and explicit composition requirements.

Unit 7 focused acceptance covers real worker execution after owner-lifetime restart, unchanged directory requests, sibling isolation, add/remove/last-member behavior, immutable prior snapshots and unavailable-point zero side effects. It does not establish full CLI process restart, BDD, full-project or cross-platform acceptance, or supersede pending framework gates.

Human confirmed on 2026-10-14: “modules的实现是符合预期的，请更新设计文档。然后开始计划 scripts 的实现，并实施它”. The accepted Module workflow is file membership plus deployment authorization update plus application restart, not automatic trust or hot reload.

Discovery is explicitly driven by `ConfiguredHookPoint.module_folder`: direct children only, excluding `__init__.py`, without nested-directory crawling. Python source Modules and compiled extension Modules both expose a plain `main(*args, **kwargs)` function; the existing probe also accepts an exact built-in C function, not arbitrary callable objects. Summary binds `main(*, hook_context)` to detached metadata. Captured sources are probed in isolated workers, published through the prepared Registrar and executed in registered-name order before the one default terminal Script Hook. Adding a member to an existing point requires no import table, Catalog member list or business-trigger edit.

The actual eight phase-one directories contain `point.py`, `payloads.py`, `__init__.py` and `modules/observer.py`; `summary_events_observer/observer.py` supplies shared observation logic. The two phase-two declarations remain inactive. Optional `scripts/` directories are supported by S3, not populated with placeholder resources. `build_summary_preparation_request(..., script_platform_policy=None)` preserves Module-only composition; an explicit POSIX shebang-only `ExecutablePlatformPolicy` selects the eight point-local Script paths without listing member files. Native suffixes are rejected by this summary builder.

S1 implements bounded zero-or-more prepared Script entries, complete capture/plan correlation and individual final child names. S2 adds the separate offline mixed-authority generator in `hooks/deployment_script_authorization.py`; the Module-only generator above remains unchanged. S3 wires optional directories into the same prepared Registrar/Runtime path. S4 verifies composed business behavior from committed tree `a4516f5f3f53cbf712f403322211b3650e043c48`; see [Summary Scripts acceptance](#summary-scripts-acceptance) and [the Script deployment API](../docs/Hooks_API.md#point-local-summary-script-deployment). Membership changes require frozen-source review, offline authorization refresh and application restart, never runtime trust generation or hot reload.

This synchronization does not authorize native acquisition implementation/build/activation, open any of the seven P2 gates, mutate `cleanup_profile`, resolve operational P3/P4/P5 or C2/C3/C4 custody work, or release child capability STOP. C3 containment remains separate; full-project acceptance remains NOT GREEN.

### Goals and Decision Background

Human requested: “Execution boundaries should use before/after or pre/post; Hook point code should be managed centrally in a dedicated folder under hooks, grouped by module.” “Clarify the rules as much as possible and save them in a features/design document.” Human later requested: “Put layer inside business_action.” Human then confirmed: “Hook point names should align with event names to avoid two standards and use a single naming convention. Modules should have their own subdirectories under each Hook point for clear, intuitive management.” Approval: “I agree, update doc.” For “Where do scripts go?”, see the directory section for placement and loading rules.

This application chapter governs new unified Hook points, using summarize as the concrete integration. The implemented file-membership baseline records the separately approved work; the remaining design text does not authorize additional implementation, migration of existing interfaces, or commits. The preceding framework sections remain authoritative for generic execution, registration, trust, and resource guarantees; this chapter specifies the application decisions and pending extensions.

Existing `pre_run_input.py`, `pre_run_agent2llm_source.py`, and `post_final_answer.py` under `workspace/agent/hooks/`, `hook_before_chat/` and `hook_after_chat/` under `ai_base/llm_hooks/`, and `hooks_pre_chat`, `hook_after_init_prompt`, `hook_after_new_session`, etc. retain their names. Public methods, environment variables, plugin imports, and discovery rules are not renamed incidentally in this task.

### Naming, Phases, and Framework Validation

New points use `hook__<module>__<before|after|error>__<business_action>`: four lowercase segments separated by `__`, with words within the action separated by `_`. For summarize points, business_action embeds the layer as `<action>_<layer>`: `summary_generate_user2agent`, `summary_generate_agent2llm`, `summary_apply_user2agent`, or `summary_apply_agent2llm`. The layer suffix is part of the fourth segment, not a fifth `__` segment; each layer has its own declaration and point plan. Human requested that layer be placed inside business_action. SummarySnapshot has no separate layer field; derive layer only from the validated point name. The module is a stable business domain matching `hooks/points/<module>/` and containing no separators; summarize uses `context`, not a class name, caller, or full Python import path. This is an external string, not a function identifier; use before/after without introducing mixed pre/post terminology. Names must remain unique within the Catalog; the module provides neither permission nor namespace isolation.

**For new declarations, `HookPointDeclaration.name == EventDefinition.name`; both use the same `NAME` constant, without separate dot-separated event names or aliases.**

| Name phase | Framework phase | Business semantics |
|---|---|---|
| before | before | Required validation and preparation are complete and the action is about to execute; not a condition query |
| after | success | The action completed successfully; not finally |
| error | error | Observation of an action failure; does not authorize recovery, retries, or exception replacement |

Names must identify the action: do not use `after_summary` to conflate generation with application. `HookPointDeclaration.phase` and the `hook_point` decorator continue to use before/success/error; no after parameter is added.

The Executor uses `point.name` for Catalog, registration, and configuration lookup, and `point.definition.name` to create events. New-format declarations now enforce equality and phase consistency in `hooks/hook_point_catalog.py`; legacy declarations retain their compatibility rules. Implemented validation:

- `hooks/configured_contracts.py` retains the legacy `_HOOK_NAME` branch and adds `_UNIFIED_HOOK_NAME` with strict four-segment validation and the 128-character limit. New `hook__` names use the strict branch, never the legacy fallback.
- The event-name regex in `hooks/validation.py`, `^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*$`, already permits zero dot-separated suffixes and underscores within segments, accepts the new names, and needs no change.
- New-format declarations validate name equality and phase consistency with the table above; legacy `hook_*` declarations may retain independent point and event names. Do not silently rename existing configuration, bindings, or consumers; migration requires a separate compatibility plan and regression verification.

### Directories, Responsibilities, and Execution Protocols

**Revision note:** the adapter-only business entry and trusted source selection below remain legacy summary-path descriptions. The generic input target uses a named point directly and executable-permission-only Scripts; see [Human revision](#human-revision-and-accepted-generic-entry-prototype).

Use Option B: an independent subdirectory per point. The following layout is relative to ProjectFolder. Point declarations and phase-one Module directories are implemented; scripts directories are optional and are not created without resources:

```text
hooks/points/
├── __init__.py
├── context/
│   ├── __init__.py
│   ├── summary_contracts.py
│   ├── summary_payloads.py
│   ├── summary_adapter.py
│   ├── before_summary_generate_user2agent/
│   │   ├── __init__.py
│   │   ├── point.py
│   │   ├── payloads.py
│   │   ├── modules/                  # Optional
│   │   │   └── observer.py
│   │   └── scripts/                  # Optional, none currently present
│   │       └── audit.py
│   ├── before_summary_generate_agent2llm/
│   ├── after_summary_generate_user2agent/  # Phase-two candidate
│   ├── after_summary_generate_agent2llm/   # Phase-two candidate
│   ├── after_summary_apply_user2agent/
│   ├── after_summary_apply_agent2llm/
│   ├── error_summary_generate_user2agent/
│   ├── error_summary_generate_agent2llm/
│   ├── error_summary_apply_user2agent/
│   ├── error_summary_apply_agent2llm/
│   └── summary_events_observer/
│       ├── __init__.py
│       └── observer.py
└── workspace/
    └── before_input_message/
        ├── __init__.py
        └── point.py
```

Other points use the same structure as the expanded point; do not create empty modules/scripts directories or placeholder execution modules without actual execution resources. Subdirectory names are path representations omitting the fixed prefix and parent domain, not event aliases.

| Location | Sole responsibility |
|---|---|
| Existing framework files in `hooks/` | Generic Runtime, Registrar, Executor, and Catalog |
| `tests/summary_catalog_support.py` | Explicit legacy test composition of phase scope; no production package-level aggregate |
| `context/summary_contracts.py` | Shared versioned schema, snapshot types, field boundaries, and security constraints |
| `context/summary_payloads.py` | Shared bounded, sanitized payload construction detached from business objects |
| `context/summary_adapter.py` | Shared operation, dispatch, and report checks; begin()/emit() span the operation |
| `<point>/point.py` | Single-point NAME, EventDefinition, and HookPointDeclaration |
| `<point>/payloads.py` | Point-specific field/state validation reusing the shared builder |
| `<point>/modules/` | Point-specific configured Python Module with a main(...) entry point |
| `<point>/scripts/` | Point-specific separate-process Script |

Execution sources are specified by trusted configuration: Modules use `ConfiguredHookPoint.module_folder`; prepared Scripts use `ConfiguredScript.target`. The summary builder selects optional point-local `scripts/` paths only when `script_platform_policy` is explicitly supplied; disabled points are not prepared. An absent optional directory means no Script source, while an existing empty directory yields a successful zero-child terminal. An explicitly configured missing/unreadable target fails closed. Broken symlinks and access failures are not absence; selection grants no authority and preparation revalidates the target.

Prepared Script directories use bounded direct-child membership; ordinary subdirectories are not traversed. Invalid/nonexecutable/unreadable files, symlinks, special files, duplicate final names or canonical identities, and unauthorized sources reject the complete affected point, never a partial plan. Final Script names are exact filenames including extensions, ordered by case-sensitive Unicode code points. Modules run first, then exactly one terminal `hook_script` containing separately named Script children; no per-Script registry binding or second engine is introduced. Discovery/capture retain aggregate bounds and deadlines, including the combined 128-entry executable-plan limit and cleanup-safe successor barriers.

The unchanged generic `ConfiguredHookBinding.scripts`/`folder` API is separate: `folder` remains recursively scanned and mutually exclusive with explicit `scripts`. Placement alone implies neither registration nor authority. Target the Script resource directory, not the entire point directory; do not confuse generic recursive discovery with prepared summary direct-child membership.

Reference cross-point shared resources from a shared location through configuration rather than duplicating them. Top-level `scripts/` conventionally holds standalone tools/operational scripts; an eligible file there or outside the point tree may also be explicitly selected as an external Hook resource under deployment trust. Point-local `modules/` and `scripts/` are not exclusive resource locations and do not imply automatic discovery or registration. The direct-child summary membership rules above describe the current implementation, not a prohibition on future authorized external sources. Legacy generic Binding observers using `handler(context)` (Binding.handler_ref), configured Modules using `main(*args, **kwargs)`, and the Script protocol are not interchangeable. The ordinary target registration contract remains Module `main`, as defined in [Registration, discovery and configuration](#registration-discovery-and-configuration).

Each point retains the [Authoritative Hook Point contract](#authoritative-hook-point-contract), including its single built-in terminal `hook_script`, Module-before-Script name ordering, and cleanup-safe prerequisites. Business resources must not replace, duplicate, or bypass that unified plan; no scripts-only dispatch chain is added.

Dependency and import boundaries:

- Business code calls only the adapter, which references point declarations. Declarations and payload builders must not import business classes such as ContextRuntime, AgentChat, or LLM models in the reverse direction, or obtain state through a hidden global agent.
- The framework core does not import business modules; Catalog aggregation is performed explicitly by application composition. Module top levels must not create a Runtime, scan handlers, register resources, or invoke business code, avoiding side effects and circular dependencies.
- Catalog declarations are only one link in the authorization chain; trusted bootstrap, Registrar, Runtime validation, and resource governance are still required. Legacy HOOKS and pre_run/post_final_answer prefix discovery do not scan the new points subtree.
- Centralize declarations, contracts, payloads, and adaptation; precise trigger sites remain in business code. Do not move generation, human confirmation, persistence, or message reconstruction into Hooks.

#### Essential Examples

Single-point `before_summary_generate_user2agent/point.py` (requires the point-name validation extension first):

```python
from topsailai.hooks.contracts import EventDefinition
from topsailai.hooks.hook_point_catalog import HookPointDeclaration
from topsailai.hooks.points.context.summary_contracts import SUMMARY_SCHEMA

NAME = "hook__context__before__summary_generate_user2agent"
POINT = HookPointDeclaration(
    name=NAME,
    definition=EventDefinition(
        name=NAME, major_version=1,
        payload_schema=SUMMARY_SCHEMA, payload_limit_bytes=8192,
    ),
    phase="before", mode="sync", owner="context.summary",
    failure_policy="report",
)
```

Other points reuse this structure, changing the name, phase, and point-specific schema restrictions as specified in the next section. The shared builder handles all fields, unknown values, and budgets; `after_summary_apply_user2agent/payloads.py` adds only point-specific validation:

```python
from topsailai.hooks.points.context.summary_payloads import build_summary_payload


def build_payload(snapshot):
    """Require completed application before publishing success."""
    if snapshot.outcome != "success":
        raise ValueError("after_apply requires an applied summary")
    return build_summary_payload(snapshot)
```

Example `before_summary_generate_user2agent/modules/observer.py`, with parameters explicitly mapped through trusted configuration:

```python
import logging

logger = logging.getLogger(__name__)


def main(operation_id, point_name):
    """Observe validated scalar metadata without mutating history."""
    logger.info("Summary generation: operation=%s point=%s", operation_id, point_name)
    return {"observed": True}
```

The production `hooks.points` package no longer imports or exports a Summary Catalog aggregate. Direct entries invoke the individual points without Catalog composition. Retained prepared tests explicitly compose `HookPointCatalog` in `tests/summary_catalog_support.py`: the first-phase set contains eight declarations (BEFORE_GENERATE, AFTER_APPLY, ERROR_GENERATE, and ERROR_APPLY for each layer), while the second-phase set contains only the two AFTER_GENERATE declarations and remains excluded from that test Catalog. This test composition neither creates a Runtime nor registers modules; the generic Catalog library is retained.

### Summarize Points and Lifecycle

Current synchronous generation entry points are `workspace/context/base.py::_summarize_messages()` / `_summarize_runtime_messages()`; the two layer entry points are `workspace/context/ctx_runtime.py::summarize_messages_for_processed()` and `workspace/context/agent2llm.py::summarize_messages_for_processing()`. `workspace/agent/agent_chat_base.py::hook_summarize_messages()` evaluates triggering conditions.

| Name (point and event) | phase | Exact checkpoint | Scope |
|---|---|---|---|
| hook__context__before__summary_generate_user2agent | before | After feasibility checks pass and the prompt and actual model are determined, before the LLM request | Phase one |
| hook__context__before__summary_generate_agent2llm | before | After feasibility checks pass and the prompt and actual model are determined, before the LLM request | Phase one |
| hook__context__after__summary_generate_user2agent | success | After a valid nonempty summary is generated, before human confirmation/application | Phase-two candidate, inactive |
| hook__context__after__summary_generate_agent2llm | success | After a valid nonempty summary is generated, before human confirmation/application | Phase-two candidate, inactive |
| hook__context__after__summary_apply_user2agent | success | After the named layer completes application | Phase one |
| hook__context__after__summary_apply_agent2llm | success | After the named layer completes application | Phase one |
| hook__context__error__summary_generate_user2agent | error | Generation-stage exception in the named layer | Phase one |
| hook__context__error__summary_generate_agent2llm | error | Generation-stage exception in the named layer | Phase one |
| hook__context__error__summary_apply_user2agent | error | Application-stage exception in the named layer | Phase one |
| hook__context__error__summary_apply_agent2llm | error | Application-stage exception in the named layer | Phase one |

There are ten definitions, eight active in phase one and two phase-two candidates. The adapter selects checkpoints for the operation's named layer; it must never dispatch the other layer's counterpart. The normal sequence within that layer is before_generate → optional after_generate → after_apply. Generation failure emits neither after point; application failure emits no after_apply. Each actual checkpoint notifies at most once per operation; report-type Hook failures must not be misrepresented as business failures.

**generated ≠ applied**: User2Agent may wait for human acceptance, then write the session, delete compressed history, and reload; without a session, it updates memory. Agent2LLM updates runtime messages and required token statistics. Application success is notified only after all these steps succeed in the corresponding layer. Empty input, feasibility rejection, a locally returned empty summary, and human nonacceptance are normal skips, not applied results or errors. Real empty-provider output follows the distinct retry-exhaustion generation-error path described in [Summary Scripts acceptance](#summary-scripts-acceptance).

Writes, deletions, and reloads are not a single transaction, so failures may leave partial application. Report that state accurately; adding Hooks provides no transaction, retry, or automatic rollback. Do not execute plugins in `is_need_summarize_*()` query functions.

### Data Contract

**DECIDED — Human approved the phase-one SummarySnapshot v1 rules and boundary.** The snapshot is serializable, metadata-only, validated, and detached from business objects. It includes no summary content, raw messages, live Python objects, full tracebacks, credentials, or secrets. Unknown/unregistered fields are rejected by the framework, never silently passed through. Apply the generic [Payload and result semantics](#payload-and-result-semantics) with these stricter application boundaries. Each point receives only fields appropriate to its lifecycle stage; before points cannot see application results, and error points receive limited error classification rather than raw exception text.

| Field set | Approved field names and stage boundary |
|---|---|
| Common | `schema_version`, `operation_id`, `point_name`, `outcome`; one summary shares a HookOperation, with separate checkpoint dispatches |
| Error points only | `error_category`, `failed_stage`; bounded classification, not exception objects, messages, or traceback text |
| Application-error point only | `partial_apply_possible`; report possible partial application without claiming rollback |


Layer is derived authoritatively from the validated point-name suffix; a separate `layer` payload key is prohibited and rejected as an unknown field, including null or a matching value. Any existing generic HookEvent envelope layer metadata must be derived from and agree with that name, never independently selected. This does not remove generic envelope fields or change generic event contracts.

The following revised precise v1 field table is a PROPOSAL awaiting Human confirmation, not a frozen executable schema. Codes use U for user2agent and A for agent2llm. All string lengths are character counts.

| Code | Point name | Outcome | Activation |
|---|---|---|---|
| BG-U | hook__context__before__summary_generate_user2agent | before | Phase one |
| BG-A | hook__context__before__summary_generate_agent2llm | before | Phase one |
| AG-U | hook__context__after__summary_generate_user2agent | success | Phase-two candidate, inactive |
| AG-A | hook__context__after__summary_generate_agent2llm | success | Phase-two candidate, inactive |
| AA-U | hook__context__after__summary_apply_user2agent | success | Phase one |
| AA-A | hook__context__after__summary_apply_agent2llm | success | Phase one |
| EG-U | hook__context__error__summary_generate_user2agent | error | Phase one |
| EG-A | hook__context__error__summary_generate_agent2llm | error | Phase one |
| EA-U | hook__context__error__summary_apply_user2agent | error | Phase one |
| EA-A | hook__context__error__summary_apply_agent2llm | error | Phase one |

| Field | JSON type | Required | Enum / constraint | Maximum string length | Absence representation | Allowed points |
|---|---|---|---|---|---|---|
| schema_version | integer | Yes | Exactly 1 in v1; MUST equal EventDefinition.major_version; boolean not accepted | Not applicable | Missing/null invalid | All ten |
| operation_id | string | Yes | Nonempty opaque host-generated HookOperation.operation_id, ASCII [A-Za-z0-9_-]+; must equal envelope operation ID, not a credential | 128 characters | Missing/null/empty invalid | All ten |
| point_name | string | Yes | Exactly one of the ten full names above; must equal declaration and event name; suffix is the authoritative layer | 128 characters | Missing/null/empty invalid | All ten |
| outcome | string | Yes | before for BG-U/BG-A; success for AG-U/AG-A/AA-U/AA-A; error for EG-U/EG-A/EA-U/EA-A | 7 characters | Missing/null/empty invalid | All ten |
| error_category | string | Conditional: required at error points, forbidden elsewhere | EG-U/EG-A: timeout, transport, provider, invalid_response, unknown. EA-U/EA-A: persistence, state_update, unknown | 16 characters | Non-error points: omitted (presence even null invalid); error points: missing/null/empty invalid; unknown is explicit safe fallback | EG-U, EG-A, EA-U, EA-A |
| failed_stage | string | Conditional: required at error points, forbidden elsewhere | EG-U/EG-A: generation_request, generation_validate, generation_unknown. EA-U: session_write, history_delete, session_reload, memory_update, application_unknown. EA-A: runtime_rebuild, tool_pairing, token_stat_update, application_unknown | 19 characters | Non-error points: omitted; error points: missing/null/empty invalid; corresponding *_unknown for unclassified stage | EG-U, EG-A, EA-U, EA-A |
| partial_apply_possible | boolean | Conditional: required at EA-U/EA-A, forbidden elsewhere | true or false; false only when host proves no application mutation could have occurred, otherwise true | Not applicable | Other points: omitted; EA-U/EA-A: missing/null invalid; unknown risk represented by true, not null | EA-U, EA-A |

| Points | Exact allowed field set |
|---|---|
| BG-U, BG-A, AG-U, AG-A, AA-U, AA-A | schema_version, operation_id, point_name, outcome (four fields) |
| EG-U, EG-A | Four common fields plus error_category, failed_stage (six fields) |
| EA-U, EA-A | Four common fields plus error_category, failed_stage, partial_apply_possible (seven fields) |

Reject unknown or out-of-point fields; null never substitutes for omission. Apply-error stage validation derives its layer from point_name: reject the other layer's stages. For User2Agent, session_write/history_delete/session_reload apply only to session-backed execution; memory_update applies to sessionless execution. The host verifies that finer execution-path consistency. Classification uses host exception types, not exception text. Host cancellation and interrupts propagate. partial_apply_possible becomes true before the first potentially mutating application step; unknown mutation risk is true, not null, and does not prove persistence or rollback. Proposed total serialized payload cap: 8192 UTF-8 bytes; never truncate identity to meet a limit. Verify the existing operation-ID generator against the proposed ASCII/128-character bound before implementation; mismatch requires renewed confirmation. Locally returned empty summaries and human nonacceptance remain skips, not errors; provider-empty retry exhaustion is a generation error.

`schema_version` identifies the contract version. For SummarySnapshot v1, `schema_version` MUST equal the EventDefinition `major_version`. Any incompatible SummarySnapshot change MUST create a new EventDefinition major version AND the matching `schema_version`; independently changing only one is invalid. Runtime matches on event major version; Snapshot validation uses `schema_version`; equality keeps both views consistent. Independent evolution requires an explicit compatibility matrix first; phase one does not introduce that complexity. Freeze v1 once the precise field table is confirmed; future incompatible changes MUST bump the version, not silently extend v1. Before coding, the implementer must submit a short table specifying exact names/types, required fields, enums, length limits, absence semantics, and per-point availability for Human confirmation. The approved list above establishes the boundary, not an already implemented executable schema. Examples in this document are illustrative and must conform to that confirmed table and point-specific validation.

Unknown values must have the confirmed absence representation, not be disguised as zero. Earlier candidate fields such as trigger reasons, input counts, processor/model identifiers, generation timing, and post-update counts are not part of the approved minimal v1 field set; adding them requires explicit contract review rather than implicit pass-through.

Length limits do not equal sanitization. The host retains full internal diagnostics; future summary-body access requires a separate policy for permissions, transfer scope, limits, retention/deletion, and sanitization. Authorization does not permit unlimited output.

### Integration and Division of Responsibilities with Existing Mechanisms

**Revision note:** mandatory application composition/Executor injection below is retained summary implementation history, superseded as a generic-entry requirement by [Human revision](#human-revision-and-accepted-generic-entry-prototype).

Use the generic [Layering and ownership](#layering-and-ownership) and [Shared execution facade](#shared-execution-facade) contracts, with the following summarize-specific composition decisions. Application composition structure: EventDefinition + HookPointDeclaration → explicit HookPointCatalog + trusted preparation request → HookRuntime + application HookScope → Registrar → Executor → explicit injection into ContextRuntime. The former summary path used an explicit `ConfiguredPreparationRequest` and deployment-owned `ConfiguredTrustPolicy`, not the simplified Script-only bootstrap: the now-deleted `SummaryHooksOwner` created Runtime/Scope, `ConfiguredHookRegistrar.from_prepared()` invokes `register_prepared_points()`, and the Executor was injected into ContextRuntime. Complete Module/Script point plans, including optional direct-child Script membership, are prepared and published with per-point dispositions; no partial-point admission or hot reload is added. The generic scripts/folder bootstrap retains its separate whole-layer policy; it does not supply Module configuration.

- Compose Runtime/Scope/Registrar/Executor once at application startup, shared by all AgentChats and sessions in that application process. Eagerly prepare ConfiguredHookPoint resources, validate Modules/Scripts, and register into Runtime before normal operation; no lazy first-dispatch registration. The Executor coordinates registration readiness.
- A single configured Hook registration failure disables that Hook, not the application. In phase one, "single Hook" means ONE `HookPointDeclaration` and its complete point plan, NOT the entire application layer and NOT an arbitrary individual Script; partial plan admission requires a later explicit policy. A Module or Script preparation failure invalidates and disables that point plan; other valid points remain active. Valid Modules/Scripts within a valid point plan remain active, but none execute while their containing plan is invalid or disabled; do not silently discard a failed entry and publish a partial plan. Emit high-visibility logs, metrics, and a startup report identifying the unavailable point; because the Runtime is shared, the disabled point affects ALL sessions.
- The summarize application composition MUST explicitly select and enforce disable-not-fail independently of the generic bootstrap default. Generic `fail` / `disable` environment semantics (`TOPSAILAI_CONFIGURED_HOOKS_STARTUP_POLICY`) MUST NOT silently override this approved summarize policy. This is implemented by the summary prepared composition and its startup dispositions, not by changing generic bootstrap semantics. The startup report MUST distinguish "disabled by configured startup policy" from "unavailable due to preparation failure", identifying the affected point and reason without exposing sensitive exception text.
- `ConfiguredHookExecutor(runtime, scope, registrar, catalog)`; business code calls `executor.dispatch(point, payload=..., operation=...)` through the adapter.
- Check DispatchReport rejection_reason, outcomes, and unified_result; a returned report does not imply business success.
- At application shutdown, close in order: Registrar stops accepting registrations → Scope stops new operations and waits for/cancels in-flight work → Runtime records final state and closes internal resources. Coordinate Executor-owned execution resources within that shutdown flow.
- Return CloseReport to the application owner, record it, and make it testable: closed Hooks, waited/cancelled operations, cleanup failures, cleanup debt, and `fully_closed`. Check cleanup_debts() and use bounded retry_cleanup(debt_id) attempts under application ownership; unresolved debt stays explicit and must never be reported as a full close.

The application lifecycle owns composition and cleanup; AgentChat/session exit must not close the shared resources, and summarize calls must not recreate them. Each summary still has its own HookOperation and host-owned checkpoint state. Shared resources require cross-session isolation, locks/coordination, and attributable operation/session diagnostics to prevent state contamination. Phase one does not support cross-process/cross-worker runtime persistence or persist runtime resources into session history; per-session scoping may be revisited in P2. Inject the Executor explicitly downward, without adding global mutable test switches or authorization-bypass modes. Prefer explicit dispatch: early returns/human rejection mean function success is not equivalent to applied. Use decorators only when function return semantics exactly match business checkpoints; do not wrap the entire function and claim persistence success.

| Existing mechanism | Retained responsibility |
|---|---|
| hooks_pre_chat / hook_summarize_messages | Evaluate summary triggers without changing the algorithm |
| HookInstruction / manual summarize | Human entry point reaching the same business observation points |
| pre-run / post-final-answer | Outer session lifecycle |
| BEFORE/AFTER_LLM_CHAT, AFTER_LLM_RESPONSE | Generic request/content processing, not proof that history updates completed |
| New unified points | Read-only business lifecycle observation, configured execution, and resource governance |

Ordinary Hook returns of False, None, or dictionaries grant no authority to cancel, rewrite the summary, or replace history. The first version permits neither transformation nor blocking; future support requires separate authorization and contract/atomicity validation.

### Synchronous Execution, Failure, and Resource Risks

- Currently use mode="sync" and waiting dispatch(). Only after genuine asynchronous conversion use mode="async" and await adispatch(), while addressing blocking LLM/persistence work. Prohibit fire-and-forget, nonwaiting APIs, and bare background tasks that bypass governance; asynchronous auditing requires a separate bounded queue, consumer lifecycle, and cleanup design.
- Default to failure_policy="report"; after_apply must be report-type and must not portray completed application as never having occurred. Ordinary handler failures do not change business outcomes; host cancellation/interrupts must not be swallowed.
- Preserve the original business exception's identity, traceback, and propagation semantics. Hook diagnostics must not override the primary exception; error-observer failures must not recursively generate error events.
- Hooks must not retrigger summarize within the same operation. Protection state explicitly belongs to the host operation; external workers must not assume context inheritance, and uncorrelated reentry is not allowed by default.
- Discovery, registration, and execution all contribute to latency. A latency_budget_ms declaration does not equal an enforced deadline; verify Runtime dispatch timeout and separately define the total Hook dispatch budget and whole-summary budget.

### Minimal Implementation Scope and Acceptance

The first step integrates only the eight first-phase points in the table above, retaining business control flow, human confirmation, persistence, and token updates. File responsibilities:

| Scope | Responsibility |
|---|---|
| workspace/context/base.py | Start and exceptions for message/runtime generation |
| workspace/context/ctx_runtime.py | User2Agent application completion and exceptions |
| workspace/context/agent2llm.py | Agent2LLM application completion and exceptions |
| hooks/points/context/ | Declarations, payloads, and adaptation; avoid expanding shared base.py |
| hooks/__init__.py and hooks/point_entry.py | Current package initialization and direct resource execution/cleanup; no workspace owner or business Executor injection |

Prepare a test plan before implementation, covering at least:

- New-name equality, phase consistency, malformed four-segment rejection; all ten layer-suffixed names, eight active points and two inactive candidates; compatibility with legacy names and independent event names; Catalog does not activate the second phase.
- Both layers × message/runtime: order, notification count, correlation ID, and actual processor fallback.
- Empty input, feasibility rejection, a locally returned empty summary, and human nonacceptance do not falsely report application or exceptions. Real empty-provider responses instead exhaust the existing request retries and report a generation error; see [Summary Scripts acceptance](#summary-scripts-acceptance).
- LLM and persistence/reload failures preserve original exception identity/traceback, with correct stage and partial-application markers.
- Behavior remains unchanged without configured Hooks; report-type failures/timeouts do not alter normal business behavior.
- Payloads cannot mutate original messages; tool-call pairing, head/tail, and token updates remain intact.
- Real Registrar/Runtime/Executor and built-in hook_script execution; eager application-startup registration, single-Hook disable-not-fail with visible logs/metrics/startup report, and shared availability across sessions.
- Application shutdown order Registrar → Scope → Runtime; CloseReport contents and bounded cleanup-debt handling, including unresolved debt with `fully_closed=false`. AgentChat/session exit does not close the shared Runtime; independent operations/sessions do not contaminate checkpoint state.
- Reentry and error-observer failures do not recursively trigger summary/error; cancellation is not swallowed.
- BDD through real HTTP/SSE with llm_mock_server verifies requests and user-visible history/runtime outcomes, not just callbacks.

Run all unit tests through `tests/run_tests.py`, not `pytest tests/unit`; single-file pytest is allowed. Temporary artifacts go in the designated .tmp; do not depend on a real external LLM.

### Design Review Findings

Reviewer: AIMember.gpt56terra-programmer. Human approved recording the review, then selected Option B (ConfiguredHookPoint) for activation and Option A for idempotency/recursion suppression. Human subsequently approved P0-4 and explicitly chose application-level ownership for P0-5, NOT the recommended AgentChat-instance level. These decisions refine the existing baseline without authorizing implementation; refer to the preceding sections for established naming, lifecycle, payload, and execution rules.

#### P0 — Human Decisions

P0-1 through P0-5 are DECIDED below. The precise v1 field table still requires Human confirmation before coding; application composition and prepared-plan handoff are implemented as described above. Historical decision rows retain their original requirements; they do not override the implemented baseline. Option labels refer to the Human-facing choices; the historical Path A/Path B labels below identify existing framework paths, not those choices.

| Gap | Decision status and implementation requirements |
|---|---|
| P0-1: Resource activation chain | **DECIDED — Option B (ConfiguredHookPoint preparation pipeline).** Both `modules/` and `scripts/` use `ConfiguredHookPoint` (`module_folder` / `ConfiguredScript.target`) → discovery → security check → capture → probe `main(...)` for Modules → build runnable plan → register to Runtime → dispatch executes. Existing Path A is this preparation path; existing Path B is `ConfiguredHookBootstrap → ConfiguredHookRegistrar → Runtime.register_configured`, carrying only `scripts` or `folder`, not `module_folder`, `module_args`, `module_kwargs`, or `ConfiguredScript.target`. The Module/Script prepared-plan handoff is connected through `from_prepared()` and `register_prepared_points()`; S1–S3 implement multi-Script directory membership and separate mixed deployment authorization, with S4 acceptance recorded below. |
| P0-2: Error-point recursion suppression | **DECIDED — Option A.** Only summary business exceptions emit error points. Handler/Module/Script failures enter DispatchReport/logs/metrics only and never trigger a new error point. Use the per-summary operation state in P0-3; current `HookOperation` identity/parent/depth (≤1000) alone provides no summary-level guard. Preserve the existing primary-exception and cancellation rules. |
| P0-3: Checkpoint idempotency | **DECIDED — Option A.** Create one `HookOperation` per summary operation; host-owned per-operation state enforces at-most-once dispatch for `(operation_id, point_name)`. Mark the checkpoint before dispatch; duplicates are skipped and return already-handled, without observer re-execution. Retries within the same operation do not redispatch that checkpoint; a new summary operation has its own state. Correlation alone does not enforce this rule: repeated raw dispatch currently creates distinct HookEvents. |
| P0-4: Executable snapshot schema | **DECIDED — Human approved.** Freeze metadata-only, versioned SummarySnapshot v1; reject unknown fields and enforce per-point lifecycle availability. Common fields: `schema_version`, `operation_id`, `point_name`, `outcome`. Derive layer from the business_action suffix in point_name; reject a separate layer payload field. Error points add `error_category`/`failed_stage`; application-error adds `partial_apply_possible`. Exclude summary content, raw messages, live objects, full tracebacks, and credentials. Incompatible changes MUST bump both `schema_version` and EventDefinition `major_version` together, preserving equality as specified in [Data Contract](#data-contract). The implementer proposes a short exact field table (types, required/enums/lengths/absence and point availability) for Human confirmation BEFORE coding; approval covers the rules and boundary, not a completed executable schema. |
| P0-5: Composition and shutdown ownership | **DECIDED — Human explicitly selected application level, not AgentChat-instance level.** Compose Runtime/Scope/Registrar/Executor once at application startup and close at application shutdown; all AgentChats/sessions share them. Eager preparation/validation/registration precedes normal operation. Single-Hook registration failure disables that Hook with high-visibility logs/metrics/startup report, while the application continues; disablement affects ALL sessions. Close Registrar → Scope → Runtime; return and record testable CloseReport under application ownership (closed Hooks, waited/cancelled operations, cleanup failures, `fully_closed`). Explicit cleanup debt receives bounded application-owner retry; never fake full close. No cross-process/cross-worker runtime persistence or runtime resources in session history in phase one. Address contamination, isolation/locks/coordination, and harder state attribution; per-session scoping is a P2 revisit. |

#### P1 — Before Coding

- **RESOLVED — Version relationship:** SummarySnapshot `schema_version` MUST equal EventDefinition `major_version`; incompatible changes upgrade both together. Independent evolution requires a compatibility matrix and is out of phase-one scope; see [Data Contract](#data-contract).
- **RESOLVED — Startup disable unit and policy precedence:** disable one complete `HookPointDeclaration` / point plan on preparation or registration failure, never the entire application layer or an arbitrary Script; no silent partial plan admission. Other valid points remain active. Summarize composition explicitly enforces disable-not-fail independently of generic startup defaults; startup reporting distinguishes configured-policy disablement from preparation unavailability. See [Integration and Division of Responsibilities with Existing Mechanisms](#integration-and-division-of-responsibilities-with-existing-mechanisms).
- **Confirmed field table:** submit the minimal v1 names/types, required fields, enums, lengths, absence semantics, and per-point availability for Human confirmation before coding.
- **Report disposition:** define a matrix for registration failure, rejection, timeout, Script cleanup pending, and Hook error: host outcome, log level, metrics, retryability, and cleanup follow-up. This makes the existing DispatchReport checks actionable. The point-plan disable unit, summarize policy precedence, and startup reason distinction are RESOLVED above; remaining disposition fields and runtime failure cases remain open.
- **Application checkpoints:** specify the last completed step per layer using the lifecycle above: User2Agent human acceptance and persistent write/delete/reload; Agent2LLM runtime rebuild, tool-call pairing, and token-stat update. Define `failed_stage` and `partial_apply_possible` markers for intervening failures.
- **Module loading boundaries:** discovery considers direct children only, excludes `__init__.py`, and does not discover nested modules. Capture/isolation is not normal import; `main` must be a plain function. Interpret “execute by name” in the directory section within this captured-module model, not as ordinary package import.
- **Script admission:** document platform-specific executable-bit and allowlisted shebang/native-format requirements, symlink/path-escape rejection, timeout/output limits, and cleanup debts. The inspected recursive-folder path deduplicates entries by basename: `scripts/a/audit.py` and `scripts/b/audit.py` collide. This is current-path behavior to test, not a general Script-name restriction; [Deterministic name keys](#deterministic-name-keys) keeps final registered names authoritative and root-relative discovery naming pending Human approval. Recursive discovery depends on the selected Runtime registration implementation, not Executor/Registrar alone.
- **Phase-two activation gate:** decide whether the two `after_summary_generate_<layer>` points enter the Catalog and how disabled configuration references are handled; Registrar calls `catalog.require()` for every binding. Preserve the established phase-one scope.
- **Timeout supervision:** decompose whole-summary, dispatch, declaration `latency_budget_ms`, Module/Script entry, and cleanup budgets; specify who measures, who cancels, and how the host continues after timeout.

#### P2 — After Phase One Stabilizes

- Design async mode / `adispatch` and context propagation without converting synchronous observers to fire-and-forget.
- Define cross-worker operation identity and reentry coordination; retain phase-one sync-only execution and no external reentry. Revisit per-session scoping if shared application resources require stronger isolation or easier attribution; do not change the approved application owner implicitly.
- Develop the separate controlled summary-body access policy identified in Data Contract: permissions, audit, retention/deletion, transport scope, and sanitization.
- Specify per-point dispatch duration, registration duration, rejection category, and cleanup-debt-count observability.
- Develop the separate legacy migration plan: dual-write/dual-trigger allowance, retirement window, configuration migration, and rollback.

#### Additional Review Acceptance Tests

Extend, rather than duplicate, the acceptance checklist above:

- Make old/new name validation table-driven; explicitly reject new-format name/event and phase mismatches while accepting legacy independent names.
- Exercise duplicate dispatch for the same operation/checkpoint against the decided P0-3 semantics; negatively assert that observer failure emits no `error_summary_*`.
- Assert after-apply emission occurs only after the last step in each layer; human nonacceptance, a local empty-result branch, and feasibility skip emit neither success nor error. Provider-empty retry exhaustion is a separate generation-error case. Retain the existing partial-apply markers and original exception identity/traceback assertions.
- Exercise the selected ConfiguredHookPoint preparation pipeline and its implemented Catalog/Registrar/Runtime handoff; prove Modules are actually discovered, captured, probed, and executed, not merely declared.
- For generic recursive Script discovery, reject nested-folder basename collisions. Prepared summary discovery does not traverse ordinary subdirectories; reject symlinks, path escape, non-executable files and invalid shebangs without partial admission.
- Verify eager application-startup preparation/registration occurs once before normal operation, shared across AgentChats/sessions without first-dispatch lazy registration.
- Inject one configured-Hook registration failure: only that Hook is disabled, the application continues, all sessions see the same disablement, and logs/metrics/startup report expose it.
- Verify Registrar → Scope → Runtime shutdown order, in-flight wait/cancel behavior, complete CloseReport contents, bounded cleanup-debt retries, and honest unresolved-debt reporting. AgentChat/session exit must not close shared resources; concurrent sessions must not share checkpoint-handled state.
- Validate the confirmed v1 field table for all ten points, reject the removed layer payload field, missing/invalid layer suffixes, cross-layer dispatch, envelope mismatch, cross-layer failed_stage values, unknown/out-of-stage fields and sensitive content, and verify version/absence handling and incompatible-version rejection.
- Retain the existing real HTTP/SSE BDD requirement using `llm_mock_server` and user-visible session results.

### Open Questions

| Question | Decision pending |
|---|---|
| after_generate | Second phase by default; if Human requires generation-success observation in the first step, adjust scope and tests |
| summary_retry | Distinguish network-request attempts from whole-business attempts; do not infer the latter from the former |
| triggered/skipped/finally | First freeze reason enums, notification counts, names, available phases, and failure semantics; do not broaden after |
| Legacy Hook migration | Separate task, not automatic |
| Precise v1 field table | P0-4 rules/boundary approved; implementer submits exact types, required/enums/lengths/absence and per-point availability for Human confirmation before coding |
| Application wiring/cross-worker reentry | Application owner is decided; confirm composition files, shared Executor injection/isolation boundaries, and identification mechanisms. Cross-worker runtime persistence is outside phase one; per-session scoping is a P2 revisit |
| timeout | Determine each point's timeout and the total business budget to prevent prolonged plugin blocking |
| Symmetrical external resource configuration | Freeze Module/Script file/list/folder schema, local/external combination rules, eligible-folder policy and nested registered-name generation; reuse existing prepared handoff without claiming generic Module bootstrap completion |
| Controlled application access | Retained legacy library in `hooks/application_access.py`; `workspace/hooks_application.py` was deleted in U3, and current input/Summary dispatch does not bind or use the library |

Open items are not allowed by default: security, behavior, and permissions require prior confirmation; subsequent plans resolve other implementation details within the agreed rules.

## Verification plan

Plan tests before each implementation or integration unit. The [summarize acceptance checklist](#minimal-implementation-scope-and-acceptance) and [additional review tests](#additional-review-acceptance-tests) specialize this general plan without replacing framework verification. Existing focused tests use a standalone test publisher and isolated fixture plugins without importing application owners. Test artifacts, logs, caches and worker temporary data must be confined to the workspace .tmp directory. Only owned processes/resources may be cleaned up.

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

Use synchronization/ready signals rather than equal-duration sleeps. Isolation canaries require real child processes and a separate loose test anti-hang watchdog. Do not confuse mocked timeout return values with proof that workers terminate. Test supported operating systems and packaged launchers separately; document unsupported environments. For the supported `point_entry` direct-entry path, Module rows are asserted to share the parent PID (in-process) while Script rows are asserted to run in a distinct child process.

Later LLM-related integrations require BDD using `tests/mock/llm_mock_server.py` over real loopback HTTP/SSE, proving unchanged provider request counts. Full project unit verification uses `tests/run_tests.py`, not a single pytest invocation over the full unit tree. Focused committed-tree evidence for earlier implemented units includes module discovery 22/22, HookScript orchestration 59/59, and Runtime/reload/diagnostics 68/68; a separate Hooks-scope run reported 277 collected and 277 passed in 20.72 seconds. For the simplified configured Runtime change, public Runtime BDD passed 4/4, interruption-sensitive validation passed 668/668 without coverage instrumentation, the prescribed complete Unit runner passed all 294 files, and authoritative commit-scoped coverage passed at 289/302 statements (95.6954%), 107/112 branches (95.5357%), and 396/414 combined (95.6522%). Cross-platform, packaged-launcher, application-integration, and production-performance acceptance remain separate.

### Summary Scripts acceptance

S1–S4 are complete: S1 `b5672e472b9a62a3bffe7a6b02744c47639c9464`, S2 `1b373d6d9722ad29e098ea9e68a61b533fb89964`, S3 `69d66eac595b18cbda63d8754d5f4ca624a32c2b`, and test-only S4 `a4516f5f3f53cbf712f403322211b3650e043c48`. Independent STEP144/145 verification used a clean S4 committed-tree snapshot; it does not verify unrelated dirty working-tree changes.

| Evidence | Committed-snapshot result |
|---|---|
| S4 integration | 6 passed; exit 0 |
| S4 BDD | 19 passed; exit 0 |
| Empty-provider diagnostics selection | 2 passed, 17 deselected; exit 0; subset of the 19 BDD cases |
| Existing summary Hooks BDD | 17 passed; exit 0 |
| Prescribed full unit runner (`tests/run_tests.py`) | 363/363 files, 11,785 cases; zero failures/errors/skips; parent exit 0; 394.76 seconds |
| S1 changed-scope coverage | Statements 198/199 (99.50%); branches 63/64 (98.44%) |
| S2 changed-scope coverage | Statements 284/285 (99.65%); branches 100/102 (98.04%) |
| S3 changed-scope coverage | Statements 12/12 (100%); branches 4/4 (100%) |
| Aggregate changed-scope coverage | Statements 494/496 (99.60%); branches 167/170 (98.24%); consistent normalized arcs, including `hooks/hook_script_discovery.py` |

Real loopback HTTP/SSE via `tests/mock/llm_mock_server.py` covers both message/runtime payload modes; message mode is not a non-streaming transport claim. Empty-provider output exhausts 18 existing requests and records requested 5, 10, …, 85-second backoffs before `LLMRetryExhaustedError`. Test-local backoff instrumentation does not establish elapsed-time/performance guarantees. A separately labelled integration-only local empty-result injection proves the owner skip branch, not wire-level provider behavior.

Composed enabled/disabled controls verify summary/history/token equivalence, exact error-checkpoint Script identity and original business exception propagation. Settled observer failures are report-only and introduce no provider retry; unresolved cleanup, host cancellation or exhausted deadlines still prevent unsafe successors. Snapshot source and ancestor permission corrections fixed verification setup, not production validation.

Task evidence (relative to ProjectFolder): `.tmp/summary-scripts/step144/` contains suite logs, `full-parent.json`, `full-results.txt` and `changed-scope-coverage.json`; STEP145 reports those results. This is commit-scoped unit/BDD/integration acceptance, not unrestricted full-project GREEN, full CLI restart, cross-platform, physical-custody, deployment or production-performance acceptance. U11H/provenance decisions remain separate; all seven P2 gates stay closed, `cleanup_profile` immutable, C3 containment separate, child capability STOP and native implementation unauthorized. S1–S4 introduced or changed no environment variables; `env_template` and `docs/Environment_Variables.md` require no update.

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

The separately approved opt-in summary Module/Script family is implemented with application-owned preparation and injection; see [Summary Scripts acceptance](#summary-scripts-acceptance). Beyond this exception, add one event family at a time from the catalog only after separate approval, such as conversation or run lifecycle. Keep core ownership and control flow unchanged. No legacy migration or tools/memory/skill work is bundled into this phase. Update factual runtime documentation only when functionality is actually shipped.

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

One framework provides registration, event delivery, ordering, isolated execution, deadlines, outcomes and lifecycle management. Functional differences live in event schemas and caller-owned result policies, not hook categories. Optional extensions may propose data but never gain implicit authority over core application flow. The explicitly adopted summary Module/Script integration uses that same framework and read-only business checkpoints. Other lifecycle integrations remain separately reviewed and gated; summary acceptance does not grant broader rollout or deployment approval.

## Configuration convenience and migration boundary

The target convenience contract selects Module and Script file/list/folder sources symmetrically, including point-local defaults and authorized external extensions. The currently implemented `scripts`/`folder` spelling below is Script-specific; it must not be presented as the completed Module configuration contract. Both kinds feed the same unified point plan and retain whole-candidate rejection and last-known-good replacement.

Conceptual input-point selection (source choices only, not a runnable configuration schema):

| Point | Kind | Example configured selection |
|---|---|---|
| `hook__workspace__before__input_message` | Script file | Human example: `/TopsailAI/src/topsailai/scripts/act_bell.sh` (project-relative `scripts/act_bell.sh`) |
| Same point | Script folder | Deployment-authorized external `input-scripts/` directory |
| Same point | Module file/list | Deployment-authorized external `input_observer.py`, or an explicit list of Module files |
| Same point | Module folder | Deployment-authorized external `input-modules/` directory containing eligible `main` Modules |

The external Module/folder paths are conceptual deployment selections, not claims that files exist or are currently accepted by bootstrap. Every selection requires authorized roots, dependency/closure evidence and platform admission. The bell example does not promise execution or audibility: its `#!/usr/bin/env bash` shebang requires admission under the actual policy, and isolated/captured stdout or an unavailable controlling terminal means a BEL result is not proof of audible terminal output. Do not relax trust, replay untrusted terminal controls, or expand child capabilities to make it work.

`hook_name` plus exactly one of `scripts` or `folder` is a convenience interface for the Hook Point's default Script Hook, not permission to publish a second first-class plan type. Both source forms use the name key above; list order is not an execution contract. For this generic configured API, folder enumeration remains bounded, recursive and no-symlink, with shell-free format validation and deployment-owned trust. The prepared summary path instead uses direct-child Script membership as described in [Directories, Responsibilities, and Execution Protocols](#directories-responsibilities-and-execution-protocols). Invalid or duplicate entries reject the whole change and preserve the previous unified plan.

The implemented legacy Hook-name validator retains the exact case-sensitive `^hook_[a-z][a-z0-9_]*$` contract, without event-name, path, prefix or alias fallback. The implemented new-point validator adds a strict double-underscore branch, matching point/event names and phase validation while preserving the legacy branch (see [Naming, Phases, and Framework Validation](#naming-phases-and-framework-validation)). Identical complete plans are successful no-ops; replacement must preserve unrelated registrations and admitted old snapshots. Execution retains existing failure, timeout and cancellation policies with no automatic retry. Scope and Runtime close own plan removal, admitted-work settlement, artifact retirement and bounded cleanup recovery.

Startup and lazy registration must atomically establish the complete Module/default-Hook plan and preserve immutable artifact capture, scope ownership, deadlines, cancellation and cleanup recovery. Callers need not manage candidates, leases, TTLs, publication or disposal. Hiding candidate mechanics does not supersede the terminal architecture.

### Retained compatibility and legacy APIs

The retained configured APIs are described in [Hooks API](../docs/Hooks_API.md). U06 synchronous dispatch and U08 awaited dispatch use unified execution; U10 removed nonwaiting emission and receipts as a breaking change, with no alias. This documentation synchronization changes no production signatures.

The prior claim that terminal `hook_script` was merely historical and no longer defined the public architecture is withdrawn. Earlier task records remain historical evidence, but cannot override the Human's clarification. The default terminal Handler, per-point cardinality, Module `main` entry and Module-before-Script name ordering remain authoritative.

## Framework-readiness extension before application Hook-point rollout

The implemented extension provides preparation and insertion conveniences, but U07–U10 are implemented and U11A–E have selected acceptance evidence; complete readiness remains gated by U11H and the accepted provenance exception decision before core rollout. This is a feature extension and convenience layer over the implemented Runtime, not a replacement for it. It adds environment-driven bootstrap, startup or first-use registration, a shared execution facade, and two insertion styles: decorators for ordinary callable boundaries and explicit function-body calls for precise lifecycle points.

The explicitly adopted summary Module/Script integration is the scoped application exception described in [Summary Scripts acceptance](#summary-scripts-acceptance); it does not close the broader framework gates. These framework-readiness APIs are implemented and exported. The following configured compatibility calls remain; sync and awaited async dispatch are unified, and nonwaiting APIs have been removed:

```python
runtime.register_configured(...)
runtime.dispatch_configured(...)
await runtime.adispatch_configured(...)
```

### Layering and ownership

**Mandatory business-side Hook aliases:** To make Hook dependencies immediately recognizable in business logic, every function, class, or variable imported from `topsailai.hooks` or its submodules MUST use an explicit consumer-side import alias, and business references MUST use that alias:

| Imported symbol kind | Required import form |
|---|---|
| Function | `from topsailai.hooks.<module> import original_name as hook__original_name` |
| Class | `from topsailai.hooks.<module> import OriginalClass as Hook__OriginalClass` |
| Variable, including constants | `from topsailai.hooks.<module> import ORIGINAL_NAME as HOOK__ORIGINAL_NAME` |
| Module | `from topsailai.hooks.<package> import module_name as hook__module_name` |

The prefix MUST be prepended to the original symbol name without renaming the public symbol in `hooks`. This is an identification convention at the business consumption boundary only; it MUST NOT change runtime behavior, execution ownership, or public APIs. It does not rename Hook-internal implementation symbols, unrelated legacy mechanisms, local business helpers, or receiver attributes. This requirement does not authorize a repository-wide rename. Business integration sketches below use these aliases for imported Hook symbols; Hook-internal declaration and implementation examples retain their original names.

**Exemption for already-prefixed symbols:** A symbol whose public name already carries the corresponding prefix (`hook__` for functions and modules, `Hook__` for classes, `HOOK__` for variables and constants) MUST NOT receive a duplicated prefix and requires no additional consumer-side alias. For example, `hook__workspace__before__input_message` is referenced by its existing name without becoming `hook__hook__workspace__before__input_message`.

For example, importing the point-local adapter module MUST be written as `from topsailai.hooks.points.context import summary_adapter as hook__summary_adapter`, and business code MUST reference it through `hook__summary_adapter`.

**Revision note:** requiring application startup binding or HookApplication below is superseded for the generic-entry target. Package bootstrap and direct point invocation are accepted; existing application-bound APIs remain legacy behavior. See [Human revision](#human-revision-and-accepted-generic-entry-prototype).

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
     U06 sync/U08 awaited execution and U07 desired-active diagnostics are implemented
```

**Target adjustment — no signature refactor:** application startup owns environment/configuration, trust, Runtime, Scope, Registrar and Executor, and explicitly binds a controlled application-scoped, context-isolated access/provider. Business code uses that unified access at an exact checkpoint, or the decorator uses its provider at a genuine before/success/error function boundary. Merely adding a Hook must not require Executor parameters, Hook constructor fields, a new service class, or call-chain dependency plumbing in the original function/class. This replaces mandatory per-call explicit Executor injection as the usability target. The controlled application access/provider is implemented in `343c8fa0`, and application-owned lifecycle is implemented in `9a1f846b`; broader rollout and generic external-resource bootstrap remain pending.

The binding is not an arbitrary mutable process-global singleton or a hidden thread-local agent. Application instances must not overwrite or borrow each other's bindings. Tasks/contexts carry only their owning application binding; threads require deliberate owner-validated propagation, not ambient inheritance or cross-thread fallback. Nested binding restores the previous context with an exact ownership token; tests restore bindings even on exceptions. Disabled/unbound report-type access returns a deterministic unavailable/no-op diagnostic without creating resources; closed bindings reject admission and never recreate or borrow a Runtime. Authorized blocking points must fail according to their Catalog contract, never treat missing binding as successful execution. The implemented access surface is `HookApplicationAccess` and `HookExecutorAccess`, provided by `bind_hook_application()` and `get_hook_executor()` in `hooks/application_access.py`; unavailable-state rejection reasons include `application_unbound`, `application_disabled`, `application_context_mismatch`, and `application_closed`. Extensions beyond this committed scope remain implementation design work.

Application shutdown stops access admission, settles in-flight work, closes Registrar → Scope → Runtime under bounded cleanup policy, and invalidates the binding; cleanup debt remains explicit. Input functions, sessions and decorators do not own shared shutdown. Business modules never read environment/configuration, discover Module/Script sources, construct Runtime, build trust assertions or mutate Runtime trust. Decorator and explicit insertion styles resolve the same Executor and Registrar; neither duplicates discovery, registration, failure caching, reload or cleanup logic.

The first release owns configured registrations in one application-level Scope with the Runtime lifetime. The [summarize application](#integration-and-division-of-responsibilities-with-existing-mechanisms) explicitly selects that owner with eager registration, per-Hook disable-not-fail visibility, and Registrar → Scope → Runtime shutdown; generic lazy mode remains available to other integrations. Short-lived request-level configured scopes are deferred because they would repeat capture and retirement. Runtime close first closes admission, settles Registrar waiters and owned deliveries under existing deadlines, retires plans and artifacts, and reports bounded cleanup debt.

### Environment-driven bootstrap

**Revision note:** the manifest/pin and deep-environment restrictions below describe legacy configured bootstrap only. Generic-entry initialization reads TOPSAILAI_HOOK_POINTS in hooks/__init__.py without that admission; see [Human revision](#human-revision-and-accepted-generic-entry-prototype).

Environment is read exactly once at the application configuration boundary and converted into a deeply detached typed snapshot. No dispatch, decorator wrapper, Registrar, or worker reads `os.environ`.

The current environment interface locates versioned configuration/trust files; direct inline environment lists are not implemented. Future configuration must express local/external Module and Script selections symmetrically at this startup boundary, never through deep business-layer environment reads. Exact schema/environment extensions remain pending. When implementation lands, synchronize `env_template`, `docs/Environment_Variables.md`, API and owning factual documentation; this documentation-only target update changes no environment behavior or factual environment reference.

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

U10 removed nonwaiting Runtime/facade methods and receipts; Catalog background mode is rejected, with no alias or hidden replacement. Lazy dispatch and adispatch share registration singleflight and wait for the unified execution result. Failed desired-revision preparation retains the active valid revision; readiness must track both rather than erase the old plan.

### Shared execution facade

**Revision note:** the application-provider facade below is retained, but not required on the accepted input path; the generic named point delegates to invoke_hook_point instead. See [Human revision](#human-revision-and-accepted-generic-entry-prototype).

The implemented controlled access/provider resolves the already prepared application-owned Executor and delegates to this same facade. It supplies no alternate execution engine, registration cache, implicit Runtime construction or application lifetime. `hooks/application_access.py` exports `HookApplicationAccess`, `HookExecutorAccess`, `bind_hook_application()` and `get_hook_executor()`; the former `workspace/hooks_application.py` owner was deleted in U3, so legacy callers must explicitly own any binding and shutdown. Broader external-resource bootstrap and wider application rollout remain target work.

The implemented waiting-only facade returns the compatibility `DispatchReport` with `unified_result`; it does not return a bare HookPointResult or derive/rewrite the unified decision:

```python
class ConfiguredHookExecutor:
    def dispatch(self, point, *, payload, operation=None) -> DispatchReport: ...
    async def adispatch(self, point, *, payload, operation=None) -> DispatchReport: ...
```

`point` is a catalog-owned `HookPointDeclaration`, not an arbitrary caller-created name/schema pair. The Executor creates the immutable event from the declaration, owning Scope, detached payload, and supplied correlation metadata; invokes the shared Registrar according to startup/lazy mode; then calls the existing Runtime method. Sync dispatch retains the existing rejection inside a running event loop. Async first-use preparation runs blocking discovery/capture in controlled infrastructure and does not block the event loop.

An unconfigured or disabled ordinary point returns a stable no-op/report outcome. A configured registration or execution failure follows the declaration policy:

- `report` is the default and preserves host flow while recording the structured result.
- `block` is allowed only when the catalog explicitly marks a security-critical point and its owner defines the host exception contract. Rejection or unified non-success triggers it; successful execution with cleanup pending/failed alone does not. Normal False/None/error-shaped data never grants blocking authority.

No Hook return value implicitly replaces a business result. Any future transformation requires a separately reviewed domain reducer.

### Decorator Hook-point insertion

Decorators are intended only for callable boundaries whose timing aligns with function entry, successful return, or exceptional exit. They are not appropriate when the point belongs between statements, after a partial commit, around a branch, before mandatory cleanup, or for a fire-and-observe requirement, which the framework does not support.

Existing attribute-injection shape (retained API, not the no-signature-refactor target requirement). Both decorator examples assume `hook_point` is imported as `hook__hook_point` and Hook declarations use `HOOK__` import aliases; payload builders remain local business helpers:

```python
@hook__hook_point(
    before=HOOK__OPERATION_BEFORE,
    success=HOOK__OPERATION_SUCCESS,
    error=HOOK__OPERATION_ERROR,
    executor_attribute="hook_executor",
    payload_builder=build_safe_payload,
)
def operation(...): ...
```

`before`, `success`, and `error` are three optional, distinct `HookPointDeclaration` references with separate stable names, schemas, policies, and budgets. They are not labels applied to one ambiguous Hook point. At least one must be supplied. The canonical post-return phase name is `success`; an API alias named `after`, if ever provided for compatibility, must resolve only to the same success-only slot and cannot coexist with `success`.

For free functions, `executor_provider` may be supplied instead of `executor_attribute`. The provider is application dependency injection; it must return an existing Executor and must not read environment or create a Runtime. Instance methods use the explicitly named receiver attribute. `functools.wraps`, descriptor binding, annotations, and the original inspectable signature are preserved. For `classmethod` or `staticmethod`, the Hook decorator applies to the underlying function inside the descriptor decorator; ambiguous ordering is rejected or documented by validation rather than guessed.

For the no-signature-refactor target, use the controlled application provider for free functions and methods without adding a receiver field or constructor parameter merely for Hooks. The existing `executor_provider` seam remains reusable, and application/context binding plus application-owned lifecycle are implemented; broader rollout and cross-worker propagation acceptance remain separate. Adding the decorator must preserve the original signature and calling conventions. Do not wrap all of `input_message()` to represent its interior checkpoint: the committed input path selects the input mode first and dispatches once before reading and before input-only interruption handling or `hook_message()` interception.

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
@hook__hook_point(
    before=HOOK__USER_LOOKUP_BEFORE,
    success=HOOK__USER_LOOKUP_SUCCESS,
    error=HOOK__USER_LOOKUP_ERROR,
    executor_attribute="hook_executor",
    payload_builder=build_user_lookup_payload,
)
async def lookup_user(self, user_id: str) -> User:
    return await self.repository.get(user_id)
```

A synchronous function uses the identical declaration mapping; only its wrapper calls `dispatch` instead of awaiting `adispatch`. This convenience wrapper must compile to the same Executor calls an explicit insertion would make; it has no independent registration cache.

### Explicit function-body insertion

Explicit insertion is the default for precise core lifecycle work. The owning module selects a catalog declaration and builds a minimal detached payload at the exact checkpoint. Under the adjusted target it calls the implemented controlled application access/provider without changing the original function/class signature. The following examples illustrate the retained explicit-Executor API only; their added Executor argument is not a requirement for adding new points. The access call delegates to the same waiting facade and preserves the same checkpoint and exception semantics.

Synchronous before/success/error example:

```python
def save_record(record, hook_executor):
    hook_executor.dispatch(HOOK__RECORD_SAVE_BEFORE, payload=safe_record_input(record))
    try:
        result = persist(record)
    except Exception as error:
        hook_executor.dispatch(HOOK__RECORD_SAVE_ERROR, payload=safe_error(error))
        raise
    hook_executor.dispatch(HOOK__RECORD_SAVE_SUCCESS, payload=safe_record_result(result))
    return result
```

Asynchronous example:

```python
async def run_task(task, hook_executor):
    await hook_executor.adispatch(HOOK__TASK_BEFORE, payload=safe_task_input(task))
    try:
        result = await execute_task(task)
    except Exception as error:
        await hook_executor.adispatch(HOOK__TASK_ERROR, payload=safe_error(error))
        raise
    await hook_executor.adispatch(HOOK__TASK_SUCCESS, payload=safe_task_result(result))
    return result
```

Waiting completion example:

```python
report = await hook_executor.adispatch(
    HOOK__TASK_FINISHED,
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
| Invocation mode | `sync` or `async` only; background is rejected. |
| Scope | Initially the application Scope; deviations require lifecycle justification. |
| Failure policy | Default `report`; security-critical `block` requires explicit approval and host error contract. A blocking `success` declaration must approve post-business-work failure risk; an `error` declaration can never replace an active business exception. |
| Sensitive-field policy | Allowlist, redaction, exception-summary rules, and prohibited fields. |
| Ordering and latency | Required checkpoint ordering, aggregate deadline, startup/first-use allowance, and steady-state overhead budget. |
| Ownership and cleanup | Owner of Executor, operation correlation, close ordering, and diagnostics. |

The catalog is the source of event construction truth for both decorators and explicit calls. Hook configuration selects scripts for a known declaration; it cannot invent schemas or turn an ordinary point into `block` through an environment file.

### Lifecycle, diagnostics, and performance gates

The bootstrap owner creates one Runtime, one long-lived application Scope, one Registrar, and one Executor. The current bootstrap publishes them only after startup registration succeeds or explicit whole-layer disablement is recorded. The implemented opt-in summary composition instead publishes per-Hook disable-not-fail startup dispositions through its prepared Registrar; the generic whole-layer bootstrap remains unchanged. Shutdown prevents new ensure/dispatch admission, wakes registration waiters, settles work, closes Scope and Runtime, and reports cleanup debt without allowing a late registration to republish.

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
- New point insertion and provider-backed decorators require no Hook-specific business parameters, constructor fields or call-chain plumbing; tests prove application/context/thread isolation, test restoration, unbound/disabled/closed behavior and bounded shutdown without Runtime recreation.
- Local and external Module/Script file/list/folder selections pass the same trust, bounded discovery, capture, duplicate-name, ordering, deadline, cancellation, cleanup and last-known-good tests. Folder semantics and generated names are reviewed before publication; a mixed Module/default-Script plan proves neither kind bypasses the unified engine.
- One catalog contract drives both insertion styles, with reviewed schema, sensitive fields, mode, Scope, failure policy, ordering, latency, and owner.
- Trust changes replace Runtime; graceful close prevents stale publication and reports zero unexplained cleanup debt in acceptance runs.
- Structural performance tests prove disabled and `READY` paths perform no hidden bootstrap filesystem I/O and async first use does not block the event loop; each concrete core Hook-point rollout records and approves its numeric latency and resource budgets.
- Unit coverage exceeds the project threshold, BDD proves user-visible bootstrap/decorator/explicit behavior, integration uses real isolated workers, and a non-empty configured public demo uses the supported manifest loader.
- Configured-bootstrap environment variables are synchronized in `env_template` and `docs/Environment_Variables.md`.
- Core integration remains absent until this gate is accepted.

### Readiness status and implementation roadmap

**U07–U10 are implemented; full architecture acceptance remains gated by U11H and the accepted provenance exception decision.** U06A–U06D synchronous per-point execution, `main` invocation and both name-order stages are committed and verified in their selected affected scope; the older inventory below remains historical evidence, not full lifecycle/core-rollout approval.

**Additional target gaps from the Human's external-extension/no-signature-refactor requirement:** symmetrical external Module/Script configuration, complete generic external Module bootstrap/prepared-plan adaptation, remain unimplemented; the application-scoped access/provider, application-owned lifecycle, and application-bound input checkpoint are committed in the limited current scope. Resolve schema/merge and nested naming policy, then verify broader signature-preserving interior/decorator insertion and local/external parity in separately reviewed logical units. Existing summary wiring and generic Script configuration must remain intact. This design update authorizes no activation, broader rollout or capability expansion; all seven P2 gates remain closed, `cleanup_profile` remains immutable, C3 containment stays separate, child capability remains STOP and native implementation remains unauthorized.

Already implemented and verified:

- Opt-in summary Module/Script preparation, separate offline mixed authorization, point-local direct-child membership and S1–S4 committed-tree acceptance; see [Summary Scripts acceptance](#summary-scripts-acceptance). Broader framework and deployment acceptance remain gated.

- Generic Runtime/Scope/Registry/Scheduler, process isolation, diagnostics, deadlines, cleanup, explicit binding APIs, and settings reload.
- Exact configured Hook names, ordered scripts/folder discovery, immutable capture, atomic plan replacement, sync/awaited-async configured execution (background removed by U10), and Scope/Runtime cleanup.
- Public Runtime BDD, interruption validation, the 294-file Unit runner, strict commit-scoped coverage, and maintained generic real-worker demos.

Framework-readiness implementation units completed in dependency order:

1. **Versioned trust-manifest loader and typed bootstrap:** implemented in `hooks/configured_bootstrap.py` with pinned digest, strict schema/path/budget validation, and immutable authority records.
2. **Startup application-Scope registration:** implemented in `hooks/configured_registration.py` with `fail` and whole-layer `disable` behavior.
3. **Lazy Registrar singleflight:** implemented with shared sync/async state, deterministic failure caching, typed bounded transient retry, reload/invalidation, and close arbitration.
4. **ConfiguredHookExecutor facade:** implemented in `hooks/configured_executor.py` with `dispatch` and awaited `adispatch` returning DispatchReport with unified_result; U09 enforces Catalog authorization, and U10 removes `aemit`.
5. **Hook-point catalog and explicit insertion contract:** implemented in `hooks/hook_point_catalog.py` with exact declaration ownership and policy validation.
6. **Decorator adapter:** implemented in `hooks/hook_point_decorator.py` with distinct before/success/error declarations, cardinality, identity-preserving error propagation, recursion metadata, idempotency, binding/metadata preservation, and generator rejection.
7. **Framework acceptance:** U11A–E provide real isolated-process ordering/returns, LKG reload, cancellation/deadline barriers, sync/async wrapper business semantics and configured startup/demo exit evidence; the latest selected affected run is 480 passed without skips/xfails. Accepted provenance REDs are excluded unchanged, not unrestricted ALL GREEN. U11F–G synchronize limited documentation only. Final full regression and per-file completion review remain pending and must pass before the framework is accepted. Production performance budgets remain a rollout-specific acceptance input rather than a reason to change framework semantics.
Prerequisites before core rollout are final acceptance of units 1–7 plus a reviewed initial Hook-point catalog. Beyond the explicitly implemented summary checkpoints, deferred to later core-integration phases: additional decorators or function-body calls in `workspace/`, `ai_base/`, `context/`, tasks, tools, memory, or skills; choosing concrete payloads from live business objects; and changing domain results based on Hook outputs. Each later core point is one separately reviewed logical unit with its own invariants and BDD/integration evidence.
