---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
status: proposed
scope: design only
---

# Standalone Unified Hook Framework

## Status and scope

This is a proposed architecture, not an implemented capability. This revision replaces the earlier migration-oriented proposal in this document. It follows the latest human direction: one foundational framework, with domain-specific behavior implemented above it.

In scope now: the independent framework, its execution guarantees, interfaces, configuration, lifecycle, extension seams, and verification plan. Possible future integration families are conversation, User2Agent turns, Agent2LLM runs, LLM requests, prompt assembly, context summarization, persistence checkpoints, and task lifecycle.

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

## Proposed package and dependencies

All paths in this section are proposed, not claims of existing implementation.

| Module | Responsibility |
|---|---|
| hooks/contracts.py | Typed event, binding, context, outcome, receipt, and policy records |
| hooks/registry.py | Definition validation, dependency graph, immutable registry snapshots |
| hooks/configuration.py | Decode a provided configuration object into typed settings; no deep environment reads |
| hooks/runtime.py | Public lifecycle and emission facade |
| hooks/dispatcher.py | Admission, event selection, deadlines, stable report assembly |
| hooks/scheduler.py | Bounded queues, dependency readiness, concurrency limits |
| hooks/worker_protocol.py | Bounded JSON transport, request/result correlation and validation |
| hooks/worker.py | Isolated target import and sync/async handler invocation |
| hooks/process_backend.py | Platform-qualified worker supervision and cancellation |
| hooks/diagnostics.py | Injected non-recursive, bounded diagnostic sink |
| hooks/extensions/ | Optional generic orchestration helpers using the same dispatch protocol |

The core depends on portable infrastructure, not ai_base, workspace, tools, skill_hub, memory, or application events. The application may inject an adapter for its event recorder. Domain schemas and reducers belong with the owning domain. Do not turn AgentRuntime into a general service locator: inject HookRuntime explicitly into owners that need it.

## Core abstractions

Use typed records internally; mappings are limited to JSON boundary encoding and explicitly schema-governed payloads.

| Abstraction | Required fields and meaning |
|---|---|
| EventDefinition | name, major_version, payload_schema_id, payload_limit_bytes; immutable declaration of a publishable contract |
| HookEvent | event_id, name, major_version, owner_id, scope_id, operation_id, parent_operation_id, sequence, timestamp, layer, purpose, payload |
| Binding | binding_id, exact event name/version, handler_ref, priority, after, requires_success, timeout_ms, max_concurrency, enabled, allowed_payload_fields |
| HookContext | Event snapshot plus delivery_id, binding_id, registry_generation, remaining_budget_ms, origin and depth; no live host object |
| HookOutcome | delivery_id, binding_id, status, optional JSON value, duration_ms, safe error category, started flag |
| DispatchReport | event_id, generation, ordered outcomes, elapsed_ms, deadline_exhausted; not a business result |
| DeliveryReceipt | admitted flag, event_id and rejection reason; admission is not successful execution |
| HookScope | Owner-linked registration handles and pending delivery ownership; closing is idempotent |
| HookRuntime | Registry, bounded scheduler, supervisor and diagnostic lifecycle; explicitly owned and closable |

Event identity and subscription identity differ. Event name describes a stable boundary, binding_id identifies one registration, event_id identifies one occurrence, and delivery_id identifies one binding's attempt for that occurrence. Reusing a handler for different events does not deduplicate subscriptions. Duplicate binding IDs within a scope are rejected, never silently overwritten.

Names use dot-separated namespaces such as conversation.started and context.summary.finished. Schema major version is a separate integer; incompatible changes require a new major version. Initial matching is exact name plus major version, without wildcards or arbitrary filter callbacks. Category labels may be metadata but never choose a different execution engine.

Sequence is monotonically increasing per scope under the owner lock; it records publication order, not completion order. IDs are correlation data, not credentials or authorization. Payload schema definitions are bounded declarative schemas, not custom application callbacks invoked during core validation.

## Unified handler and public interfaces

Conceptual interfaces below are pseudocode, not runnable project APIs.

```text
handle(context: HookContext) -> JsonValue | Awaitable[JsonValue]

runtime.register(definition, binding, scope) -> RegistrationResult
runtime.unregister(handle) -> RegistrationResult
runtime.emit(event, policy) -> DeliveryReceipt
runtime.dispatch(event, policy) -> DispatchReport
await runtime.adispatch(event, policy) -> DispatchReport
runtime.open_scope(parent, metadata) -> HookScope
runtime.close(deadline) -> CloseReport
```

Every handler has the same signature and return envelope. Null, false, zero, empty text, empty list, and empty object are valid distinct JSON values. The framework does not interpret any of them as a veto, replacement, success marker, or request to retry. Execution success is represented by outcome.status, independently of outcome.value.

Host-side admission, serialization, configuration, queue, and backend errors return diagnostic statuses. Programmer-facing registration can expose detailed validation errors through RegistrationResult without raising through normal runtime emission. Genuine host cancellation and interrupts remain host control flow, not successful empty reports.

Recommended outcome statuses: success, error, timeout, invalid_output, worker_lost, cancelled, skipped_dependency, skipped_disabled, skipped_deadline, rejected_capacity. A rejected event yields an explicit receipt/report reason rather than pretending that no handlers matched. No matching bindings yields a successful empty dispatch.

Reports remain bounded. emit does not store unlimited futures or reports; it sends completion summaries to the diagnostic sink. dispatch owns its short-lived report. Any future result polling API must have explicit retention and consumption rules.

## Registration, discovery and configuration

Use an explicit manifest or typed API registration. Handler references are importable module:callable strings; closures, live instances, lambdas, and implicitly inherited thread-local agents are not supported. Configuration parsing must not import plugin modules.

The application reads a chosen config source once and passes settings to HookRuntime. No new environment-variable family is prescribed. No directory crawling, implicit loading from the working directory, or automatic execution of installed entry points. If package discovery is added later, it must enumerate metadata first and require an explicit allowlist before import.

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
  },
  "bindings": [
    {
      "binding_id": "example-session-audit",
      "event": "conversation.started",
      "event_version": 1,
      "handler_ref": "example_plugin.audit:on_event",
      "priority": 100,
      "after": [],
      "requires_success": [],
      "max_concurrency": 1,
      "timeout_ms": 500
    }
  ]
}
```

These are proposed finite starting budgets, not measured production defaults. Reject non-finite/negative durations, excessive graph sizes, unknown fields, incompatible versions, and undefined events. Enforce global hard caps above per-binding settings. Hook runtime disabled is a cheap no-op with no workers.

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
runtime = HookRuntime(settings, process_backend, diagnostic_sink)
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

Plan tests before implementation. Foundation tests use a standalone test publisher and isolated fixture plugins without importing application owners. Test artifacts, logs, caches and worker temporary data must be confined to the workspace .tmp directory. Only owned processes/resources may be cleaned up.

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

Later LLM-related integrations require BDD using tests/mock/llm_mock_server.py over real loopback HTTP/SSE, proving unchanged provider request counts. Full project unit verification uses tests/run_tests.py, not a single pytest invocation over the full unit tree. This design revision does not run product tests or claim these gates have passed.

## Phased delivery

### Standalone contract and scheduler

Implement typed records, schema validation, configuration, immutable registry, dependency planning and no-op behavior. Use deterministic scheduler tests and a fake execution adapter; do not enable plugins in the application. Review all public result and error semantics before proceeding.

### Isolated worker execution

Implement the bounded JSON protocol, platform-qualified launcher, sync/async handler invocation, deadlines, cancellation, output caps and cleanup-debt handling. Prove hangs/import stalls/crashes are contained using real-process tests. No deployment enablement until the backend passes these gates.

### Runtime ownership and diagnostics

Complete bounded queues, scope lifecycle, explicit registration handles, reload, non-recursive diagnostics and shutdown. Verify two scopes and repeated lifecycle cycles leave no unbounded state. Release the framework as a standalone usable component, without changing existing hooks.

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
