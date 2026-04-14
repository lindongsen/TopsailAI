---
maintainer: AI
---

# Test Execution Checklist

## Overview

This document provides a structured checklist for executing all tests for the agent_daemon project. Tests are organized by priority and category to ensure systematic validation of all features.

**Test Execution Order:**
1. Unit Tests (Core Logic)
2. Integration Tests (Business Flows)
3. Edge Case & Exception Tests

---

## Phase 1: Unit Tests - Core Logic

### 1.1 API Routes Tests

**File:** `tests/unit/test_api/test_routes.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.1.1 | `test_receive_message_success` | Returns 200, msg_id in response | ⬜ |
| 1.1.2 | `test_receive_message_missing_message` | Returns 422 validation error | ⬜ |
| 1.1.3 | `test_receive_message_missing_session_id` | Returns 422 validation error | ⬜ |
| 1.1.4 | `test_retrieve_messages` | Returns 200, list of messages | ⬜ |
| 1.1.5 | `test_retrieve_messages_missing_session_id` | Returns 422 validation error | ⬜ |
| 1.1.6 | `test_set_task_result_success` | Returns 200, code=0 | ⬜ |
| 1.1.7 | `test_set_task_result_missing_fields` | Returns 422 validation error | ⬜ |
| 1.1.8 | `test_retrieve_tasks` | Returns 200, list of tasks | ⬜ |
| 1.1.9 | `test_health_check` | Returns 200, code=0 | ⬜ |

**Pass Criteria:** All 9 tests pass

---

### 1.2 Storage Tests - Session Manager

**File:** `tests/unit/test_storage/test_session_manager.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.2.1 | `test_create_session` | Session created successfully | ⬜ |
| 1.2.2 | `test_get_session` | Returns session data | ⬜ |
| 1.2.3 | `test_update_session` | Session updated successfully | ⬜ |
| 1.2.4 | `test_update_processed_msg_id` | processed_msg_id updated | ⬜ |
| 1.2.5 | `test_delete_session` | Session deleted successfully | ⬜ |
| 1.2.6 | `test_get_or_create` | Creates new or returns existing | ⬜ |
| 1.2.7 | `test_get_sessions_older_than` | Returns filtered sessions | ⬜ |

**Pass Criteria:** All 7 tests pass

---

### 1.3 Storage Tests - Message Manager

**File:** `tests/unit/test_storage/test_message_manager.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.3.1 | `test_create_message` | Message created successfully | ⬜ |
| 1.3.2 | `test_get_message` | Returns message data | ⬜ |
| 1.3.3 | `test_update_message` | Message updated successfully | ⬜ |
| 1.3.4 | `test_delete_message` | Message deleted successfully | ⬜ |
| 1.3.5 | `test_get_by_session` | Returns session messages | ⬜ |
| 1.3.6 | `test_get_latest_message` | Returns latest message | ⬜ |
| 1.3.7 | `test_get_unprocessed_messages` | Returns unprocessed messages | ⬜ |
| 1.3.8 | `test_update_task_info` | Task info updated | ⬜ |
| 1.3.9 | `test_get_recent_messages` | Returns recent messages | ⬜ |
| 1.3.10 | `test_delete_by_session` | All messages deleted for session | ⬜ |

**Pass Criteria:** All 10 tests pass

---

### 1.4 Croner Tests - Message Consumer

**File:** `tests/unit/test_croner/jobs/test_message_consumer.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.4.1 | `test_message_consumer_initialization` | Object created successfully | ⬜ |
| 1.4.2 | `test_message_consumer_get_recent_messages` | Returns filtered messages | ⬜ |
| 1.4.3 | `test_message_consumer_get_unique_sessions` | Returns unique session IDs | ⬜ |
| 1.4.4 | `test_message_consumer_triggers_processor` | Processor triggered | ⬜ |
| 1.4.5 | `test_message_consumer_skips_processed_session` | Skips already processed | ⬜ |
| 1.4.6 | `test_full_message_consumption_flow` | All messages processed | ⬜ |

**Pass Criteria:** All 6 tests pass

---

### 1.5 Croner Tests - Message Summarizer

**File:** `tests/unit/test_croner/jobs/test_message_summarizer.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.5.1 | `test_message_summarizer_initialization` | Object created successfully | ⬜ |
| 1.5.2 | `test_message_summarizer_get_last_24h_messages` | Returns 24h messages | ⬜ |
| 1.5.3 | `test_message_summarizer_group_by_session` | Groups correctly | ⬜ |
| 1.5.4 | `test_message_summarizer_order_by_create_time` | Messages ordered correctly | ⬜ |
| 1.5.5 | `test_message_summarizer_calls_worker` | Worker called successfully | ⬜ |
| 1.5.6 | `test_full_summarization_flow` | All sessions summarized | ⬜ |

**Pass Criteria:** All 6 tests pass

---

### 1.6 Croner Tests - Session Cleaner

**File:** `tests/unit/test_croner/jobs/test_session_cleaner.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.6.1 | `test_session_cleaner_initialization` | Object created successfully | ⬜ |
| 1.6.2 | `test_session_cleaner_finds_old_sessions` | Returns old sessions | ⬜ |
| 1.6.3 | `test_session_cleaner_deletes_session_messages` | Messages deleted | ⬜ |
| 1.6.4 | `test_session_cleaner_deletes_session` | Session deleted | ⬜ |
| 1.6.5 | `test_session_cleaner_full_cleanup_flow` | Old sessions deleted | ⬜ |
| 1.6.6 | `test_session_cleaner_preserves_recent_sessions` | Recent sessions preserved | ⬜ |
| 1.6.7 | `test_session_cleaner_handles_empty_database` | No error thrown | ⬜ |
| 1.6.8 | `test_session_cleaner_handles_session_without_messages` | Handled gracefully | ⬜ |
| 1.6.9 | `test_multiple_old_sessions_cleanup` | All old sessions cleaned | ⬜ |

**Pass Criteria:** All 9 tests pass

---

### 1.7 Worker Tests - Processor

**File:** `tests/unit/test_worker/test_processor.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.7.1 | `test_scenario1_direct_reply` | Reply message created | ⬜ |
| 1.7.2 | `test_scenario1_retrieve_messages` | Messages retrieved correctly | ⬜ |
| 1.7.3 | `test_scenario2_task_generation` | Task created successfully | ⬜ |
| 1.7.4 | `test_scenario2_task_result` | Task result set correctly | ⬜ |
| 1.7.5 | `test_start_processor` | Processor started | ⬜ |
| 1.7.6 | `test_processor_environment_variables` | Correct env vars passed | ⬜ |
| 1.7.7 | `test_processor_script_exists` | Script exists (may skip) | ⬜ |
| 1.7.8 | `test_processor_script_executable` | Script is executable (may skip) | ⬜ |

**Pass Criteria:** 6-8 tests pass (2 may skip)

---

### 1.8 Worker Tests - Summarizer

**File:** `tests/unit/test_worker/test_summarizer.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.8.1 | `test_summarizer_environment_variables` | Correct env vars passed | ⬜ |
| 1.8.2 | `test_summarizer_script_executable` | Script is executable (may skip) | ⬜ |
| 1.8.3 | `test_summarizer_env_command` | Env vars accessible | ⬜ |
| 1.8.4 | `test_summarizer_with_worker_manager` | WorkerManager works | ⬜ |
| 1.8.5 | `test_summarizer_script_exists` | Script exists (may skip) | ⬜ |
| 1.8.6 | `test_summarizer_script_permissions` | Correct permissions (may skip) | ⬜ |

**Pass Criteria:** 3-6 tests pass (3 may skip)

---

### 1.9 Worker Tests - Session State Checker

**File:** `tests/unit/test_worker/test_session_state_checker.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 1.9.1 | `test_state_checker_idle_output` | Returns "idle" | ⬜ |
| 1.9.2 | `test_state_checker_processing_output` | Returns "processing" | ⬜ |
| 1.9.3 | `test_state_checker_environment_variable` | TOPSAILAI_SESSION_ID passed | ⬜ |
| 1.9.4 | `test_state_checker_script_executable` | Script is executable (may skip) | ⬜ |
| 1.9.5 | `test_worker_manager_check_session_state_idle` | Returns "idle" | ⬜ |
| 1.9.6 | `test_worker_manager_check_session_state_processing` | Returns "processing" | ⬜ |
| 1.9.7 | `test_worker_manager_is_session_idle` | Returns True/False | ⬜ |
| 1.9.8 | `test_state_checker_script_exists` | Script exists (may skip) | ⬜ |
| 1.9.9 | `test_state_checker_script_permissions` | Correct permissions (may skip) | ⬜ |

**Pass Criteria:** 6-9 tests pass (3 may skip)

---

## Phase 2: Integration Tests - Business Flows

### 2.1 End-to-End Message Flow Tests

**File:** `tests/integration/test_integration.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.1.1 | `test_receive_message_process_session_check_result` | Complete flow successful | ⬜ |
| 2.1.2 | `test_direct_message_without_task` | Message processed without task | ⬜ |

**Pass Criteria:** All 2 tests pass

---

### 2.2 Session Lifecycle Tests

**File:** `tests/integration/test_integration.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.2.1 | `test_session_lifecycle` | Complete lifecycle successful | ⬜ |
| 2.2.2 | `test_session_with_unprocessed_messages` | Unprocessed messages identified | ⬜ |

**Pass Criteria:** All 2 tests pass

---

### 2.3 Cron Job Integration Tests

**File:** `tests/integration/test_integration.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.3.1 | `test_message_consumer_job` | Processor triggered | ⬜ |
| 2.3.2 | `test_message_summarizer_job` | Summarizer triggered | ⬜ |

**Pass Criteria:** All 2 tests pass

---

### 2.4 Error Handling Tests

**File:** `tests/integration/test_integration.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.4.1 | `test_invalid_session_id` | Returns None gracefully | ⬜ |
| 2.4.2 | `test_missing_required_parameters` | Handled gracefully | ⬜ |
| 2.4.3 | `test_database_errors` | Errors handled gracefully | ⬜ |
| 2.4.4 | `test_message_not_found` | Returns None gracefully | ⬜ |

**Pass Criteria:** All 4 tests pass

---

### 2.5 Worker Manager Integration Tests

**File:** `tests/integration/test_integration.py`

| # | Test Case | Expected Result | Status |
|---|-----------|-----------------|--------|
| 2.5.1 | `test_start_processor` | Processor started successfully | ⬜ |
| 2.5.2 | `test_session_state_check` | Returns correct state | ⬜ |

**Pass Criteria:** All 2 tests pass

---

## Phase 3: Edge Case & Exception Tests

### 3.1 Edge Cases - Storage

| # | Test Scenario | Expected Behavior | Status |
|---|---------------|-------------------|--------|
| 3.1.1 | Empty session list query | Returns empty list, no error | ⬜ |
| 3.1.2 | Message with very long content | Handled correctly | ⬜ |
| 3.1.3 | Special characters in message | Preserved correctly | ⬜ |
| 3.1.4 | Concurrent message creation | No data corruption | ⬜ |
| 3.1.5 | Delete non-existent session | Handled gracefully | ⬜ |

---

### 3.2 Edge Cases - API

| # | Test Scenario | Expected Behavior | Status |
|---|---------------|-------------------|--------|
| 3.2.1 | Very large offset/limit values | Handled gracefully | ⬜ |
| 3.2.2 | Invalid date formats | Returns validation error | ⬜ |
| 3.2.3 | Empty request body | Returns validation error | ⬜ |
| 3.2.4 | Unicode content in messages | Handled correctly | ⬜ |
| 3.2.5 | Session with 1000+ messages | Pagination works correctly | ⬜ |

---

### 3.3 Edge Cases - Croner

| # | Test Scenario | Expected Behavior | Status |
|---|---------------|-------------------|--------|
| 3.3.1 | No messages in last 10 minutes | No action taken | ⬜ |
| 3.3.2 | All sessions already processed | No duplicate processing | ⬜ |
| 3.3.3 | Processor script fails | Error logged, continues | ⬜ |
| 3.3.4 | No sessions older than 1 year | No deletion performed | ⬜ |
| 3.3.5 | Database locked during cleanup | Retry or skip gracefully | ⬜ |

---

### 3.4 Edge Cases - Worker

| # | Test Scenario | Expected Behavior | Status |
|---|---------------|-------------------|--------|
| 3.4.1 | Processor script not found | Error logged | ⬜ |
| 3.4.2 | Processor script not executable | Error logged | ⬜ |
| 3.4.3 | Processor timeout | Process terminated | ⬜ |
| 3.4.4 | State checker returns unexpected output | Handled gracefully | ⬜ |
| 3.4.5 | Environment variables not set | Clear error message | ⬜ |

---

## Test Execution Commands

### Run All Tests

```bash
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python -m pytest tests/ -v
```

### Run Unit Tests Only

```bash
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python -m pytest tests/unit/ -v
```

### Run Integration Tests Only

```bash
export HOME=/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python -m pytest tests/integration/ -v
```

### Run Specific Test File

```bash
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python -m pytest tests/unit/test_storage/test_session_manager.py -v
```

### Run with Coverage

```bash
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon
python -m pytest tests/ --cov=topsailai_server.agent_daemon --cov-report=html
```

---

## Success Criteria Summary

| Category | Total Tests | Expected Pass | Status |
|----------|-------------|---------------|--------|
| Unit Tests - API Routes | 9 | 9 | ⬜ |
| Unit Tests - Storage | 17 | 17 | ⬜ |
| Unit Tests - Croner | 21 | 21 | ⬜ |
| Unit Tests - Worker | 23 | 15-23 | ⬜ |
| **Unit Tests Total** | **70** | **62-70** | ⬜ |
| Integration Tests | 12 | 12 | ⬜ |
| Edge Case Tests | 20 | 20 | ⬜ |
| **Grand Total** | **102** | **94-102** | ⬜ |

---

## Sign-off

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Reviewer | km-k25 | | |
| Developer | mm-m25 | | |

---

## Notes

1. **Test Environment:** Ensure all environment variables are set before running tests
2. **Mock Scripts:** Integration tests require mock scripts to be executable
3. **Database:** Each test uses isolated temporary databases
4. **Timeouts:** Default timeout is 120 seconds per test
5. **Cleanup:** Temporary files are automatically cleaned up after tests

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-04-14 | km-k25 | Initial creation |
