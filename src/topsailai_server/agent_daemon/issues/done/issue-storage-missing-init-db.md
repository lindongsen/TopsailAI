---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Storage Class Missing init_db() Method

## Description
The `Storage` class in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/__init__.py` is missing the `init_db()` method that was previously available. This breaks legacy unit tests and any code that calls `storage.init_db()` to initialize database tables.

## Root Cause
During refactoring to use individual managers, the `init_db()` method was removed from the `Storage` class. The method should delegate to the migration module or individual managers to create all required tables.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/storage/__init__.py`
- Legacy unit tests that call `storage.init_db()`

## Proposed Fix
Add `init_db()` method to the `Storage` class:
```python
def init_db(self):
    """Initialize all database tables."""
    from .migration import migrate
    migrate(self.engine)
```

## Impact
Legacy unit tests and any external code relying on `Storage.init_db()` will fail with `AttributeError`. This affects backward compatibility.
