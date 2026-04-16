---
maintainer: AI
---

# Code Improvement Proposal - Agent Daemon

## 1. Project Overview

### 1.1 Brief Description

**agent_daemon** is a message orchestration service that receives user messages and automatically schedules AI agents to process them. The CLI name is `topsailai_agent_daemon`, running in background mode.

**Core Capabilities:**
- Manage user conversation messages
- Automatically process conversation messages, launching new `TOPSAILAI_AGENT_DAEMON_PROCESSOR` processes at appropriate times
- SQLAlchemy-based storage for session and message management
- RESTful HTTP API on port 7373
- Croner for periodic tasks (message consumption, summarization, cleanup)

### 1.2 Current Implementation Status

| Component | Status | Location |
|-----------|--------|----------|
| Storage | ✅ Complete | `storage/session_manager/`, `storage/message_manager/` |
| Configer | ✅ Complete | `configer/env_config.py` |
| Http API | ✅ Complete | `api/routes/session.py`, `api/routes/message.py`, `api/routes/task.py` |
| Croner | ✅ Complete | `croner/scheduler.py`, `croner/jobs/*.py` |
| Worker | ✅ Complete | `worker/process_manager.py` |
| CLI - Daemon | ✅ Complete | `topsailai_agent_daemon.py` |
| CLI - Client | ⚠️ Needs Refactor | `topsailai_agent_client.py` (monolithic) |
| Client Modules | ❌ Missing | `client/` folder structure |

---

## 2. Required Implementation

### 2.1 Client Folder Structure Refactoring

**New Requirement:** Organize client operations into `{workspace}/client/` folder with separate modules:

```
{workspace}/client/
├── __init__.py      # Package initialization, exports main classes/functions
├── base.py          # Base client class, common utilities (format_time, SPLIT_LINE, etc.)
├── session.py       # Session operations (list-sessions, get-session, delete-sessions, process-session)
├── message.py       # Message operations (send-message, list-messages)
└── task.py          # Task operations (set-task-result, list-tasks)
```

**Files to Create:**

#### 2.1.1 `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/client/__init__.py`
- Package initialization
- Export main client classes and functions
- Define version info

#### 2.1.2 `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/client/base.py`
**Purpose:** Base client functionality and common utilities

**Contents:**
- `DEFAULT_HOST`, `DEFAULT_PORT`, `DEFAULT_SESSION_ID` constants
- `SPLIT_LINE` constant
- `format_time(time_str)` function - Format time to "YYYY-MM-DD HH:MM:SS" (seconds only)
- `BaseClient` class:
  - `__init__(host, port, verbose=False)`
  - `base_url` property
  - `_make_request(method, url, **kwargs)` - Common request handling with error handling
  - `_handle_connection_error()` - Connection error handler
  - `_print_response(data, verbose)` - Response printer

#### 2.1.3 `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/client/session.py`
**Purpose:** Session-related client operations

**Contents:**
- `SessionClient` class inheriting from `BaseClient`
- `list_sessions(**filters)` - List all sessions with filtering
  - Support: session_ids, start_time, end_time, offset, limit, sort_key, order_by
  - Display format: When session_id == session_name, only show one
  - Format: `[create_time] session_id: session_name` (or just session_id if same)
  - Show task content and processed_msg_id
- `get_session(session_id)` - Get single session by ID
  - Display format: Show all session fields including status
- `delete_sessions(session_ids)` - Delete sessions
- `process_session(session_id)` - Process pending messages for a session

#### 2.1.4 `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/client/message.py`
**Purpose:** Message-related client operations

**Contents:**
- `MessageClient` class inheriting from `BaseClient`
- `send_message(session_id, message, role='user', processed_msg_id=None)` - Send a message
- `list_messages(session_id, **filters)` - List messages for a session
  - Support: start_time, end_time, offset, limit, sort_key, order_by
  - Display format:
    ```
    [create_time] [msg_id] [role]
    message content (full, not truncated)
    
    >>> task_id: xxx
    >>> task_result:
    content
    ```
  - Time format: Only show up to seconds
  - Show complete message content, do not omit
  - Show task_id and task_result if present

#### 2.1.5 `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/client/task.py`
**Purpose:** Task-related client operations

**Contents:**
- `TaskClient` class inheriting from `BaseClient`
- `set_task_result(session_id, processed_msg_id, task_id, task_result)` - Set task result
- `list_tasks(session_id, **filters)` - List tasks for a session
  - Support: task_ids, start_time, end_time, offset, limit, sort_key, order_by
  - Display format:
    ```
    [create_time] task=[task_id] session=[session_id] msg=[msg_id]
    Task: message content (full)
    ---
    task_result
    ```
  - Show complete message content
  - Show session_id and msg_id

### 2.2 Refactor topsailai_agent_client.py

**File to Modify:** `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/topsailai_agent_client.py`

**Changes:**
1. Import client classes from `client` package
2. Refactor each `do_client_*` function to use the new client classes
3. Keep CLI argument parsing and subcommand setup
4. Remove duplicate code (format_time, request handling, etc.) - move to client modules

**Example Refactor Pattern:**
```python
from topsailai_server.agent_daemon.client.session import SessionClient
from topsailai_server.agent_daemon.client.message import MessageClient
from topsailai_server.agent_daemon.client.task import TaskClient

def do_client_list_sessions(args):
    """List sessions"""
    client = SessionClient(host=args.host, port=args.port, verbose=args.verbose)
    return client.list_sessions(
        session_ids=args.session_ids,
        start_time=args.start_time,
        end_time=args.end_time,
        offset=args.offset,
        limit=args.limit,
        sort_key=args.sort_key,
        order_by=args.order_by
    )
```

---

## 3. Implementation Checklist

### Phase 1: Create Client Package Structure

| # | Task | File | Priority |
|---|------|------|----------|
| 1 | Create client package directory | `client/` | 🔴 High |
| 2 | Create package init file | `client/__init__.py` | 🔴 High |
| 3 | Create base client module | `client/base.py` | 🔴 High |
| 4 | Create session client module | `client/session.py` | 🔴 High |
| 5 | Create message client module | `client/message.py` | 🔴 High |
| 6 | Create task client module | `client/task.py` | 🔴 High |

### Phase 2: Refactor Client CLI

| # | Task | File | Priority |
|---|------|------|----------|
| 7 | Refactor topsailai_agent_client.py to use new client modules | `topsailai_agent_client.py` | 🔴 High |
| 8 | Remove duplicate code from topsailai_agent_client.py | `topsailai_agent_client.py` | 🟡 Medium |

### Phase 3: Testing

| # | Task | Description |
|---|------|-------------|
| 9 | Unit Test | Test SessionClient.list_sessions() |
| 10 | Unit Test | Test SessionClient.get_session() |
| 11 | Unit Test | Test MessageClient.list_messages() with task display |
| 12 | Unit Test | Test TaskClient.list_tasks() with message display |
| 13 | Integration Test | Test all client operations via CLI |
| 14 | Integration Test | Verify time format shows only seconds |
| 15 | Integration Test | Verify session_id == session_name displays correctly |
| 16 | Integration Test | Verify complete message content is displayed |

---

## 4. Implementation Notes

### 4.1 Display Format Requirements

**Time Format:**
- All time displays should only show up to "seconds"
- Format: `YYYY-MM-DD HH:MM:SS`
- Remove microseconds from ISO format

**Session Display (list-sessions):**
```
Retrieved {TOTAL_COUNT} session(s)

=============================================================================
[2026-04-13 23:27:53] test-session-123    -> When session_id == session_name
Task content
>>> Processed: 126d3ebbdc452e7

=============================================================================
[2026-04-13 23:27:53] session-id: session-name    -> When different
Task content
>>> Processed: 126d3ebbdc452e7
```

**Message Display (list-messages):**
```
Retrieved {TOTAL_COUNT} message(s), Session: {SESSION_ID}

=============================================================================
[2026-04-14 09:32:51] [msg_id] [role]
hello world (full content, not truncated)

>>> task_id: aaa
>>> task_result:
task result content
```

**Task Display (list-tasks):**
```
Retrieved {TOTAL_COUNT} task(s)

=============================================================================
[2026-04-14 13:31:36] task=[task_id] session=[session_id] msg=[msg_id]
Task: message content (full)
---
task result content
```

### 4.2 Code Organization Principles

1. **Single Responsibility:** Each client module handles one resource type
2. **DRY:** Common code (format_time, request handling) in base.py
3. **Consistent Interface:** All client classes inherit from BaseClient
4. **Error Handling:** Centralized in BaseClient._make_request()
5. **Logging:** Use logger from topsailai_server.agent_daemon

### 4.3 File Size Constraints

- Each file should be max 700 lines of code
- If a client module grows too large, split into sub-modules

---

## 5. Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-04-16 | Initial proposal - identified missing client folder structure | km-k25 |
| 2026-04-16 | Added detailed implementation plan for client modules | km-k25 |

---

## Appendix: Existing Implementation (Already Complete)

### A.1 API Endpoints

All API endpoints are implemented:
- `GET /api/v1/session/{session_id}` - GetSession with status
- `GET /api/v1/session` - ListSessions
- `DELETE /api/v1/session` - DeleteSessions
- `POST /api/v1/session/process` - ProcessSession
- `POST /api/v1/message` - ReceiveMessage
- `GET /api/v1/message` - RetrieveMessages
- `POST /api/v1/task` - SetTaskResult
- `GET /api/v1/task` - RetrieveTasks

### A.2 Current Client Operations

All client operations exist in `topsailai_agent_client.py`:
- `health` - Check server health
- `list-sessions` - List all sessions
- `get-session` - Get a single session
- `send-message` - Send a message
- `list-messages` / `get-messages` - Retrieve messages
- `set-task-result` - Set task result
- `list-tasks` / `get-tasks` - Retrieve tasks
- `process-session` - Process pending messages
- `delete-sessions` - Delete sessions

### A.3 Display Features Already Implemented

- Time format shows only seconds (format_time function)
- Session display handles session_id == session_name case
- Message display shows task_id and task_result
- Task display shows session_id and msg_id
