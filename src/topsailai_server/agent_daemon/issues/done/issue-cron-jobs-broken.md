---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Cron Jobs Broken: Storage Delegation Methods Missing

## Description
The cron jobs (`message_consumer`, `message_summarizer`, `session_cleaner`) in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/croner/jobs.py` call `self.storage.list_messages()` and `self.storage.list_sessions()`, but the `Storage` class in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/__init__.py` has no such delegation methods. Every cron execution will raise `AttributeError`, causing all background periodic tasks to fail silently or crash.

## Root Cause
The `Storage` class was refactored to use individual managers (`session_manager`, `message_manager`, `task_manager`, `api_key_manager`), but the cron jobs were not updated to use the new manager methods. The `Storage` class lacks delegation methods for `list_messages()` and `list_sessions()`.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/croner/jobs.py`
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/__init__.py`

## Proposed Fix
Add delegation methods to the `Storage` class:
- `list_messages(**kwargs)` -> delegates to `self.message_manager.list_messages(**kwargs)`
- `list_sessions(**kwargs)` -> delegates to `self.session_manager.list_sessions(**kwargs)`

Alternatively, update the cron jobs to call the manager methods directly via `self.storage.message_manager.list_messages()` and `self.storage.session_manager.list_sessions()`.
