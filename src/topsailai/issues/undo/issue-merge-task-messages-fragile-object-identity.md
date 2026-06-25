# Issue: `_merge_task_messages` relies on `id()` identity, which is fragile across serialization

## Status
**undo / deferred**

- Deferred by: Human.DawsonLin
- Deferred at: 2026-06-25
- Reason: Not handling this issue for now. The current implementation works because callers share object references; serialization round-trips are not currently introduced in the summarization path. Will revisit if/when messages are serialized between snapshot and merge.

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/base.py`
- Method: `ContextRuntimeBase._merge_task_messages`

## Problem
The merge logic uses Python object identity (`id(msg)`) to detect which messages survived summarization and where to insert the head_portion:

```python
task_ids = {id(m) for m in task_messages}
original_ids = {id(m) for m in original_messages}
new_ids = {id(m) for m in new_messages}
```

If any message was serialized/deserialized (e.g., JSON dump/load) between `original_messages` and `new_messages`, its object identity changes and the merge will misplace or duplicate head messages. The current code does create `original_messages = list(messages)` and reuses objects, but downstream code (or future changes) may easily break this assumption.

## Impact
- Head/task messages can be duplicated or lost after summarization.
- Hard to debug because the bug depends on whether messages were copied.

## Evidence
```python
task_ids = {id(m) for m in task_messages}
original_ids = {id(m) for m in original_messages}
new_ids = {id(m) for m in new_messages}
...
if _id not in original_ids:
    summary_index = i
```

## Root Cause
The merge helper treats object identity as a stable surrogate for "same message slot". Python `id()` is only stable for the lifetime of a single object reference; any copy, deep-copy, JSON round-trip, or reconstruction creates a new object with a new identity. The current code happens to work only because `original_messages = list(messages)` keeps references to the same dict objects and `_summarize_messages` returns a list that still contains some of those original references. This coupling is implicit and easy to break.

## Proposed Change: Index-Based Tracking
Replace identity checks with index-based tracking:

1. Before summarizing, record `task_indices` as positions in `original_messages` for all task messages.
2. After summarization, build a mapping from each surviving message to its original index by comparing values (or by carrying an explicit `__index` marker during the summarize step).
3. Detect the summary message as the first new message that cannot be mapped to an original index.
4. Re-insert any head-portion messages whose original indices are missing from the surviving prefix, at the correct positions.

This removes the dependency on object identity and makes the merge robust against copying or serialization.

## Alternative Considered
Simplify the summarization contract so the summarizer explicitly returns:

```python
new_messages = head_offset_messages + keeping_messages + [summary_answer] + [last_user_message]
```

This avoids the need for a separate merge helper entirely. However, it changes the current interleaving behavior: task messages that currently survive inside the summarized region would no longer be preserved in their original positions. Evaluate whether that behavior is required before adopting this alternative.

## Suggested Direction
Use a stable message identifier (e.g., a monotonic index or a content hash) instead of `id()`. Pass indexes rather than object references through the merge helper.

## Tests to Add
1. **Unit tests for `_merge_task_messages`**: cover normal merge, empty head portion, all task messages summarized away, and duplicate content values.
2. **JSON round-trip integration tests**: for both `ContextRuntimeData.summarize_messages_for_processed()` and `ContextRuntimeAgent2LLM.summarize_messages_for_processing()`, simulate a chat-history manager that serializes messages to JSON and back before summarization, then assert head/task messages remain correctly placed.

## Notes
- No code fix implemented yet.
- Deferral is acceptable while messages are not serialized in the summarization path, but any future change that copies or serializes messages will reactivate this risk.
