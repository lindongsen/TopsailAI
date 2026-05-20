---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Worker Process Manager: Tuple Unpack Bug in _get_api_key_environs

## Description
The `_get_api_key_environs()` method in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py` calls `self.storage.api_key_manager.list_api_keys()` which returns `Tuple[List[ApiKeyData], int]`, but the code treats the return value as a single list. This causes API key environment variables to never be injected into processor, summarizer, and checker worker processes.

## Root Cause
`list_api_keys()` returns a tuple `(api_keys, total_count)`, but `_get_api_key_environs()` iterates over the tuple instead of the list. The first iteration gets the list of ApiKeyData objects, and the second gets the integer count, neither of which produces valid API key lookups.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/worker/process_manager.py`

## Proposed Fix
Unpack the tuple correctly:
```python
api_keys, _ = self.storage.api_key_manager.list_api_keys()
for api_key in api_keys:
    ...
```

## Impact
Without this fix, API key-specific environment variables (feature 11) are never passed to worker processes, breaking the per-API-key customization of processor/summarizer/checker behavior.
