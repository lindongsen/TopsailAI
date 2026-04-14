---
maintainer: AI
---

# Agent Daemon Test Cases

## Overview

This document provides a comprehensive overview of all test cases for the agent_daemon project. The test suite includes both unit tests and integration tests to ensure full functionality and reliability.

**Test Statistics:**
- Unit Tests: 64 passed, 6 skipped
- Integration Tests: 12 passed

## Test Categories

### Unit Tests

Unit tests are located in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/unit/`

#### 1. API Routes Tests (`test_api/test_routes.py`)

**TestMessageAPI:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_receive_message_success` | Test receiving a valid message | Returns 200, msg_id in response |
| `test_receive_message_missing_message` | Test receiving message without content | Returns 422 validation error |
| `test_receive_message_missing_session_id` | Test receiving message without session_id | Returns 422 validation error |
| `test_retrieve_messages` | Test retrieving messages for a session | Returns 200, list of messages |
| `test_retrieve_messages_missing_session_id` | Test retrieving messages without session_id | Returns 422 validation error |

**TestTaskAPI:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_set_task_result_success` | Test setting task result | Returns 200, code=0 |
| `test_set_task_result_missing_fields` | Test setting task result with missing fields | Returns 422 validation error |
| `test_retrieve_tasks` | Test retrieving tasks | Returns 200, list of tasks |

**TestHealthCheck:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_health_check` | Test health check endpoint | Returns 200, code=0 |

#### 2. Storage Tests (`test_storage/`)

**test_session_manager.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_create_session` | Test creating a new session | Session created successfully |
| `test_get_session` | Test retrieving a session | Returns session data |
| `test_update_session` | Test updating a session | Session updated successfully |
| `test_update_processed_msg_id` | Test updating processed_msg_id | processed_msg_id updated |
| `test_delete_session` | Test deleting a session | Session deleted successfully |
| `test_get_or_create` | Test get_or_create method | Creates new or returns existing |
| `test_get_sessions_older_than` | Test getting sessions older than date | Returns filtered sessions |

**test_message_manager.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_create_message` | Test creating a new message | Message created successfully |
| `test_get_message` | Test retrieving a message | Returns message data |
| `test_update_message` | Test updating a message | Message updated successfully |
| `test_delete_message` | Test deleting a message | Message deleted successfully |
| `test_get_by_session` | Test getting messages by session | Returns session messages |
| `test_get_latest_message` | Test getting the latest message | Returns latest message |
| `test_get_unprocessed_messages` | Test getting unprocessed messages | Returns unprocessed messages |
| `test_update_task_info` | Test updating task info | Task info updated |
| `test_get_recent_messages` | Test getting recent messages | Returns recent messages |
| `test_delete_by_session` | Test deleting all messages for session | All messages deleted |

#### 3. Croner Tests (`test_croner/jobs/`)

**test_message_consumer.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_message_consumer_initialization` | Test MessageConsumer initialization | Object created successfully |
| `test_message_consumer_get_recent_messages` | Test getting recent messages from last 10 minutes | Returns filtered messages |
| `test_message_consumer_get_unique_sessions` | Test getting unique session IDs | Returns unique session IDs |
| `test_message_consumer_triggers_processor` | Test processor trigger | Processor triggered for unprocessed |
| `test_message_consumer_skips_processed_session` | Test skipping processed sessions | Skips already processed |
| `test_full_message_consumption_flow` | Test complete consumption flow | All messages processed |

**test_message_summarizer.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_message_summarizer_initialization` | Test MessageSummarizer initialization | Object created successfully |
| `test_message_summarizer_get_last_24h_messages` | Test getting messages from last 24 hours | Returns 24h messages |
| `test_message_summarizer_group_by_session` | Test grouping messages by session | Groups correctly |
| `test_message_summarizer_order_by_create_time` | Test ordering by create_time | Messages ordered correctly |
| `test_message_summarizer_calls_worker` | Test worker call | Worker called successfully |
| `test_full_summarization_flow` | Test complete summarization flow | All sessions summarized |

**test_session_cleaner.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_session_cleaner_initialization` | Test SessionCleaner initialization | Object created successfully |
| `test_session_cleaner_finds_old_sessions` | Test finding sessions older than 1 year | Returns old sessions |
| `test_session_cleaner_deletes_session_messages` | Test deleting session messages | Messages deleted |
| `test_session_cleaner_deletes_session` | Test deleting a session | Session deleted |
| `test_session_cleaner_full_cleanup_flow` | Test complete cleanup flow | Old sessions deleted, new preserved |
| `test_session_cleaner_preserves_recent_sessions` | Test preserving recent sessions | Recent sessions not deleted |
| `test_session_cleaner_handles_empty_database` | Test handling empty database | No error thrown |
| `test_session_cleaner_handles_session_without_messages` | Test handling sessions without messages | Handled gracefully |
| `test_multiple_old_sessions_cleanup` | Test cleaning multiple old sessions | All old sessions cleaned |

#### 4. Worker Tests (`test_worker/`)

**test_processor.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_scenario1_direct_reply` | Test direct reply scenario | Reply message created |
| `test_scenario1_retrieve_messages` | Test retrieving messages after reply | Messages retrieved correctly |
| `test_scenario2_task_generation` | Test task generation scenario | Task created successfully |
| `test_scenario2_task_result` | Test setting task result | Task result set correctly |
| `test_start_processor` | Test starting processor | Processor started |
| `test_processor_environment_variables` | Test processor env variables | Correct env vars passed |
| `test_processor_script_exists` | Test processor script exists | Script exists |
| `test_processor_script_executable` | Test processor script executable | Script is executable |

**test_summarizer.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_summarizer_environment_variables` | Test summarizer env variables | Correct env vars passed |
| `test_summarizer_script_executable` | Test summarizer script executable | Script is executable |
| `test_summarizer_env_command` | Test env command usage | Env vars accessible |
| `test_summarizer_with_worker_manager` | Test summarizer via WorkerManager | WorkerManager works |
| `test_summarizer_script_exists` | Test summarizer script exists | Script exists |
| `test_summarizer_script_permissions` | Test summarizer script permissions | Correct permissions |

**test_session_state_checker.py:**
| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_state_checker_idle_output` | Test idle output | Returns "idle" |
| `test_state_checker_processing_output` | Test processing output | Returns "processing" |
| `test_state_checker_environment_variable` | Test env variable passed | TOPSAILAI_SESSION_ID passed |
| `test_state_checker_script_executable` | Test script executable | Script is executable |
| `test_worker_manager_check_session_state_idle` | Test WorkerManager idle check | Returns "idle" |
| `test_worker_manager_check_session_state_processing` | Test WorkerManager processing check | Returns "processing" |
| `test_worker_manager_is_session_idle` | Test is_session_idle method | Returns True/False |
| `test_state_checker_script_exists` | Test script exists | Script exists |
| `test_state_checker_script_permissions` | Test script permissions | Correct permissions |

---

### Integration Tests

Integration tests are located in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration/test_integration.py`

#### 1. End-to-End Message Flow Tests

| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_receive_message_process_session_check_result` | Complete message flow: receive → process → check result | All steps complete successfully |
| `test_direct_message_without_task` | Direct answer without task generation | Message processed without task |

#### 2. Session Lifecycle Tests

| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_session_lifecycle` | Complete session lifecycle | Session created, messages added, processed |
| `test_session_with_unprocessed_messages` | Unprocessed message identification | Unprocessed messages correctly identified |

#### 3. Cron Job Integration Tests

| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_message_consumer_job` | Message consumer job execution | Processor triggered for unprocessed |
| `test_message_summarizer_job` | Message summarizer job execution | Summarizer triggered for sessions |

#### 4. Error Handling Tests

| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_invalid_session_id` | Invalid session ID handling | Returns None gracefully |
| `test_missing_required_parameters` | Missing parameters handling | Handled gracefully |
| `test_database_errors` | Database error handling | Errors handled gracefully |
| `test_message_not_found` | Message not found handling | Returns None gracefully |

#### 5. Worker Manager Integration Tests

| Test Case | Description | Expected Result |
|-----------|-------------|-----------------|
| `test_start_processor` | Starting processor worker | Processor started successfully |
| `test_session_state_check` | Session state checking | Returns correct state |

---

## Test Execution Instructions

### Running All Tests

```bash
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon

# Run all unit tests
python -m pytest tests/unit/ -v

# Run all integration tests
python -m pytest tests/integration/ -v

# Run all tests
python -m pytest tests/ -v
```

### Running Specific Test Categories

```bash
# Run API tests only
python -m pytest tests/unit/test_api/ -v

# Run storage tests only
python -m pytest tests/unit/test_storage/ -v

# Run croner tests only
python -m pytest tests/unit/test_croner/ -v

# Run worker tests only
python -m pytest tests/unit/test_worker/ -v
```

### Running Integration Tests with Environment

```bash
export HOME=/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration
cd /root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration
python -m pytest test_integration.py -v
```

### Running with Coverage

```bash
python -m pytest tests/ --cov=topsailai_server.agent_daemon --cov-report=html
```

---

## Expected Outcomes

### Unit Tests

| Category | Expected | Status |
|----------|----------|--------|
| API Routes | 9 tests | All should pass |
| Storage | 17 tests | All should pass |
| Croner | 18 tests | All should pass |
| Worker | 20 tests | 6 may skip (script existence checks) |

### Integration Tests

| Category | Expected | Status |
|----------|----------|--------|
| End-to-End Flow | 2 tests | All should pass |
| Session Lifecycle | 2 tests | All should pass |
| Cron Job Integration | 2 tests | All should pass |
| Error Handling | 4 tests | All should pass |
| Worker Manager | 2 tests | All should pass |

### Test Success Criteria

1. **All unit tests pass** (64 passed, 6 skipped acceptable)
2. **All integration tests pass** (12 passed)
3. **No test timeouts** (default timeout: 120 seconds)
4. **No database file conflicts** (each test uses unique temp files)
5. **Proper cleanup** (temp files deleted after tests)

---

## Test Fixtures

### Integration Test Fixtures (`conftest.py`)

| Fixture | Purpose |
|---------|---------|
| `temp_db_path` | Creates temporary database file |
| `storage` | Provides Storage instance for tests |
| `test_client` | Provides Flask test client |
| `sample_session` | Creates sample session data |
| `sample_message` | Creates sample message data |
| `mock_processor_script` | Mock processor script path |
| `mock_summarizer_script` | Mock summarizer script path |
| `mock_state_checker_script` | Mock state checker script path |

---

## Mock Scripts

Mock scripts are located in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/tests/integration/`:

- `mock_processor.sh` - Mock processor script
- `mock_summarizer.sh` - Mock summarizer script
- `mock_state_checker.sh` - Mock state checker script

These scripts are used during integration testing to simulate worker behavior without actual processing.

---

## Notes

1. **Environment Variables**: Tests set required environment variables before imports
2. **Database Cleanup**: Each test uses temporary databases that are cleaned up after use
3. **Concurrent Tests**: Tests are designed to run independently without conflicts
4. **Skipped Tests**: Some tests may skip if mock scripts are not available
5. **Logging**: Tests use the agent_daemon logger for output

---

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure `sys.path` includes the project root
2. **Database Locks**: Use `check_same_thread=False` for SQLite
3. **Missing Scripts**: Mock scripts must be executable
4. **Environment Variables**: Set required env vars before running tests

### Debug Mode

```bash
# Run with verbose output
python -m pytest tests/ -v -s

# Run with pdb on failures
python -m pytest tests/ --pdb
```
