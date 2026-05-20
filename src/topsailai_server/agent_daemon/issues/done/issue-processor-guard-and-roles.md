---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Processor Flow: "All Assistant" Guard is Dead Code and UNPROCESSED_MSG_INCLUDED_ROLES Ignored

## Description
Two related bugs exist in the processor flow in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py`:

### Bug 1: "All Assistant" Guard is Dead Code
The infinite-loop prevention check (step 2 of the processor flow) checks if all messages between `processed_msg_id` and the latest message have `role=assistant`. However, this check runs **after** assistant messages have already been filtered out when building the unprocessed messages list. Therefore, the check can never trigger — if all messages were assistant, the unprocessed list would be empty and the code would have already exited.

### Bug 2: UNPROCESSED_MSG_INCLUDED_ROLES Ignored
The processor hardcodes skipping only messages with `role="assistant"`, ignoring the configurable environment variable `TOPSAILAI_AGENT_DAEMON_UNPROCESSED_MSG_INCLUDED_ROLES`. This env var should control which roles are included in unprocessed messages, but the code never reads it.

## Root Cause
1. The guard check was placed after message filtering instead of before.
2. The role filtering uses a hardcoded string `"assistant"` instead of reading from the environment variable.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py`

## Proposed Fix
1. Move the "all assistant" guard check to run on the **raw** message list (before filtering), or check if the filtered list is empty after applying the configured role filter.
2. Read `UNPROCESSED_MSG_INCLUDED_ROLES` from environment variables (default: `"user"`) and use it to filter messages:
```python
included_roles = os.environ.get("TOPSAILAI_AGENT_DAEMON_UNPROCESSED_MSG_INCLUDED_ROLES", "user").split(",")
included_roles = [r.strip() for r in included_roles]
```

## Impact
- Without fix 1: Infinite loops could occur if a processor generates assistant messages that trigger further processing.
- Without fix 2: Users cannot customize which message roles are included in unprocessed messages, limiting flexibility.
