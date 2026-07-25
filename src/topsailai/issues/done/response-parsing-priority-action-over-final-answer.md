---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# Response Parsing Priority: Action Should Take Precedence Over Final Answer

## Summary

When parsing an LLM response that contains both `topsailai.action` and `topsailai.final_answer` blocks, the current `format_response` logic appears to prioritize `final_answer` and stop processing further steps. The expected behavior is that `action` should take precedence over `final_answer`, because an `action` indicates the agent still needs to perform work before producing a final answer.

## Observed Behavior

Given a response containing both:

```text
topsailai.action
{"tool_call": "cmd_tool-exec_cmd", "tool_args": {...}}

topsailai.final_answer
The result is ready.
```

The parser returns only the `final_answer` step or treats the response as complete, ignoring the pending `action`.

## Expected Behavior

If any `topsailai.action` block is present in the response, it should be parsed and returned as the active step. `final_answer` should only be considered authoritative when no `action` block exists.

## Impact

This affects the new `topsailai_format_response` CLI and any other consumer of `format_response`. Users see a completed answer when the agent actually intended to invoke a tool, which breaks the ReAct loop.

## Root Cause Hypothesis

The `format_response` function in `../src/topsailai/ai_base/llm_control/message.py` likely scans for `final_answer` first or returns early upon encountering it, without checking whether a subsequent or preceding `action` block exists.

## Suggested Fix

1. Update `format_response` to collect all step blocks first.
2. If the result list contains any `action` step, return only the action steps (or mark the action as the active step).
3. Return `final_answer` only when no `action` is present.

## Files to Investigate

- `../src/topsailai/ai_base/llm_control/message.py` (source of `format_response`)
- `topsailai_format_response.py` (CLI wrapper)
- `tests/unit/topsailai_format_response/test_topsailai_format_response.py` (add regression test)

## Status

Pending investigation and fix.
