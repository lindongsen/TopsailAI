---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Unprocessed Message Format Violates Specification

## Description
The unprocessed message format generated in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py` places `task_id` and `task_result` after the closing `---` separator instead of before it. This violates the specification in `features/00features.md`.

## Expected Format (per spec)
```
---
msg4 content
---
msg5 content
>>> task_id: msg5's task_id
>>> task_result: msg5's task_result
---
```

## Actual Format (current code)
```
---
msg4 content
---
msg5 content
---
>>> task_id: msg5's task_id
>>> task_result: msg5's task_result
```

The `task_id` and `task_result` lines appear after the final `---` separator, but the spec requires them to be inside the last message block, before the closing `---`.

## Root Cause
In `worker/process_manager.py`, the code appends `---` for each message first, then appends task info separately:
```python
for msg in messages:
    parts.append(msg.message)
    parts.append("---")
if task_id:
    parts.append(f">>> task_id: {task_id}")
```

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py`

## Proposed Fix
Restructure the loop to append `task_id`/`task_result` before the final `---` for the last message:
```python
for i, msg in enumerate(messages):
    parts.append(msg.message)
    if i == len(messages) - 1:
        if task_id:
            parts.append(f">>> task_id: {task_id}")
        if task_result:
            parts.append(f">>> task_result: {task_result}")
    parts.append("---")
```
