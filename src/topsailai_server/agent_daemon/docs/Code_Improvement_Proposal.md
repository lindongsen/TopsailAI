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
| Http API | ⚠️ Partial | `api/routes/session.py`, `api/routes/message.py`, `api/routes/task.py` |
| Croner | ✅ Complete | `croner/scheduler.py`, `croner/jobs/*.py` |
| Worker | ✅ Complete | `worker/process_manager.py` |
| CLI Tools | ✅ Complete | `topsailai_agent_daemon.py`, `topsailai_agent_client.py` |
| Scripts | ✅ Complete | `scripts/processor_callback.py`, `scripts/session_state_checker.py` |
| Logger | ✅ Complete | `logger.py` |

**⚠️ CRITICAL MISSING:** GetSession API endpoint is NOT implemented.

---

## 2. Required Implementation

### 2.1 GetSession API Endpoint

**File to Modify:** `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/routes/session.py`

**Specification:**
```
### session, uri_path:api/v1/session

#### GetSession
parameters:
- session_id: str, required

response:
- data: dict

此接口还要去调用 `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER` 以得到session状态(status)，将状态信息填入 data 中。
```

**Implementation Requirements:**

1. **Route:** `GET /api/v1/session/{session_id}`
2. **Parameters:**
   - `session_id` (path parameter, required): The session identifier
3. **Behavior:**
   - Validate session_id format using `validate_session_id()`
   - Retrieve session data from storage
   - Call `worker_manager.check_session_state(session_id)` to get status (idle/processing)
   - Include status in the response data
   - Return 404 if session not found
4. **Response Format:**
   ```json
   {
     "code": 0,
     "data": {
       "session_id": "...",
       "session_name": "...",
       "task": "...",
       "create_time": "...",
       "update_time": "...",
       "processed_msg_id": "...",
       "status": "idle"  // or "processing"
     },
     "message": "OK"
   }
   ```

**Reference Implementation Pattern:**
Look at existing endpoints in `session.py`:
- Use `validate_session_id()` from `topsailai_server.agent_daemon.validator`
- Use `storage.session.get(session_id)` to retrieve session
- Use `worker_manager.check_session_state(session_id)` to get status
- Use `success_response()` and `error_response()` from `api.utils`

---

## 3. Implementation Checklist

### Phase 1: GetSession API Implementation

| # | Task | File | Priority |
|---|------|------|----------|
| 1 | Add GetSession endpoint | `api/routes/session.py` | 🔴 High |
| 2 | Add GetSession client command | `topsailai_agent_client.py` | 🟡 Medium |
| 3 | Add unit tests for GetSession | `tests/unit/test_api/` | 🟡 Medium |

### Phase 2: Testing

| # | Task | Description |
|---|------|-------------|
| 1 | Unit Test | Test GetSession with valid session_id |
| 2 | Unit Test | Test GetSession with invalid session_id format |
| 3 | Unit Test | Test GetSession with non-existent session_id |
| 4 | Integration Test | Test status field returns idle/processing correctly |
| 5 | Client Test | Test topsailai_agent_client get-session command |

---

## 4. Implementation Notes

### 4.1 Session Status Logic

The session status is determined by:
1. First checking local `running_processes` in WorkerManager
2. If not found locally, calling `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER` script
3. The script returns "idle" or "processing"

### 4.2 Client CLI Addition

Add to `topsailai_agent_client.py`:
```python
def do_client_get_session(args):
    """Get a single session by ID"""
    base_url = f"http://{args.host}:{args.port}"
    url = f"{base_url}/api/v1/session/{args.session_id}"
    # ... implementation

# Add subparser:
get_session_parser = subparsers.add_parser('get-session', help='Get a session by ID')
get_session_parser.add_argument('--session-id', type=str, required=True, help='Session ID')
get_session_parser.set_defaults(func=do_client_get_session)
```

---

## 5. Changelog

| Date | Change | Author |
|------|--------|--------|
| 2026-04-16 | Identified missing GetSession API | km-k25 |
| 2026-04-16 | Created implementation checklist | km-k25 |

---

## Appendix: Existing Improvements (Already Implemented)

### A.1 Configuration Validation

**File:** `configer/env_config.py`

Validates `TOPSAILAI_AGENT_DAEMON_PROCESSOR`, `TOPSAILAI_AGENT_DAEMON_SUMMARIZER`, `TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER` scripts exist and are executable.

### A.2 Cron Job Resilience

**Files:** `croner/jobs/message_consumer.py`, `croner/jobs/message_summarizer.py`

- Retry mechanism with exponential backoff
- Circuit breaker pattern for external script failures
- Execution metrics logging

### A.3 Edge Case Handling

**Files:** `api/routes/session.py`, `api/routes/message.py`, `api/routes/task.py`

Validation functions for session_id, message_content, role, task_id, msg_id with proper error handling.
