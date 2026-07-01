# Duplicate Tool Call Detection

## 1. Purpose

Detect when an agent calls the same tool with the same arguments and receives the same result multiple times in a row. When this happens, the system can surface a notice to the agent so it stops repeating the call and analyzes the result it already has.

## 2. Duplicate Detection Criteria

A tool call is considered a duplicate only when it is **immediately consecutive** with the previous call and all of the following match:

1. **Tool name** — the same tool identifier.
2. **Arguments** — the same arguments after deterministic normalization.
3. **Result** — the same returned value after deterministic normalization.

Non-consecutive repeats are intentionally not detected. Arguments and results are normalized using the same deterministic serializer so that equivalent values produce the same comparison key.

## 3. Consecutive Duplicate Count

Each agent's tool-call tracker maintains a consecutive duplicate counter:

| Call | Condition | Count |
|---|---|---|
| S1 | First call | 0 |
| S2 | Duplicate of S1 | 1 |
| S3 | Duplicate of S2 | 2 |
| S4 | Not a duplicate | 0 |

The counter increments by one for each consecutive duplicate and resets to zero as soon as a non-duplicate call is recorded.

## 4. Placement and Scope

Duplicate detection is applied at the single atomic entry point for all tool executions. The detector wraps the tool execution function and inspects the most recent records after the call completes.

The detector is read-only: it never writes to the tool-call history. Recording remains the responsibility of the existing tool execution path.

### Decorator Ordering

The duplicate detector is placed as the outermost decorator so that it runs after inner concerns have completed:

1. Tool approval is evaluated first.
2. The tool executes and its result is truncated if oversized.
3. The duplicate detector inspects the final result and the recent call history.

This ordering guarantees that detection operates on the final, approved, truncated result.

## 5. Per-Agent Isolation

Duplicate detection history is scoped to the current agent instance. Each agent gets its own tool-call tracker, so calls from one agent do not interfere with another. When the agent is released, its history is released with it.

If no agent is active, a module-level fallback tracker is used.

## 6. Notice and Result Wrapping

### Enable Switch

`TOPSAILAI_DUP_TOOL_CALL_ENABLED` is the master switch. When disabled, the detector is bypassed entirely.

### Notice Template

`TOPSAILAI_DUP_TOOL_CALL_NOTICE` is an optional English notice template. When it is non-empty and a duplicate is detected, the original result is wrapped in a dictionary containing:

- `original_result` — the raw tool result.
- `notice` — the rendered notice text.
- `reason` — a short explanation of why the result was wrapped.
- `consecutive_duplicate_count` — the current consecutive duplicate count.

The notice template supports the placeholders `{tool_name}` and `{consecutive_count}`.

When the notice template is empty or unset, duplicate detection still logs a warning internally, but the original result is returned unchanged. This keeps the feature safe to enable by default without surprising downstream consumers with a return-type change.

## 7. Environment Variables

All configuration variables share the prefix `TOPSAILAI_DUP_TOOL_CALL_`.

| Variable | Default | Description |
|---|---|---|
| `TOPSAILAI_DUP_TOOL_CALL_ENABLED` | `1` | Master switch. `1` enables duplicate detection, `0` disables it. |
| `TOPSAILAI_DUP_TOOL_CALL_NOTICE` | `""` | Optional English notice template. Supports `{tool_name}` and `{consecutive_count}`. When non-empty, duplicate results are wrapped with the notice dictionary. |

## 8. Relationship with Existing Mechanisms

| Mechanism | Relationship |
|---|---|
| `tool_stat` | Reused as the source of duplicate-detection history. The detector only reads from it; recording remains the responsibility of the tool execution path. |
| `TOPSAILAI_REFUSE_SEVERE_REPETITION` | Independent. That variable operates on LLM response text, not on tool calls. |
| `TOPSAILAI_TOOL_CALL_MAXIMUM_RETURN` | Result truncation happens before duplicate detection, so the detector compares and wraps the already-truncated result. |

## 9. Open Decisions

1. Should there be a rate-limit or consecutive-count threshold before wrapping (e.g. warn on first duplicate, escalate on third)?
2. Should non-string argument types be normalized further (e.g. path canonicalization)?
