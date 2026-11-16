---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Runtime Instruction Test Cases

## Scope

These cases verify human-facing, read-only access to one current Agent's public Runtime Data. They do not repeat Store ownership or LLM retry policy tests.

## Command Contract

The first version provides:

```text
/runtime [json=1]
/runtime.get <key> [json=1]
/runtime.history [key] [json=1]
```

The command names are exact. They must be discoverable through the existing Instruction registry and must not shadow `/ctx.*`, `/session.*`, or `/agent.tokens`.

### Parameter Contract

`json=1` selects JSON output; `json=0` and an omitted flag both select text output. The flag is accepted in two forms because two transports deliver arguments differently:

- Terminal dispatch delivers named parameters as keyword arguments.
- The control channel forwards one `;`-separated token, so `key=llm.request.retrying;json=1` arrives as a single positional argument.

Both forms must produce identical output. `;` is the only parameter separator; a space-separated form such as `key=x json=1` is not a valid named-parameter string. An unknown named parameter reports usage instead of being silently ignored.

### JSON Output Contract

JSON mode returns a string so terminal printing emits valid JSON. Every response carries `ok`:

```text
{"ok": true, "active": [{"key": ..., "revision": ..., "updated_at_ms": ..., "value": {...}}]}
{"ok": true, "active": {"key": ..., "revision": ..., "updated_at_ms": ..., "value": {...}}}
{"ok": true, "history": [{"key": ..., "outcome": ..., "revision": ..., "settled_at_ms": ..., "value": {...}}]}
{"ok": false, "error": "no_runtime"}
{"ok": false, "error": "not_found", "key": ...}
{"ok": false, "error": "invalid_key"}
{"ok": false, "error": "unknown_parameter", "usage": ...}
{"ok": false, "error": "too_many_arguments", "usage": ...}
{"ok": false, "error": "missing_key", "usage": ...}
```

`value` contains only the same approved diagnostic fields as text mode. JSON mode must not become a path around the display allowlist: `owner_id`, lease generation, and arbitrary payload fields stay absent.

## Required Gherkin-Style Behavior

```gherkin
Feature: Read-only inspection of Agent Runtime Data
  As an agent operator
  I want concise runtime-state Instructions
  So that I can inspect active and recently settled public states safely

  Scenario: Runtime lists active public states
    Given the current Agent has one public active state and one private active state
    When the operator invokes /runtime
    Then the output shows the public state
    And the output does not show the private state

  Scenario: Runtime reports no active state after request settlement
    Given an LLM retry state activated and its request has ended
    When the operator invokes /runtime
    Then the output says no active runtime states exist

  Scenario: Runtime get returns one active public state
    Given the current Agent has an active public llm.request.retrying state
    When the operator invokes /runtime.get llm.request.retrying
    Then the output shows that state's public snapshot

  Scenario: Runtime get does not expose private or missing state
    Given the requested key is private or absent
    When the operator invokes /runtime.get for that key
    Then the output returns the same concise not-found contract

  Scenario: Runtime history shows only bounded settled public records
    Given more public states have settled than the configured history capacity
    When the operator invokes /runtime.history
    Then only the newest retained public records are shown
    And private history is absent

  Scenario: Runtime history filters by exact key
    Given settled public records exist for multiple state keys
    When the operator invokes /runtime.history llm.request.retrying
    Then only exact matching records are shown

  Scenario: Runtime Instructions are unavailable outside an Agent context
    Given no current Agent is bound
    When any Runtime Instruction is invoked
    Then it returns a concise no-runtime response without raising

  Scenario: Runtime returns machine-readable JSON on request
    Given the current Agent has one public active state
    When the operator invokes /runtime json=1
    Then the output parses as JSON with ok true
    And the value contains only approved diagnostic fields
    And no lease token or owner identity appears

  Scenario: Runtime JSON reports a structured error
    Given no current Agent is bound
    When the operator invokes /runtime json=1
    Then the output parses as JSON with ok false
    And the error token is no_runtime
```

## Registration Cases

### Commands are discovered once

The Instruction registry maps exact names to callables:

- `runtime`
- `runtime.get`
- `runtime.history`

No duplicate alias is added for the same behavior unless separately approved.

### Existing commands remain registered

Loading Runtime Instructions does not remove or replace existing plugin Instructions.

### Help inventory includes Runtime commands

The existing `/help` output lists each command once with concise usage.

## `/runtime` Cases

### Empty active state

Expected meaning:

```text
No active runtime states.
```

Exact capitalization may follow existing Instruction style, but output must be stable and tested.

### One public active state

Output includes:

- key
- active indication or equivalent unambiguous presentation
- failed attempt count when present in the public value
- threshold when present
- bounded error category when present
- revision
- updated timestamp

Output excludes:

- lease token or generation secret
- Store object identity
- Agent object identity
- private state
- raw prompt or response
- API key
- complete exception text

### Multiple states

States appear in the Store's deterministic snapshot order. Formatting does not hold the Store lock while producing text.

## `/runtime.get` Cases

### Valid active public key

Returns only that key's public snapshot.

### Missing argument

Returns concise usage:

```text
Usage: /runtime.get <key>
```

### Extra arguments

Reject or join arguments according to the Instruction framework's established positional contract. Because runtime keys cannot contain spaces, rejecting extra arguments is preferred and must be tested.

### Missing key

Returns a concise not-found result without revealing whether a private state with that key exists.

### Invalid key text

Control characters, whitespace-only values, and malformed namespaced keys are rejected without querying or mutating the Store.

## `/runtime.history` Cases

### Empty history

Returns a concise no-history result.

### Bounded history

When Store history capacity is `3` after five settlements, output contains exactly the retained three public records and no evicted record.

### Exact key filter

Filtering uses exact key equality, not prefix, substring, regular expression, or case-folded matching.

### Missing filter

No argument means all retained public history.

### Private history

Private settled records are omitted. Their existence is not disclosed through counts or not-found differences.

## JSON Output Cases

### JSON mode is parseable

Every JSON response parses with a standard JSON parser and carries a boolean `ok`. Text mode output is never valid JSON and JSON mode output is never a Python repr.

### JSON mode preserves the display allowlist

`value` contains only the approved diagnostic fields. A payload carrying `prompt`, `response`, `api_key`, `exception`, or a nested object must not leak those fields, and `owner_id` and lease generation must stay absent. This case exists because JSON serialization is the obvious place to bypass a text-only allowlist.

### JSON mode reports structured errors

`no_runtime`, `not_found`, `invalid_key`, `unknown_parameter`, `too_many_arguments`, and `missing_key` are machine-readable tokens. A consumer must be able to distinguish "no Agent" from "no active state" without matching English sentences.

### Both transports agree

The keyword form and the single forwarded `;`-separated token produce identical JSON. A space-separated named-parameter string is not a supported form.

### `json=0` equals an omitted flag

`json=0` and an omitted flag produce byte-identical text output. A truthiness check must not treat the string `"0"` as enabled.

## Read-Only Enforcement

### No mutation methods are called

Use a spy Store whose mutation methods fail the test. Every Runtime Instruction may call only query methods.

### Returned text cannot mutate the Store

Formatting nested values, sorting output, or serializing snapshots operates on detached data.

### Repeated queries are side-effect free

Repeated `/runtime`, `/runtime.get`, and `/runtime.history` invocations leave active count, revisions, and history unchanged.

## Current-Agent Resolution

### Bound Agent

Instructions resolve the Agent already bound by the existing Instruction Agent cache and read `agent.runtime.runtime_data`. Context-local chat binding takes precedence over the chat-level fallback, so concurrent chats do not borrow each other's Runtime Data while handling an Instruction.

### No bound Agent

When the Instruction Agent cache has no Agent, Instructions return no-runtime and do not create an Agent, Store, or process-global Runtime Data fallback.

### Unavailable Runtime

If the bound Agent has no available Runtime Data Store, the query maps to no-runtime and does not expose a stack trace to the terminal.

## Lifecycle Presentation

### Active during retry

When invoked from a test-controlled context while the LLM request is held after failure `3`, `/runtime` displays `llm.request.retrying`.

### Absent after request settlement

After the same request returns or raises, `/runtime` displays no active retry state.

### Settled record remains bounded

After settlement, `/runtime.history llm.request.retrying` displays the retained terminal outcome until bounded history eviction removes it.

The live-during-retry case may be covered by the LLM BDD harness plus direct handler invocation; it must not depend on the ordinary single-thread terminal input loop accepting a second command while blocked.

## Information-Safety Cases

Populate internal and public values with unique sentinels. Assert output omits:

- private-state sentinel
- lease-token sentinel
- prompt sentinel
- response sentinel
- credential sentinel
- complete-exception sentinel

If a generic public value intentionally contains arbitrary strings, the Store admission contract must define what fields are public. Instruction formatting must not blindly dump an unbounded dictionary.

## Output Bounds

Instruction output must be bounded by Store capacities and per-field display limits. Tests should include:

- Maximum retained history.
- An overlong key or category rejected at Store admission.
- Nested public values limited by the state schema.
- No recursive or binary values.

The Instruction layer must not add an independent unbounded cache.

## Regression Scope

Run focused Runtime Instruction tests plus existing Instruction registration and context command tests. Candidate existing scope must be discovered before execution, including:

```text
tests/unit/workspace/plugin_instruction/
tests/unit/workspace/context/
tests/unit/test_topsailai_workspace_context_instruction.py
```

Only paths that actually exist are executed.

## Negative Controls

- If public filtering is removed, the private-state scenario must fail.
- If a mutation method is called, the read-only spy test must fail.
- If current-Agent resolution falls back to process-global state, the no-Agent isolation test must fail.
- If history output bypasses Store capacity, the bounded-history scenario must fail.
- If settled active state remains visible, the lifecycle presentation test must fail.
- If JSON mode serializes the raw snapshot instead of the allowlisted fields, the JSON allowlist case must fail.
- If the `json` flag is resolved after parameter validation, an unknown parameter combined with `json=1` must return text instead of JSON, and the structured-error case must fail.
- If the forwarded `;`-separated token is split only on `=`, the flag is glued into the key value and the transport-agreement case must fail.
- If `json` is tested with a plain truthiness check, `json=0` enables JSON and the disabled-flag case must fail.
