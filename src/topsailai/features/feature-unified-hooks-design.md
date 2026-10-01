---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: partially implemented
scope: standalone components implemented; integration and some acceptance remain
---

# Standalone Unified Hook Framework

## Status and scope

This document records both the approved architecture and the current implementation boundary. The standalone framework, HookScript planning and orchestration, and configured module discovery are implemented; application integration, immutable file artifacts, a concrete script launcher/transport, and some acceptance gates remain. This revision replaces the earlier migration-oriented proposal and follows the latest human direction: one foundational framework, with domain-specific behavior implemented above it.

| Dimension | Current status |
|---|---|
| Implementation | Standalone contracts, validation, configuration, registry, scheduler, runtime, scope, diagnostics, HookScript planning/orchestration, and module discovery are implemented. |
| Verification | Focused committed-tree gates exist for the implemented components; full-project, cross-platform, packaged-launcher, and production-performance acceptance remain separate. |
| Integration | Configured discovery and HookScript components are not yet composed into the ordinary Runtime or application lifecycle boundaries. |

In scope now: the independent framework, its execution guarantees, interfaces, configuration, lifecycle, extension seams, current implementation status, and verification plan. Possible future integration families are conversation, User2Agent turns, Agent2LLM runs, LLM requests, prompt assembly, context summarization, persistence checkpoints, and task lifecycle.

Explicitly out of scope: all tool-specific hooks under tools/, tool invocation and approval integrations, memory hooks, skill hooks, compatibility adapters, and migration of existing TOPSAILAI_HOOK_* implementations. Existing mechanisms remain untouched. No environment variable is introduced by this design. Domain integration is a later reviewed phase, not a prerequisite for the standalone component.

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
| Latency | emit returns after bounded admission without waiting for handlers. dispatch waits only up to an aggregate deadline. Neither promises literal zero CPU cost. |
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

The Runtime methods below are implemented, but this compact sketch is not an exact call signature reference. `HookScheduler` is implemented as a module-level API and is not currently a package-level export.

```text
handle(context: HookContext) -> JsonValue | Awaitable[JsonValue]

runtime.register(definition, binding, scope) -> RegistrationResult
runtime.unregister(handle) -> RegistrationResult
runtime.emit(event, policy) -> DeliveryReceipt
runtime.dispatch(event, policy) -> DispatchReport
await runtime.adispatch(event, policy) -> DispatchReport
runtime.open_scope(parent, metadata) -> HookScope
runtime.reload(settings) -> ReloadResult
runtime.make_event(...) -> HookEvent
runtime.close(deadline) -> CloseReport

settle_configured_empty_hook_script(...) -> HookScriptSettlement
execute_configured_hook_script(..., runner: HookScriptRunner, ...) -> HookScriptSettlement
```

The standalone HookScript orchestration interfaces `HookScriptExecutionOptions`, `HookScriptExecutionPolicy`, `HookScriptEntryResult`, `HookScriptRunner`, and `execute_configured_hook_script` are implemented. `HookScriptRunner` is an injected trusted runner protocol; these interfaces do not imply that a concrete launcher/transport or configured-hook Runtime integration is implemented.

Every handler has the same signature and return envelope. Null, false, zero, empty text, empty list, and empty object are valid distinct JSON values. The framework does not interpret any of them as a veto, replacement, success marker, or request to retry. Execution success is represented by outcome.status, independently of outcome.value.

Host-side admission, serialization, configuration, queue, and backend errors return diagnostic statuses. Programmer-facing registration can expose detailed validation errors through RegistrationResult without raising through normal runtime emission. Genuine host cancellation and interrupts remain host control flow, not successful empty reports.

Implemented `HookStatus` values include: success, error, timeout, invalid_output, worker_lost, cancelled, skipped_dependency, skipped_disabled, skipped_deadline, rejected_capacity. A rejected event yields an explicit receipt/report reason rather than pretending that no handlers matched. No matching bindings yields a successful empty dispatch.

Reports remain bounded. emit does not store unlimited futures or reports; it sends completion summaries to the diagnostic sink. dispatch owns its short-lived report. Any future result polling API must have explicit retention and consumption rules.

## Registration, discovery and configuration

Use an explicit manifest or typed API registration. Handler references are importable module:callable strings; closures, live instances, lambdas, and implicitly inherited thread-local agents are not supported. Configuration parsing must not import plugin modules.

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

A configuration candidate is validated as a whole. Initial invalid configuration produces a disabled runtime with diagnostics; invalid reload preserves the last valid generation. A successful reload atomically publishes an immutable new generation. An in-flight dispatch retains its captured generation. Explicit unregister affects new admissions only; scope close also cancels outstanding deliveries.

## Ordering, dependencies and concurrency

For matching bindings, resolve a directed acyclic graph. after specifies completion-before-start, regardless of predecessor success. requires_success additionally skips the dependent if the predecessor did not succeed; it implies an ordering edge. Targets must exist within the same event/version and effective scope snapshot. Cross-event dependencies and hidden lookups into previous reports are unsupported.

Reject cycles and unknown references before activation. Priority cannot override dependency edges. Among ready nodes, choose ascending priority and then lexicographic binding_id; this avoids filesystem and discovery-order nondeterminism.

Default dispatch concurrency is one for simple predictable behavior. Explicit bounded parallelism may run independent ready nodes; selection order remains deterministic but completion order does not. Reports are always ordered by the stable topological plan, not completion timing. A failing independent handler never suppresses later independent handlers. Dependency skips and deadline exhaustion are intentional exceptions to execution, not propagation of a plugin error.

Per-binding max_concurrency defaults to one across an owning runtime. Ready deliveries for that binding use admission order. Cross-binding completion order and cross-process global ordering are not guaranteed. No dispatch holds a registry or application lock while waiting for a handler. Registration changes inside application code affect only future snapshots; workers do not receive registration authority.

Worker parallelism is bounded at runtime level, not multiplied without limit per scope. Sequential dispatch does not imply a stateful plugin singleton: initial workers use one delivery per process, preventing module globals leaking across calls. Worker reuse is a later optimization requiring an explicit reset/isolation contract and evidence; it must not silently weaken the initial guarantee.

## Dispatch algorithm and deadlines

All public emission paths use this same algorithm. emit returns after admission; dispatch/adispatch additionally wait for its terminal report.

```text
capture registry generation and matching bindings
validate and freeze bounded event snapshot
try admission without waiting for queue space
record absolute monotonic deadline at admission
schedule ready graph nodes while deadline and capacity allow
for each node:
    send detached payload to owned worker
    import target and invoke handle in that worker
    accept only matching, bounded, valid result before deadline
    convert failure to outcome and update graph readiness
finalize stable ordered report; discard every late result
```

Absolute deadline includes queue residence, process launch, import, execution and result transport. Each delivery expires at min(dispatch_deadline, delivery_start + binding_timeout). For emit, delivery_start does not reset the event deadline after a long queue wait. Unstarted nodes at deadline become skipped_deadline. A deadline is never extended by retries, recursive publication, result parsing, or sequential handlers.

Serialization limits include byte count, nesting depth, collection sizes, maximum string length, maximum bindings and output size. Do not invoke arbitrary __str__, repr, deepcopy, property access or custom JSON serializers on caller objects. Accept only validated JSON primitives/containers supplied by the publisher, detach them before dispatch, and reject cycles or oversized content without semantic truncation.

The host owns all result acceptance. Check event ID, delivery ID, scope lifetime, captured generation, deadline, output schema, and duplicate completion before accepting a result. A newer registry generation alone does not invalidate an already admitted delivery; closed scope or expired deadline does. Host code never unpickles plugin output.

## Synchronous and asynchronous execution

Synchronous and coroutine handlers run in the same worker protocol. The worker invokes the declared callable and awaits an awaitable result on a worker-owned event loop. It never nests an event loop inside the caller's loop. A coroutine that blocks is still terminated through the process supervisor.

emit supports synchronous and asynchronous callers with the same non-waiting admission semantics. dispatch is for synchronous callers; adispatch cooperatively awaits results without blocking the host loop. Calling dispatch from a running host event loop is rejected with a diagnostic report directing the caller to adispatch, rather than blocking that loop.

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

No hook can mutate host objects merely by modifying its input. Mutating a worker copy and then raising leaves the host unchanged. JSON return values are data only; no implicit merging into event payloads, environment variables, session messages or application results.

For lifecycle events, callers normally ignore values. For other capabilities, a domain extension can validate and consume values through the same DispatchReport. The core does not learn domain-specific meanings.

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

receipt = runtime.emit(start_event, policy=bounded_delivery)
continue_required_conversation_work()  # Does not depend on receipt success.
```

```text
base = validated_prompt_snapshot()
report = await runtime.adispatch(prompt_extension_event(base), policy=bounded_delivery)
candidate = prompt_policy.reduce_valid_proposals(base, report)
apply_if_revision_unchanged(candidate)
run_required_prompt_validation()
```

```text
plugin handle(context):
    read detached context.event.payload
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
| conversation.started / closing / closed | workspace/agent/agent_shell_base.py, AgentChat._run / run | After setup; before cleanup; after cleanup attempts. Conversation ID and cleanup outcomes. | Enqueue only; failures never delay required cleanup. |
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

Later LLM-related integrations require BDD using tests/mock/llm_mock_server.py over real loopback HTTP/SSE, proving unchanged provider request counts. Full project unit verification uses tests/run_tests.py, not a single pytest invocation over the full unit tree. Focused committed-tree evidence reported for the implemented units includes module discovery 22/22, HookScript orchestration 59/59, and Runtime/reload/diagnostics 68/68. Separately, the Tester reported a workspace Hooks-scope run with 277 collected, 277 passed, and 0 failed, errors, or skipped tests in 20.72 seconds. These are scoped gates, not proof of full-project, cross-platform, packaged-launcher, application-integration, or production-performance acceptance. Later full project verification must still use the prescribed runner.

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
| Strong isolation adds process-launch cost | Accept bounded cost initially; measure before adding reusable workers. Core business can use emit without waiting. |
| Strict ordering lengthens dispatch | One aggregate deadline; optional explicit parallelism for independent nodes only. |
| Hook outcome mistaken for business success | Separate reports from domain values and document exact lifecycle checkpoints. |
| Optional result processing becomes another framework | Keep domain policy outside core and reuse the same registry, worker protocol and outcomes. |
| Fake non-blocking promises | State finite wait semantics and OS limits; prohibit arbitrary inline plugin execution. |
| External mutation survives timeout | No automatic retries or rollback claims; require idempotency outside this component. |
| Shutdown cannot confirm worker death | Report cleanup debt, quarantine capacity, never block main cleanup indefinitely. |
| Expansion into unrelated tooling | Exclude tool/memory/skill and old-hook migration from current scope and phases. |

## Decision summary

One framework provides registration, event delivery, ordering, isolated execution, deadlines, outcomes and lifecycle management. Functional differences live in event schemas and caller-owned result policies, not hook categories. Optional extensions may propose data but never gain implicit authority over core application flow. Build and verify this component independently first; choose lifecycle integration points only after its non-disruptive behavior is proven.

## Configured module discovery and terminal hook_script

This section incorporates the human-approved registration requirements and supersedes the earlier statement that directory discovery is wholly deferred. Discovery remains explicit and configuration-driven: the framework never scans the working directory, installed packages, or arbitrary search paths implicitly.

### Hook-point configuration and reserved registration

Each framework-defined hook point may receive one typed configuration containing:

- `module_folder`: an optional canonical directory whose direct children are module-hook candidates;
- `hook_script.target`: an optional canonical path to one executable file or one directory of directly contained executable entries;
- module arguments and keyword arguments that are JSON-serializable and bounded;
- `hook_script.argv`: a bounded list of literal string arguments appended after each selected executable path;
- `hook_script.stdin_payload`: a declaration that the bounded detached hook context is encoded as JSON on standard input;
- `hook_script.environment_allowlist`: names that may be copied from the host environment;
- `hook_script.environment`: bounded explicit string overrides, with secret-bearing values prohibited from diagnostics;
- working-directory and input/output byte limits; and
- the ordinary unified binding timeout, aggregate deadline, cancellation, and capacity settings.

The implemented independent planner reserves exactly one binding named `hook_script` for every hook point. The design requires it to be admitted, scheduled, cancelled, settled, and reported through the same runtime mechanisms as module hooks once integrated. Users cannot replace, remove, duplicate, rename, reprioritize, or add dependencies after this reserved binding. An unconfigured `hook_script` remains a successful zero-entry no-op. It counts toward `bindings_per_event`; candidate validation reserves its slot so capacity is explicit rather than hidden.

The implemented planner places `hook_script` as the terminal binding. Module hooks execute sequentially in deterministic module-name order and must reach a terminal, cleanup-safe state before the next module starts. Only after every preceding module has completed may `hook_script` start. This rule overrides ordinary priority and parallel-ready-node selection for discovered hooks at that hook point; the compiled plan represents explicit completion-before-start edges ending at `hook_script`.

“Always last” defines ordering, not guaranteed execution. A completed module error or invalid result does not suppress later modules or `hook_script`; it is recorded and execution continues while budget remains. A timeout may permit continuation only after the exact owned worker has been confirmed terminated and its reservation settled. If cancellation, scope/runtime closure, aggregate deadline exhaustion, or unresolved cleanup debt leaves the preceding work unfinished, no later module or script starts. Remaining entries receive unified non-started outcomes such as `skipped_deadline` or `cancelled`. The main application flow returns within its bounded contract and never waits indefinitely merely to reach the script phase.

### Python and Cython module discovery

`module_folder` discovery is non-recursive and evaluates only direct regular-file children. It does not follow symbolic links. It excludes package initializers, hidden/editor-temporary files, directories, and files outside the canonical configured root.

Candidates are:

- files ending in `.py`; and
- extension modules whose complete suffix matches one of `importlib.machinery.EXTENSION_SUFFIXES` for the running interpreter.

Complete extension suffixes are matched in descending length order before the suffix is removed and the remaining logical module name is checked with Python identifier rules. Suffix recognition is filename-level candidate admission only; it does not certify ABI compatibility. A foreign-tagged filename whose complete foreign suffix is not recognized falls back to ordinary filename handling and is excluded when the remaining logical name is not a valid identifier. Conversely, a validly named but unloadable binary remains a recognized candidate and proceeds to isolated probing, where its failure is retained as a bounded load result rather than being silently omitted.

The logical module name is the filename with the complete recognized source or extension suffix removed. It must be a valid Python identifier. A source file and extension module, or multiple extension suffix variants, that map to the same logical name are an ambiguous identity and reject the candidate configuration rather than relying on import precedence.

Every recognized candidate enters the manifest. Isolated loading records success only when import succeeds and the module exposes a callable attribute named `main`; import failure or missing callable `main` remains in the manifest as a bounded failure entry such as `load_error`. Discovery validates importability and callable presence but never invokes the target `main`. The future invocation contract remains `main(*args, **kwargs)`. Signature introspection is advisory because Cython callables may not expose a reliable Python signature; an invocation mismatch is a normal isolated hook error, not host failure.

Stable registration identity is `(hook_point, canonical_module_folder, logical_module_name)`. Ordering uses the Unicode code-point, case-sensitive logical module name, independent of locale and filesystem enumeration order. The target immutable execution version is separate from stable identity and would include the runtime generation plus a content/version fingerprint; current frozen dataclasses do not freeze file contents.

Current discovery rejects invalid roots, path escapes, and duplicate recognized identities. Plugin import never occurs in the host process and never mutates host `sys.path`; import and callable-`main` validation run in a managed isolated worker under finite startup/import/execution budgets. A recognized candidate failure does not prevent independent later candidates from being probed. Capacity validation, atomic rejection of an integrated candidate configuration, and preservation of the active generation belong to the future Runtime integration layer described below; they are not capabilities of standalone discovery.

Process isolation is failure containment, not a security sandbox. Python and native extension code can execute at import time and retains the OS permissions of its worker account. Only administrator-trusted roots are eligible. Minimum-privilege accounts, filesystem/network sandboxing, and native-library policy are deployment controls outside this framework; unsupported containment fails closed rather than importing inline.

### Public hook_script discovery and execution

Static HookScript discovery is implemented. `hook_script` accepts either one configured file or one configured directory. A file target yields one candidate. A directory is scanned non-recursively for direct regular-file children; symbolic links, subdirectories, sockets, devices, and other special files are rejected or ignored according to candidate-level validation and are never executed.

Directory entries execute sequentially in filename order. The stable sorting key is `(basename, normalized relative path)`, compared case-sensitively by Unicode code point and independent of locale. For a non-recursive directory, basename is unique; the relative-path tiebreaker fixes the contract if representation rules later evolve. Extensions do not affect priority and do not select an interpreter.

Executable policy is explicit and shell-free:

- POSIX requires a regular file with execute permission. Text scripts require a valid shebang naming an allowed executable; native binaries must be directly executable by the operating system.
- Windows initially permits directly executable native entries recognized by the reviewed launcher, such as `.exe`. File associations and implicit execution of `.py`, `.bat`, `.cmd`, or PowerShell files are not used. Supporting an interpreter later requires an explicit configured launcher and separate review.
- No platform invokes a shell, builds a command string, expands globs, evaluates metacharacters, or searches `PATH` for the target.
- A directly configured non-executable file rejects the candidate. In a configured directory, non-executable ordinary files are excluded and summarized by bounded diagnostics; an empty resulting list is a successful no-op.

The target concrete launcher/transport will ensure each process receives an argument vector composed of the exact canonical executable path followed by configured literal `argv`. The detached, size-bounded hook context is encoded as JSON on standard input; no runtime object, scope object, credential, open descriptor, or mutable host reference is passed. The child environment starts from a minimal framework baseline, copies only explicitly allowlisted host names, then applies bounded explicit overrides. The working directory is the validated target directory unless an equally constrained explicit directory is configured.

The target concrete launcher/transport drains standard output and standard error without deadlock, byte-limited independently, sanitized, and kept separate from the structured result channel. They never flow directly into the application output. Non-zero exit, signal termination, malformed result, output overflow, startup failure, timeout, and cancellation map to the same bounded outcome/diagnostic categories used by module hooks.

The implemented static plan models `hook_script` as one registered hook, not one registry binding per executable. `execute_configured_hook_script` implements sequential orchestration over an immutable entry snapshot through an injected trusted `HookScriptRunner` protocol. A completed entry failure is retained in a bounded sub-result and does not prevent the next entry while the shared budget remains; a later success cannot overwrite an earlier failure. Every entry consumes the one absolute `hook_script` deadline and remaining dispatch deadline—each entry must not receive a reset full timeout. Runtime integration must reuse the existing unified scheduler and process ownership authority and must not create a second scheduler, executor, retry loop, or cleanup subsystem.

### Atomic reload and immutable versions

The target configured-discovery integration uses prepare-then-publish. Current `HookRuntime.reload()` atomically adjusts operational runtime settings; it does not jointly publish module/script manifests or immutable file artifacts:

1. Resolve and validate canonical roots, enumerate candidates, detect identities/conflicts, compute bounded fingerprints, and prepare an immutable manifest outside the runtime owner transaction. Any plugin import probe occurs only in isolated owned workers.
2. Enter the runtime owner transaction and revalidate runtime lifecycle, base generation, binding capacity, and manifest applicability.
3. Atomically publish settings, module manifest, terminal `hook_script` manifest, registry plan, and one new runtime generation.
4. On any rejection, retain the old settings, registrations, scheduler identity, manifests, and behavior.

An equal configuration with equal immutable manifests is an accepted no-op and does not increment generation. A content change at the same path creates a new execution version. Work already admitted retains its old ordered module list, script list, arguments, environment policy, limits, absolute deadline, and generation; later admission sees the complete new version or complete old version, never a hybrid.

Capturing paths alone is insufficient because files can be replaced in place after admission. A future jointly published file-backed version therefore requires framework-owned immutable artifacts, or an equivalently proven identity-preserving handle, with bounded reference-counted retention until admitted work settles. Cleanup physically removes only framework-owned versions, logs deletion, and observes count/byte/age limits. The first version supports only layouts whose module and native dependency closure can be frozen and loaded predictably; unresolved relative imports, mutable external package dependencies, or companion native libraries are rejected rather than falsely claimed immutable.

### Security and diagnostic boundaries

Configuration authority and code-execution authority are distinct from event publication authority. Only trusted configuration owners may add roots, environment names, launchers, arguments, or executable targets. When opening/versioning is integrated, canonical containment must be checked again immediately before that operation to limit path-replacement races. Files must eventually satisfy a configured ownership and permission policy; world-writable-root and entry enforcement remains to be implemented or independently accepted. Current discovery performs its existing canonical containment checks only; those checks do not freeze file identity or prove ownership, permission, or path-race safety.

Diagnostics contain stable hook point, stable binding/module identity, generation, bounded status category, entry count, and timing. They omit payloads, argv values, environment values, stdout/stderr content, arbitrary exception text, and absolute sensitive paths by default. Import and execution failures cannot recursively emit hooks.

### Historical delivery sequence and remaining work

Deterministic contracts and production implementation were added for direct-child `.py` and interpreter-compatible extension discovery, exclusion of incompatible `.so` names and symlinks, duplicate logical-name rejection, stable identity and locale-independent ordering, callable `main` validation, and isolated per-module load failure. Extension-only loading uses a real isolated extension fixture where the supported build environment permits it; a renamed text file is not treated as proof of extension loading.

Terminal `hook_script` reservation/order, discovery-to-plan bridging, configured-empty and legacy-zero-entry settlement, shared-deadline orchestration, and unfinished-cleanup gating were delivered in earlier focused units. Configured module discovery and entry validation were implemented and committed in `042ecc5`; the `_red` test filename records its TDD history rather than a currently failing state.

Remaining separate units cover a concrete cross-platform script launcher and JSON/argv/environment transport, aggregate module-discovery deadlines, candidate caps and cancellation, read-only-root-safe temporary isolation, immutable artifact versioning across reload, owned-resource cleanup, and application wiring. No unit may introduce a second scheduler or weaken the existing R2b/R3 reload contracts. Demos, tools, memory, skill, legacy migration, and the blocked repeated-cancellation deadline, cancellation early-return, and concurrent `make_event` proofs remain outside this completed discovery unit.


## Configured accepted-empty metadata settlement decision

This decision superseded the earlier next-unit statement above and the earlier plan suggestion of a general zero-entry helper with a predecessor-status argument. The accepted legacy nonempty-entry fix remains unchanged. The API is implemented and publicly exported, but it is not yet wired into Runtime.

### Input provenance and public entry

Public signature: `settle_configured_empty_hook_script(*, hook_point: str, module_bindings: tuple[Binding, ...], bindings_per_event: int, discovery_result: HookScriptDiscoveryResult | None) -> HookScriptSettlement`.

Use a separate entry rather than broaden `settle_unconfigured_hook_script(terminal)`. The new entry has no caller-controlled configured flag, terminal argument, predecessor statuses, or execution options. It fixes `hook_script_configured=True` and composes the existing public `build_hook_point_binding_plan_from_discovery(...)` with the supplied planning inputs and discovery result. It must reuse that bridge rather than duplicate its validators or construct a success terminal from raw entries.

The production caller obtains discovery_result from the existing static discovery boundary, retains its diagnostics, and supplies the same planning inputs used for the intended hook point. The constructor revalidates these inputs through the bridge; it never rescans the filesystem. A bare terminal is insufficient provenance: the ordinary planner can construct a configured empty terminal without discovery, and all current dataclasses are publicly constructible. Accordingly this API proves validated metadata composition only, not cryptographic provenance, filesystem authenticity, generation authority, or that discovery actually ran. In-memory public discovery records are suitable for contract tests; no new opaque authority, admission token, or registry is introduced in this unit.

### Fixed result semantics and precedence

The bridge result is inspected before entry cardinality. All results have `entry_results=()` and `started=False`; inputs and their nested metadata remain unchanged.

| Condition, in evaluation order | status | error_category |
|---|---|---|
| Bridge rejects malformed/missing discovery, accepted-with-errors, rejected discovery, or invalid planning inputs | error | hook_script_plan_rejected |
| Bridge accepts, but its terminal entries are not exactly the empty tuple | error | hook_script_nonempty_entries |
| Bridge accepts a configured terminal whose entries equal the empty tuple | success | None |

The existing bridge remains authoritative for exact input validation and detailed `HookPointBindingPlan.errors`. Its rejection diagnostics are not rewritten or copied into error_category. HookScriptSettlement has no detailed-errors field; the caller retains discovery/plan diagnostics separately. This decision does not add fields or promise a new diagnostic transport. A rejected discovery never becomes an empty successful terminal, even when its entries are empty. Accepted nonempty input remains pending work, not an executed or successful script. Validation rejection is returned as metadata; this unit does not add blanket exception handling for arbitrary hostile objects or internal programming failures.

### Compatibility and caller-owned readiness

The legacy helper remains restricted to unconfigured terminals: its exact-empty success, `hook_script_not_unconfigured` precedence, and `hook_script_nonempty_entries` rejection stay unchanged. The new API does not support the unconfigured case; missing discovery returns hook_script_plan_rejected, not legacy fallback.

This is a result constructor, not an admission or publication operation. The caller must establish readiness for the corresponding accepted plan through `hook_script_ready(...)` under its existing ownership authority before recording successful terminal completion. Missing predecessors, cleanup-pending work, cancellation, expired budget, closed scope, or stale generation must not be bypassed because entries are empty. The constructor neither reads those states nor enforces them; no predecessor mapping is accepted, and it may construct metadata before the caller is authorized to publish it. Empty results do not prove the whole hook chain completed. Actual configured-hook Runtime integration, lifecycle enforcement, and freshness proofs remain deferred work.

### Configured-empty contract history

The seven non-parameterized contracts in `tests/unit/test_topsailai_hooks/test_hook_script_configured_empty_red.py` were added during the RED phase and the implementation/export now exist. The `_red` suffix records test history; it does not indicate a currently failing suite. The contracts cover accepted-empty success, accepted-nonempty rejection, discovery and planning rejection, absence of readiness enforcement in the constructor, and unchanged legacy behavior.

This completed unit did not add execution transport, immutable artifacts, Runtime/application wiring, demos/integrations, tools/memory/skill, environment changes, legacy migration, or the separate cancellation/deadline/make_event proofs. Those exclusions remain valid boundaries for future work.
