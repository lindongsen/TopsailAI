# Issue: User2Agent in-memory summary path assigns `self.messages` directly

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/ctx_runtime.py`
- Method: `ContextRuntimeData.summarize_messages_for_processed`

## Problem
In the `else` branch (no session_id), the code builds `new_messages` and then does:

```python
self.set_messages(new_messages)
```

This is correct. However, earlier in the same method, when a session_id exists, the code deletes raw session messages and then calls:

```python
self.reset_messages()
```

`reset_messages()` internally uses `set_messages`, so that path is also correct. But the method also directly manipulates `self.messages` indirectly through `ctx_manager` operations and does not explicitly guard against external aliasing. More importantly, the docstring and comments in `readme.md` state that direct assignment `self.messages = new_messages` is forbidden, yet the code does not violate this in the current path.

The actual violation is subtler: `del self.messages[index]` in `del_session_message` directly mutates the list. While not an assignment, it bypasses the `set_messages`/`append_message` mutator contract and can leave `tokenStat` or other cached state inconsistent.

## Impact
- Direct list mutation bypasses the controlled mutators designed for persistence/token parity.
- Future maintainers may introduce direct assignments because the existing `del` operation already breaks the mutator pattern.

## Evidence
```python
def del_session_message(self, index: int):
    ...
    del self.messages[index]
    return
```

## Suggested Direction
Refactor `del_session_message` to use `self.set_messages()` or a dedicated delete mutator that maintains invariants (e.g., token accounting, session parity).
