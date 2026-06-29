# Duplicate Tool Call Detection Decorator

## 1. Design Goal

Add a decorator at the agent tool execution entry point to detect repeated tool invocations. When a duplicate is detected, wrap the original result in a dictionary with a clear notice so the LLM realizes it is calling the same tool again with the same outcome.

## 2. Duplicate Detection Criteria

A tool call is considered a duplicate when **all three** of the following match between the last two records in the same agent's `ToolStat`:

1. `tool_name` — the tool identifier (e.g. `file_tool-read_file`).
2. `normalized_args` — arguments serialized in a deterministic form.
3. `normalized_result` — the returned value serialized in a deterministic form.

```text
duplicate iff:
  _tool_calls[-1] == _tool_calls[-2]  (same tool_name, same normalized args, same normalized result)
```

Only the immediately preceding tool call is checked. Non-consecutive repeats are intentionally not detected.

### Normalization

Both arguments and results are normalized with the same helper:

```python
@staticmethod
def _normalize(value) -> str:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
    except Exception:
        return str(value)
```

Using the same normalization for both arguments and results is required because different serializers can produce different strings for the same value. For example, for the string result `"hello"`:

| Expression | Output |
|---|---|
| `str("hello")` | `hello` |
| `json.dumps("hello")` | `"hello"` |

If the first call records `"hello"` with `json.dumps` and the second call records `hello` with `str`, the two normalized results no longer match, so a genuine duplicate is missed. Therefore `_normalize()` must be the single source of truth for both `tool_args` and `result`.

Only exact matches count. Calls with different arguments or different results are not duplicates, even if the tool name is the same.

## 3. Where to Place the Decorator

Apply the decorator on `exec_tool_func(tool_func, args, tool_name)` in `/TopsailAI/src/topsailai/ai_base/agent_types/tool.py`.

```python
from topsailai.context.tool_stat import detect_duplicate_tool_call

@detect_duplicate_tool_call
@with_tool_response_safe
@with_tool_approval
def exec_tool_func(tool_func, args, tool_name: str = None):
    ...
```

The `detect_duplicate_tool_call` decorator itself is defined in `/TopsailAI/src/topsailai/context/tool_stat.py` (alongside `ToolStat`, `get_agent_tool_stat()`, and the normalization helper). `tool.py` only imports and applies it.

### Decorator Ordering Rationale

`@detect_duplicate_tool_call` is placed as the outermost decorator so that it runs after the inner decorators have finished executing the tool and truncating the result. `@with_tool_approval` is closest to the function definition and runs first, followed by `@with_tool_response_safe`, which executes the tool and applies result truncation. Finally, `@detect_duplicate_tool_call` reads the most recent records from `ToolStat` and decides whether to re-wrap the result with a duplicate notice.

Execution flow when calling `exec_tool_func(...)`:

1. Enter `detect_duplicate_tool_call` wrapper (outermost).
2. Enter `with_tool_response_safe` wrapper.
3. Enter `with_tool_approval` wrapper.
4. `with_tool_approval` performs approval checks.
5. Approval passes → original `exec_tool_func` runs the tool.
6. `with_tool_response_safe` truncates the result if it exceeds `TOPSAILAI_TOOL_CALL_MAXIMUM_RETURN`.
7. Result propagates back through `with_tool_approval`.
8. `detect_duplicate_tool_call` examines the result, reads `ToolStat` history, and decides whether to wrap it with a notice.

This ordering guarantees that tool approval is evaluated before any tool execution, and that duplicate detection operates on the final result produced by the inner decorators. Because the comparison reads from `ToolStat` records rather than from the value returned by `exec_tool_func`, the decorator can safely re-construct the result after detection without interfering with the inner decorators' execution logic.

### Why Here?

- `exec_tool_func` is the smallest atomic entry point for all tool executions.
- It already receives `tool_name` and `args` and handles result truncation.
- Decorating here avoids touching the more complex `StepCallTool.execute_step_action()` flow.
## 4. Call History Maintenance

The duplicate-detection history is sourced from `ToolStat` instead of a new standalone module.

### Source of History

`/TopsailAI/src/topsailai/context/tool_stat.py`

`ToolStat` already records every tool invocation with `tool_call`, `tool_args`, `result`, and other metadata. We extend it with a duplicate-check helper and a per-agent accessor.

### Proposed Extension to `ToolStat`

```python
class ToolStat:
    # ... existing methods ...

    @staticmethod
    def _normalize(value) -> str:
        try:
            return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)
        except Exception:
            return str(value)

    def is_last_call_duplicate(self) -> bool:
        """
        Check whether the last two tool calls in this agent session are duplicates.

        Returns True only when there are at least two records and the most recent
        record has the same tool_name, normalized arguments, and normalized result
        as the record immediately before it.
        """
        with self._lock:
            if len(self._tool_calls) < 2:
                return False

            last = self._tool_calls[-1]
            prev = self._tool_calls[-2]

            if last.get("tool_call") != prev.get("tool_call"):
                return False
            if self._normalize(last.get("tool_args")) != self._normalize(prev.get("tool_args")):
                return False
            if self._normalize(last.get("result")) != self._normalize(prev.get("result")):
                return False
            return True
```

### Per-Agent Isolation (Mandatory)

The `ToolStat` instance used for duplicate detection must be bound to the current agent instance via `thread_local_tool.get_agent_object()`.

Add a helper in `tool_stat.py`:

```python
def get_agent_tool_stat() -> ToolStat:
    """
    Get or create the ToolStat instance bound to the current agent.

    Falls back to the default global instance when no agent is active.
    """
    from topsailai.utils.thread_local_tool import get_agent_object

    agent = get_agent_object()
    if agent is None:
        return get_default_stat()

    if not hasattr(agent, "_tool_stat"):
        agent._tool_stat = ToolStat()

    return agent._tool_stat
```

Each agent instance gets its own `ToolStat` object. When the agent is garbage collected, the history is released naturally. This prevents cross-agent and cross-session pollution.

### Capacity Limit

The per-agent `ToolStat` reuses the existing capacity-management logic inside `ToolStat.record()`. No additional environment variable is needed for duplicate-detection history size.

### Read-Only Constraint for the Decorator

The `detect_duplicate_tool_call` decorator **must not** write to `ToolStat`. It only reads the most recent records via `is_last_call_duplicate()`. Tool-call recording continues to be performed by the existing `finally` block inside `exec_tool_func`, which calls `tool_stat.get_agent_tool_stat().record(...)` (or the equivalent existing recording path). This avoids double-recording and keeps the decorator a pure detection/wrapping layer.

### Recording Path

`exec_tool_func` currently records tool calls through `tool_stat.record_tool_call(...)`. To ensure duplicate detection uses the same per-agent history, change the recording path to use the agent-bound `ToolStat`:

```python
# Inside exec_tool_func, in the finally block
stat = tool_stat.get_agent_tool_stat()
stat.record(tool_call=tool_name, tool_args=args, result=result)
```

If `record_tool_call()` is the only public API, it should be updated internally to delegate to `get_agent_tool_stat()` rather than `get_default_stat()`. Either way, the invariant is: **the ToolStat instance used for recording must be the same instance used for duplicate detection**.


### Decorator Definition Location

`detect_duplicate_tool_call` is also defined in `/TopsailAI/src/topsailai/context/tool_stat.py`. Keeping it next to `ToolStat`, `get_agent_tool_stat()`, and `_normalize()` keeps all duplicate-detection logic in one place. `ai_base/agent_types/tool.py` imports the decorator and applies it to `exec_tool_func`.
## 5. Detection Logic

The `detect_duplicate_tool_call` decorator is implemented in `/TopsailAI/src/topsailai/context/tool_stat.py`. Because it lives in the same module as `ToolStat` and `get_agent_tool_stat()`, it can read the agent-bound history directly without extra imports.

```python
import logging
from functools import wraps

from topsailai.utils import env_tool

logger = logging.getLogger(__name__)


def detect_duplicate_tool_call(func):
    @wraps(func)
    def wrapper(tool_func, args, tool_name: str = None, **kwargs):
        if not tool_name:
            tool_name = getattr(tool_func, "__name__", "unknown_tool")

        # Execute the original tool function. Because @detect_duplicate_tool_call
        # is the outermost decorator, the inner decorators (@with_tool_approval and
        # @with_tool_response_safe) run first: approval, execution, and result
        # truncation all complete before this point. Any exception raised by func
        # propagates out untouched.
        result = func(tool_func=tool_func, args=args, tool_name=tool_name, **kwargs)

        # Master enable switch.
        if not env_tool.EnvReaderInstance.check_bool(
            "TOPSAILAI_DUP_TOOL_CALL_ENABLED", True
        ):
            return result

        # Get the ToolStat instance bound to the current agent.
        stat = get_agent_tool_stat()

        # Check whether the current call duplicates the immediately preceding one.
        # The decorator is read-only: it does NOT call stat.record().
        is_duplicate = stat.is_last_call_duplicate()

        if is_duplicate:
            logger.warning(
                "Duplicate tool call detected: tool=%s args=%s", tool_name, args
            )

            notice_template = env_tool.EnvReaderInstance.get(
                "TOPSAILAI_DUP_TOOL_CALL_NOTICE", ""
            )
            if notice_template:
                # Only {tool_name} is supported. Use replace() to avoid KeyError
                # when users include other brace pairs in the template.
                notice = notice_template.replace("{tool_name}", tool_name)
                reason = (
                    "Duplicate tool call detected: same tool_name, same arguments, "
                    "and same result as the previous call in this agent session."
                )
                result = {
                    "original_result": result,
                    "notice": notice,
                    "reason": reason,
                }

        return result

    return wrapper
```

## 6. Notice Template and Result Wrapping

### Default Notice Behavior

There is **no built-in notice template**. The default value of `TOPSAILAI_DUP_TOOL_CALL_NOTICE` is an empty string.

- When the variable is **non-empty**, duplicate results are wrapped in a dictionary containing the original result, the rendered notice, and a reason.
- When the variable is **empty or unset**, duplicate detection still occurs internally and a warning is logged, but the original result is returned unchanged. This keeps the feature safe to enable by default without surprising downstream consumers with a return-type change.

### Example Template

A project can configure a custom notice in `env_template`:

```text
TOPSAILAI_DUP_TOOL_CALL_NOTICE="""
---
⚠️ SYSTEM NOTICE: Duplicate tool call detected.

You have already called tool `{tool_name}` with the same arguments, and it returned the same result.
Calling it again is unlikely to yield new information.

Recommended actions:
1. Stop repeating this tool call.
2. Analyze the result you already have.
3. Try a different approach or ask the user for clarification if you are stuck.
---
"""
```

Only the `{tool_name}` placeholder is supported. The implementation uses `str.replace("{tool_name}", tool_name)` so that any other braces in the template do not raise `KeyError`.

### Wrapped Result Format

When a duplicate is detected and `TOPSAILAI_DUP_TOOL_CALL_NOTICE` is non-empty, the original result is wrapped as a dictionary with three explicit keys:

```python
{
    "original_result": <the raw tool result>,
    "notice": "<the rendered English notice>",
    "reason": "Duplicate tool call detected: same tool_name, same arguments, and same result as the previous call in this agent session."
}
```

This is an intentional return-type change: downstream code and the LLM receive a dict instead of the original raw result type. The change is documented here so that callers and tests can rely on the exact key names.

### Example

Original result:

```python
"File content: hello world"
```

Wrapped result:

```python
{
    "original_result": "File content: hello world",
    "notice": "\n---\n⚠️ SYSTEM NOTICE: Duplicate tool call detected.\n\nYou have already called tool `file_tool-read_file` ...",
    "reason": "Duplicate tool call detected: same tool_name, same arguments, and same result as the previous call in this agent session."
}
```

This guarantees the LLM receives both the original data and a clear explanation of why the shape changed.

## 7. Environment Variables (Unified Prefix)

All configuration variables share the prefix `TOPSAILAI_DUP_TOOL_CALL_` for easy searching.

### Naming Rule

- Variables ending with `_ENABLED` are boolean switches.
- Variables without the `_ENABLED` suffix are configuration values or text templates.

| Variable | Default | Type | Description |
|---|---|---|---|
| `TOPSAILAI_DUP_TOOL_CALL_ENABLED` | `1` | switch | Master switch. `1` enables duplicate detection, `0` disables it. |
| `TOPSAILAI_DUP_TOOL_CALL_NOTICE` | `""` | text | Custom notice template. Must be English. Supports only the `{tool_name}` placeholder. When non-empty, duplicate results are wrapped with the notice dictionary. When empty or unset, only a warning log is emitted and the original result is returned unchanged. |

## 8. Relationship with Existing Mechanisms

| Mechanism | Role | Relationship |
|---|---|---|
| `tool_stat` (`/TopsailAI/src/topsailai/context/tool_stat.py`) | Records tool call statistics, errors, and outcomes. | **Reused as the source of duplicate-detection history.** The `ToolStat` class is extended with `is_last_call_duplicate()` and `get_agent_tool_stat()` so the same data structure serves both statistics and duplicate detection. The decorator only reads from `ToolStat`; recording remains the responsibility of `exec_tool_func`. |
| `TOPSAILAI_REFUSE_SEVERE_REPETITION` | Detects severe repetition in LLM response text and raises an error. | Independent. This variable operates on LLM text output, not on tool calls. The new decorator does not depend on it. |
| `TOPSAILAI_TOOL_CALL_MAXIMUM_RETURN` | Truncates oversized tool results. | Truncation happens inside `@with_tool_response_safe`, which is an inner decorator. Therefore the tool result is already truncated before `@detect_duplicate_tool_call` wraps it with the notice dictionary. The notice itself is never truncated, because the wrapper is applied after truncation. |

## 9. Files to Modify

| File | Change |
|---|---|
| `/TopsailAI/src/topsailai/context/tool_stat.py` | **Modify**. Add `_normalize()`, `is_last_call_duplicate()`, `get_agent_tool_stat()`, and define `detect_duplicate_tool_call()` in this module. Keep all existing behavior intact. |
| `/TopsailAI/src/topsailai/ai_base/agent_types/tool.py` | **Modify**. Import `detect_duplicate_tool_call` from `context.tool_stat` and apply it as the outermost decorator on `exec_tool_func` (outside `@with_tool_response_safe` and `@with_tool_approval`). Ensure the existing `finally` block records the call through the agent-bound `ToolStat` instance. |
| `/TopsailAI/src/topsailai/env_template` | **Modify**. Add the two `TOPSAILAI_DUP_TOOL_CALL_*` variables. Provide an example notice template in a comment. |
| `/TopsailAI/src/topsailai/docs/Environment_Variables.md` | **Modify**. Document the two new variables and the `_ENABLED` naming convention. |
| `/TopsailAI/src/topsailai/tests/unit/` | **Add tests**. Cover consecutive duplicate detection, per-agent isolation, notice wrapping, and the disable switch. |

## 10. Pros and Cons

### Pros

- **Minimal intrusion**: only one decorator on `exec_tool_func`.
- **Correct scope**: per-agent `ToolStat` prevents cross-session contamination.
- **Clear LLM feedback**: the wrapped dictionary explicitly separates original data, notice, and reason.
- **Configurable**: behaviors are controlled by environment variables with a unified prefix and a clear `_ENABLED` naming convention.
- **Reuses existing infrastructure**: no new history module; duplicate detection builds on `ToolStat`.
- **Approval-first**: decorator ordering guarantees tool approval runs before duplicate detection.
- **No extra history-size knob**: capacity management stays inside `ToolStat`, reducing configuration surface.
- **Low overhead**: comparing only the last call avoids scanning the full history on every invocation.
- **Exception transparency**: the decorator does not swallow exceptions from `exec_tool_func`; original error semantics are preserved.
- **Read-only decorator**: the decorator never writes to `ToolStat`, avoiding double-recording and keeping concerns separated.

### Cons

- **In-memory only**: history is lost when the agent process ends. This is acceptable for detecting repetition within a single agent run.
- **Exact-match limitation**: only identical arguments and results trigger detection. Semantically equivalent arguments (e.g. `./a` vs `a`) are not normalized beyond JSON serialization.
- **Return type change**: wrapping the result in a dictionary changes the type seen by downstream code. Because wrapping happens after `@with_tool_response_safe` has already truncated the raw result, the wrapped dictionary itself is not subject to further truncation.

## 11. Open Decisions

1. Should there be a rate-limit or consecutive-count threshold before wrapping (e.g. warn on first duplicate, escalate on third)?
2. Should non-string argument types be normalized further (e.g. path canonicalization)?
