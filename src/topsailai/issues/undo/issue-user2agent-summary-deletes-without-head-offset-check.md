# Issue: User2Agent summary deletes session messages without honoring `head_offset_to_keep`

## Location
- File: `/TopsailAI/src/topsailai/workspace/context/ctx_runtime.py`
- Method: `ContextRuntimeData.summarize_messages_for_processed`

## Problem
When `self.session_id` exists, the method deletes raw session messages using:

```python
for raw_msg in raw_messages_from_session[head_offset_to_keep:]:
    ...
    ctx_manager.del_session_messages(self.session_id, [raw_msg.msg_id])
```

It then calls `self.reset_messages()`. However, the in-memory `self.messages` is **not** explicitly rebuilt with the head offset kept; it is simply reloaded from the now-truncated session store. The summary answer is added to the session, but the head offset messages are not guaranteed to be the same objects or count as the caller requested.

More importantly, the code computes `head_offset_to_keep` and then unconditionally slices `raw_messages_from_session[head_offset_to_keep:]` for deletion. If `head_offset_to_keep` is larger than the number of messages before the first task message, important task/head messages can be deleted because the keep-list (`raw_msg_ids_to_keep`) only protects messages up to the first task message, not the configured head offset.

## Impact
- The User2Agent session may end up with fewer head messages than configured.
- The protected head-portion logic and `head_offset_to_keep` are inconsistent in the session-persistence path.

## Evidence
```python
head_offset_to_keep = self._get_head_offset_to_keep_in_summary(head_offset_to_keep)
if head_offset_to_keep and len(self.messages) <= head_offset_to_keep:
    head_offset_to_keep = 1
...
for raw_msg in raw_messages_from_session[head_offset_to_keep:]:
    if last_user_raw_msg and raw_msg.msg_id == last_user_raw_msg.msg_id:
        continue
    if raw_msg_ids_to_keep and raw_msg.msg_id in raw_msg_ids_to_keep:
        continue
    ctx_manager.del_session_messages(self.session_id, [raw_msg.msg_id])
```

## Suggested Direction
Rebuild the in-memory `self.messages` explicitly after session deletion (using `set_messages`) and ensure the head-offset keep logic is aligned with the head-portion preservation logic. Consider keeping `max(head_offset_to_keep, len(raw_msg_ids_to_keep))` head messages.


---

## Status

**undo / invalid as described**

- **Reason:** The deletion loop `raw_messages_from_session[head_offset_to_keep:]` already preserves the first `head_offset_to_keep` raw session messages. The `raw_msg_ids_to_keep` list provides additional protection for messages up to the first task message. The two mechanisms are complementary, not conflicting. No head/task messages are deleted beyond the configured head offset.
- **Note:** A separate observation: the fallback `head_offset_to_keep = 1` when `len(self.messages) <= head_offset_to_keep` may be surprising, but that is not the bug described in this issue.
- **Verified by:** AIMember.km2-reviewer
- **Date:** 2026-06-26
