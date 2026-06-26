# Issue: User2Agent interactive summary returns `answer` when user rejects it

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/ctx_runtime.py`
- Method: `ContextRuntimeData.summarize_messages_for_processed`

## Problem
The interactive confirmation block contains inverted logic:

```python
while True:
    yn = input(">>> Is this answer acceptable? [yes/no] ").lower().strip()
    if not yn:
        continue
    if yn != "yes":
        return answer
    break
```

If the user answers anything other than "yes" (e.g., "no"), the method returns `answer` immediately and still proceeds to persist the summary and delete history. The intended behavior is likely to abort summarization when the user says "no".

## Impact
- User rejection of a summary is ignored; the summary is still applied and session history is deleted.
- Data loss: the original session messages are removed even when the user explicitly rejects the summary.

## Evidence
```python
if yn != "yes":
    return answer
break
```

## Suggested Direction
Invert the logic so that only "yes" continues with summarization, and any other answer aborts (return `None` or raise a cancellation exception) before deleting session messages.
