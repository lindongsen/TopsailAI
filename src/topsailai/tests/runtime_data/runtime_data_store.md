---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Runtime Data Store Test Cases

## Scope

These cases verify the generic Agent-scoped Store independently of LLM retry policy and terminal rendering.

## Public Contract Under Test

The concrete names may differ, but the public behavior must support:

```text
activate(key, owner_id, value, public) -> lease
update(lease, value) -> success or rejected result
remove(lease, outcome) -> success or rejected result
get(key, public_only) -> detached snapshot or absent
snapshot(public_only) -> detached active snapshots
history(key, public_only) -> detached settled snapshots
```

Mutation APIs must not expose the internal active-state dictionary. Query APIs must not return mutable references owned by the Store.

## Data Validation Cases

### Accept a valid namespaced state

Given a new Store and a JSON-compatible payload,
when `llm.request.retrying` is activated for one owner,
then one active snapshot exists with the same key and owner, revision `1`, ordered timestamps, and a detached value.

### Reject an invalid key without mutation

Invalid cases include empty, whitespace-only, non-string, control-character, leading/trailing separator, and non-namespaced keys.

For each invalid key:

- Activation reports a stable validation failure.
- Active count remains zero.
- History count remains zero.

### Reject an invalid owner without mutation

Empty, whitespace-only, non-string, or over-limit owners are rejected before state mutation.

### Reject non-JSON-compatible values without partial state

Values containing unsupported objects, non-string dictionary keys, recursion, or non-finite numeric values are rejected. The Store must not retain a partially copied value.

### Detach accepted values

After activation, mutating the caller's original nested dictionary or list does not alter the stored snapshot.

## Lifecycle Cases

### Activate, update, and remove one state

Given one active leased state:

- A matching update changes the value.
- Revision increases by exactly one.
- `created_at_ms` remains unchanged.
- `updated_at_ms` is not earlier than its previous value.
- A matching remove makes the key absent from active snapshots.
- One settled history record contains the terminal revision and requested outcome.

### Repeated remove is idempotent

Removing the same lease twice does not create duplicate history and does not raise into a caller cleanup path.

### Update after remove is rejected

A settled lease cannot recreate or alter an active state through `update`.

### Remove an unknown lease without side effects

An unknown key, owner, or generation changes neither active state nor history.

### Private state remains private

A private state is visible only through an explicit internal query. It is absent from public `get`, active snapshot, and public history.

## Lease Ownership Cases

### A stale lease cannot update a replacement

Given owner A activates a key and the key is later legitimately owned by generation B,
when A updates using the old lease,
then B's value and revision remain unchanged.

### A stale lease cannot remove a replacement

Given the same replacement arrangement,
when A performs delayed cleanup,
then B remains active and no history record is created for B.

### One owner cannot guess another lease

Matching key and owner text without matching generation/token is insufficient for update or removal.

## Capacity Cases

### Active-state capacity is bounded

Given an active capacity of `N`,
when `N` distinct keys are active,
then activation of another key follows the documented deterministic full-capacity policy and never silently removes a currently owned state.

Preferred first-version policy: reject the new activation with no mutation. If implementation chooses another policy, it requires review and explicit tests.

### Settled history retains only the newest configured count

Given history capacity `3`,
when five states are activated and settled in order,
then:

- History length is exactly `3`.
- Entries for settlements `1` and `2` are absent.
- Entries `3`, `4`, and `5` remain in settlement order.
- Active state is empty.
- Additional queries do not increase history.

### Zero history capacity stores no settled records

If zero is an allowed constructor value, removal still clears active state but retains no history. If zero is invalid, constructor validation must reject it clearly; the selected contract must be tested and documented.

### Invalid capacity values fail before construction completes

Negative, boolean, non-integer, and unreasonably large capacity values follow one documented validation rule.

## Snapshot Isolation Cases

### Mutating an active snapshot cannot mutate the Store

Modify nested values, reorder returned lists, and remove fields from a returned snapshot. A fresh snapshot remains unchanged.

### Mutating a history snapshot cannot mutate history

The same isolation applies to settled records.

### Snapshot order is deterministic

Active snapshots use a documented order, preferably key order or activation order. History uses settlement order. Repeated queries without mutation return the same order.

## Revision and Clock Cases

### Revision is monotonic within a generation

Activation starts at revision `1`; each successful update increases it exactly once; rejected updates do not consume a revision.

### Replacement generation does not accept the old revision stream

A replacement state has a distinct lease generation. Whether its displayed revision restarts at `1` or uses a Store-wide sequence must be documented; stale lease rejection must not depend only on the displayed revision.

### Clock seam permits deterministic timestamps

Inject a monotonic or wall-clock seam so tests can prove `created_at_ms` stability and `updated_at_ms` progression without sleeping.

## Concurrency Cases

### Concurrent updates through one valid lease do not corrupt the state

Use a barrier to start multiple worker threads. Every successful update produces one complete JSON-compatible value and a unique revision transition; the final record is structurally valid and no exception escapes.

The test must not require a specific thread scheduling order unless the Store API explicitly guarantees it.

### Snapshot during updates is internally consistent

Repeated snapshots taken while another thread updates never contain partial nested values, mismatched revision/value pairs, or iteration errors.

### Concurrent stale cleanup cannot remove a replacement

Synchronize replacement activation and delayed old-owner removal with Events or barriers. The replacement remains active after the stale cleanup attempt.

## AgentRuntime Composition Cases

### Each Agent gets one independent Store

Create two fake Agents and two `AgentRuntime` instances. Activating a state in the first does not affect the second.

### Injected Store is preserved

Supplying a Store to `AgentRuntime` for testing exposes that exact instance without altering existing dynamic Agent accessors.

### Default Store is created once

Repeated access through one `AgentRuntime` returns the same Store object.

### Weak Agent ownership remains unchanged

The Store must not capture the Agent strongly. Releasing the Agent still allows the existing weak-reference test to pass.

## Negative Controls

At least one test must demonstrate that removing generation/token validation causes stale cleanup to delete a replacement state.

At least one test must demonstrate that returning an internal nested value directly allows snapshot mutation to corrupt the Store.

At least one test must demonstrate that removing history trimming grows history beyond the configured maximum.

Negative controls may be mutation tests, local substitute implementations, or review-time temporary reversions; they must not remain in production code.

## Focused Verification

The checklist should run, without color:

```text
pytest -q --tb=line --disable-warnings --color=no tests/unit/test_topsailai_ai_base_runtime_data.py
pytest -q --tb=line --disable-warnings --color=no tests/unit/test_topsailai_ai_base_agent_runtime.py
pytest -q --tb=line --disable-warnings --color=no tests/unit/test_topsailai_ai_base_agent_base.py
```

Exact existing AgentBase test paths must be confirmed before execution rather than assumed.
