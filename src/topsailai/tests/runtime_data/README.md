---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Runtime Data Test Specification

## Purpose

This specification defines acceptance behavior for the Agent-scoped Runtime Data mechanism, the LLM request retry-state producer, and read-only Runtime Instructions before implementation begins.

The tests follow the project BDD rule: user-visible LLM behavior crosses the real OpenAI-compatible HTTP/SSE boundary through `tests/mock/llm_mock_server.py`; pure Store invariants and formatting rules remain focused unit tests.

## Human-Approved Behavior

- Runtime Data belongs to one `AgentRuntime`; it is not User2Agent or Agent2LLM message data.
- A dedicated Store owns runtime states and bounded settled history.
- The initial state key is `llm.request.retrying`.
- With threshold `3`, the state becomes active on the third failed attempt of one LLM request.
- The state remains active through every later retry in that same request.
- As soon as that LLM request finishes for any reason, the active state no longer exists.
- Settled history has a fixed maximum count and cannot grow indefinitely.
- Runtime Instructions are read-only.
- After implementation, the mechanism is documented in the Agent Core MEMO and the project `MEMORY.md`; root `MEMO.md` receives only a concise index link.

## Terminology

### LLM request

One invocation of `LLMModel.chat()` with one request-level operation identifier. Its internal provider attempts and any automatic or manually authorized retry cycles remain part of the same request until the invocation returns or raises.

### Failed attempt count

The number of provider attempts in the current LLM request that have produced the error-attempt Hook Point. For threshold `3`, counts `1` and `2` are below threshold, and count `3` activates the retry state.

### Active state

The current public Runtime Data entry visible while its owning LLM request is still retrying at or above the threshold.

### Settled history

A bounded diagnostic record created when an active state is removed. History does not make the state active and does not authorize business behavior.

### Lease

An opaque ownership capability returned when a state is activated. Update and removal require the matching lease so stale cleanup cannot alter a newer owner of the same key.

## Test Layers

| Layer | Responsibility | Required boundary |
|---|---|---|
| Store unit tests | State validation, lease ownership, snapshots, revisions, bounded capacity, concurrency | In-process public Store API |
| AgentRuntime unit tests | One Store per Agent and dependency injection | In-process `AgentRuntime` API |
| LLM producer unit tests | Threshold arithmetic, unavailable Runtime, publication failure isolation, settlement mapping | Hook/public request seams without replacing HTTP BDD |
| LLM producer BDD | Real retry lifecycle and state observability | Real loopback HTTP/SSE through `llm_mock_server` |
| Instruction unit tests | Registration, read-only output, filtering, formatting, unavailable Runtime | Public Instruction dispatch or handler API |
| Regression tests | Existing AgentRuntime, retry, null-response recovery, Hook and Instruction behavior | Existing project suites |

## Required Test Artifacts

Implementation is expected to add or update the following test artifacts. Exact names may be refined before the relevant logical unit, but the separation of responsibilities must remain.

```text
tests/unit/test_topsailai_ai_base_runtime_data.py
tests/unit/test_topsailai_ai_base_agent_runtime.py
tests/unit/test_topsailai_llm_retry_runtime_state.py
tests/unit/test_topsailai_workspace_plugin_instruction_runtime.py
tests/bdd/features/llm_retry_runtime_state.feature
tests/bdd/llm_retry_runtime_state_harness.py
tests/bdd/steps/llm_retry_runtime_state_steps.py
tests/bdd/test_llm_retry_runtime_state.py
```

## Global Invariants

Every test layer must preserve these invariants:

1. Runtime state never enters User2Agent session messages.
2. Runtime state never enters Agent2LLM request messages.
3. Runtime state is not written to session persistence.
4. State values contain no prompt, response content, credential, configured recovery-message text, or complete exception text.
5. Publication and query failures never replace the original LLM result or exception.
6. Different Agent instances do not share Runtime Data.
7. A request can remove only the state owned by its own lease.
8. Active entries and settled history are both bounded.
9. Snapshot consumers cannot mutate internal Store state.
10. Instruction handlers cannot call Store mutation methods.

## State Transition Model

For threshold `3`, the required observable transition is:

```text
request starts
  -> failure 1: no active state
  -> failure 2: no active state
  -> failure 3: active llm.request.retrying
  -> failure 4+: same active state updated
  -> request returns or raises: no active state
  -> one bounded settled-history record when the state had activated
```

A request that finishes before failure `3` creates neither an active retry state nor a settled retry-state history record.

## Outcome Mapping

At minimum, tests distinguish:

| Request terminal condition | Active state after settlement | History outcome |
|---|---|---|
| Eventual provider success | absent | `recovered` |
| Automatic retry exhaustion | absent | `failed` |
| Back to chat | absent | `abandoned` |
| Explicit Exit | absent | `failed` |
| Hard interruption or cancellation | absent | `interrupted` |
| Unexpected exception | absent | `failed` |

If implementation uses different concise outcome tokens, they require review before tests are written; semantically distinct success, abandonment, interruption, and failure outcomes must not collapse silently.

## BDD Evidence Rules

Every LLM Runtime Data scenario must:

- Start a private `llm_mock_server` on loopback port `0`.
- Configure the production client to use only that loopback endpoint.
- Exercise production `LLMModel.chat()` and its actual HTTP/SSE parser.
- Assert server-side request count and parsed request bodies.
- Capture state snapshots through the public Runtime Data query API, not internal fields.
- Synchronize observations with request lifecycle phases or Hook checkpoints; fixed sleeps are not acceptable evidence.
- Close the exact model, server, handler threads, and serving thread created by the scenario.
- Write temporary data only under `/TopsailAI/src/topsailai/.tmp`.

## Execution Order

For each logical unit:

1. Create a timestamped checklist under `.task/` before running tests.
2. Implement the source change before adding executable tests; this project does not use red-green TDD unless explicitly requested.
3. Add tests described by this specification.
4. Run focused tests without color.
5. Fix failures and rerun affected regression scope.
6. Review every changed file individually.
7. Perform independent unit-end review.
8. Commit the completed logical unit with explicit pathspec after review.

Task-level execution follows:

1. Store and AgentRuntime unit tests.
2. LLM producer unit tests.
3. Real HTTP/SSE retry-state BDD.
4. Existing retry and null-response recovery regressions.
5. Runtime Instruction unit tests and existing Instruction regressions.
6. Full unit runner.
7. Relevant BDD suites in separate collection.
8. Coverage and diff checks.

## Logical Unit Mapping

| Logical unit | Owning specification |
|---|---|
| Runtime Data Store and AgentRuntime composition | `runtime_data_store.md` |
| LLM retry-state producer and lifecycle | `llm_retry_state.md` |
| Read-only Runtime Instructions | `runtime_instructions.md` |

## Completion Criteria

The feature is accepted only when:

- All mandatory scenarios in the three owning specifications pass.
- The threshold is proven to activate at failed attempt `3`, not before and not only after it.
- Active state absence is proven after every tested request terminal path.
- History capacity is proven with more settlements than the configured maximum.
- Existing LLM retry and null-response recovery behavior remains green.
- Documentation accurately reflects the implemented contract without embedding source code or internal implementation narrative in the environment-variable reference.
