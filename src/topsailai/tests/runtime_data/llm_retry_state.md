---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# LLM Retry Runtime State Test Cases

## Scope

These cases verify the `llm.request.retrying` producer across one complete `LLMModel.chat()` request. User-visible retry behavior must use a real loopback HTTP/SSE provider.

## Approved Threshold Semantics

With threshold `3`:

- Failure `1`: inactive.
- Failure `2`: inactive.
- Failure `3`: activate.
- Failure `4` and later: remain active and update the same entry.
- Request settlement: remove the active entry immediately.

The threshold counts failed provider attempts in the current `LLMModel.chat()` invocation. It is not a count shared across Agent turns or across separate chat calls.

## Required Gherkin Feature

The executable feature should express at least the following scenarios.

```gherkin
Feature: Agent runtime state for repeated LLM request failures
  As an agent operator
  I want one request's repeated provider failures to publish bounded runtime state
  So that I can observe a fault without polluting conversation context

  Scenario: The third failed attempt activates retry state
    Given an Agent-owned LLM request whose first three SSE attempts fail and a later attempt is held
    When the first two failed attempts have settled
    Then no LLM retry runtime state is active
    When the third failed attempt has settled
    Then one LLM retry runtime state is active for that request
    And its failed attempt count is 3
    And its threshold is 3

  Scenario: Later failures update one active state
    Given an Agent-owned LLM request that remains retryable after activation
    When five failed attempts have settled
    Then exactly one LLM retry runtime state is active
    And its failed attempt count is 5
    And its revision is greater than the activation revision

  Scenario: Eventual success removes active retry state
    Given an Agent-owned LLM request that succeeds after retry state activation
    When the request returns successfully
    Then no LLM retry runtime state is active
    And bounded runtime history records a recovered retry state

  Scenario: Retry exhaustion removes active retry state
    Given an Agent-owned LLM request that fails through the automatic retry bound
    When the request raises bounded retry exhaustion
    Then no LLM retry runtime state is active
    And bounded runtime history records a failed retry state

  Scenario: A request below the threshold creates no retry-state history
    Given an Agent-owned LLM request that succeeds after two failures
    When the request returns successfully
    Then no LLM retry runtime state is active
    And runtime history contains no retry state for that request

  Scenario: Runtime state never changes provider request messages
    Given an Agent-owned LLM request that succeeds after retry state activation
    When every provider request body is inspected
    Then runtime state fields are absent from every provider message
    And all request messages equal the caller-owned conversation except existing approved recovery behavior

  Scenario: Runtime state excludes sensitive request content
    Given an Agent-owned LLM request containing unique sensitive sentinels
    When retry state and its settled history are inspected
    Then neither snapshot contains any sensitive sentinel

  Scenario: Direct LLM chat without an Agent keeps existing retry behavior
    Given the same retry sequence without a current Agent runtime
    When the direct LLM request completes
    Then the provider request count and result retain their existing contract
    And no Runtime Data publication failure escapes
```

## Harness Design

The harness must own:

- One fake or minimal real `AgentBase` context with one real `AgentRuntime` Store.
- One production `LLMModel` configured for the mock provider.
- One private `llm_mock_server` on loopback port `0`.
- One request-execution thread when observation must occur while `chat()` is blocked.
- Deterministic lifecycle synchronization primitives.
- Captured result or terminal exception.

The harness must not monkeypatch `LLMModel.chat()`, provider parsing, Hook dispatch, or Runtime Data producer logic.

## Deterministic Observation

A final snapshot after `chat()` returns cannot prove the state was active during retry because settlement removes it. Scenarios must observe intermediate state deterministically.

Preferred synchronization:

1. Script request-indexed SSE failures.
2. Use mock-server request handles or Hook-checkpoint Events to know when each failed attempt has settled.
3. Hold the next request at a mock-server lifecycle phase so the request remains active.
4. Query the public Store snapshot while the execution thread is blocked.
5. Release the held request and join the exact execution thread.

Do not use a fixed sleep to guess when failure `3` occurred.

## Provider Scripts

### Activate then hold

- Attempts `1`, `2`, and `3`: retryable SSE failures.
- Attempt `4`: held before first response item.
- Observe active state while attempt `4` is held.
- Release with a successful response for settlement.

### Five failures then success

- Attempts `1` through `5`: retryable SSE failures.
- Attempt `6`: held for observation, then succeeds.
- Assert one active entry, count `5`, and increased revision.

### Below threshold

- Attempts `1` and `2`: retryable failures.
- Attempt `3`: success.
- Assert no active state and no history record.

### Exhaustion

- All automatic attempts: retryable failures.
- Disable manual retry cycles through the existing policy seam.
- Skip retry backoff only through the established scoped clock seam.
- Assert bounded exhaustion and failed history.

## State Value Assertions

While active at failed count `N`, the public state must include:

```text
key = llm.request.retrying
owner_id = current request operation identifier
failed_attempts = N
next_retry_number = N + 1
threshold = 3
last_error_category = bounded class/category token
revision >= 1
```

If implementation defines `next_retry_number` differently, it must remain unambiguous and be approved before executable tests are finalized.

The snapshot must not include:

- request messages
- prompt text
- response text
- API key
- provider endpoint credentials
- complete exception text
- configured null-response recovery content
- Agent object
- LLM model object
- Store or lease object

## Request Settlement Cases

Focused producer tests must prove cleanup for each reachable exit:

### Success

- Active state removed.
- One `recovered` history entry.
- Original result returned unchanged.

### Automatic exhaustion

- Active state removed.
- One `failed` history entry.
- Original `LLMRetryExhaustedError` contract retained.

### Back to chat

- Active state removed.
- One `abandoned` history entry.
- Existing `LLMBackToChatError` behavior retained.

### Explicit Exit

- Active state removed.
- Failed outcome retained.
- Existing explicit-exit marker and caller behavior retained.

### Hard interruption

- Active state removed.
- One `interrupted` history entry.
- Original host interruption is not swallowed or replaced.

### Unexpected exception

- Active state removed.
- One failed outcome.
- Original exception identity and chaining remain intact.

Cleanup is idempotent: a success Hook and request-level finalizer may both attempt settlement, but only one history record is created.

## Configuration Cases

The public variable proposed by the implementation plan is:

```text
TOPSAILAI_LLM_REQUEST_RETRY_STATE_THRESHOLD
```

Tests must cover:

| Value | Expected behavior |
|---|---|
| unset | threshold `3` |
| empty | threshold `3` |
| `3` | activate at failure `3` |
| `1` | activate at failure `1` |
| `0` | producer disabled |
| negative | fallback to `3` |
| non-numeric | fallback to `3` |

The value is resolved once per LLM request. Changing the environment after attempt `1` does not change that request's threshold, but a subsequent request reads the new value.

## Missing Runtime and Failure Isolation

### No current Agent

A direct `LLMModel.chat()` call without `ctxm_set_agent()` performs its existing retries and returns or raises normally. No process-global fallback Store is created.

### Store activation failure

Inject a Store that raises during activation. The request continues its existing retry behavior. A bounded diagnostic is logged without prompt, response, credential, or complete exception text.

### Store update failure

An update failure does not duplicate active entries, alter request messages, or stop provider retries.

### Store settlement failure

The original request result or exception wins. The failure is logged. This case should be designed so a failed removal cannot falsely report a clean active snapshot; exact recovery policy requires implementation review.

## Isolation Cases

### Separate Agents

Run two Agent-owned requests against independently controlled providers. Each Agent sees only its own retry state and history.

### Sequential requests on one Agent

After request A settles, request B starts with no active state from A. A's stale lease cannot remove B's active state.

### Concurrent requests on one Agent

If the runtime supports concurrent `LLMModel.chat()` operations on one Agent, a single-key Store cannot represent both owners without loss. Before executable coverage is finalized, implementation must choose and document one contract:

- Reject overlapping ownership without corrupting the current state;
- Model active entries by key plus owner;
- Or prove one Agent serializes LLM requests and guard that invariant.

The test must match the actual supported concurrency contract and must not silently let one request overwrite another.

## History Capacity Through Real Lifecycle

Given history capacity `3`, execute five qualifying requests that activate and settle. Assert:

- No active state remains.
- Exactly three history entries remain.
- They belong to the three most recently settled request operation identifiers.
- Querying history repeatedly does not grow it.
- A below-threshold request creates no history entry and does not evict a qualifying entry.

This may use a smaller focused integration harness if repeating full 18-attempt exhaustion would be unnecessarily slow; it must still use real HTTP/SSE for each qualifying request.

## Existing Regression Scope

At minimum rerun:

```text
tests/unit/test_topsailai_ai_base_llm_control_llm_retry.py
tests/unit/test_topsailai_null_response_recovery.py
tests/bdd/test_null_response_recovery.py
tests/bdd/test_llm_retry_exhaustion.py
```

The complete retry-exhaustion suite may contain slow scenarios; use its documented marker split and record what was or was not executed.

## Negative Controls

- If activation changes from `failed_attempts >= threshold` to `failed_attempts > threshold`, the third-failure scenario must fail.
- If request settlement cleanup is removed, success and exhaustion scenarios must fail on an active-state leak.
- If later failures call activation instead of lease update, the single-entry/revision scenario must fail.
- If the producer adds state to request messages, provider-body assertions must fail.
- If history trimming is removed, the real-lifecycle capacity scenario must fail.
