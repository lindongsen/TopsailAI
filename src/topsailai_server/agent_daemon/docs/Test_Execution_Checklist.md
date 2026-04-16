# Test Execution Checklist

**Project:** agent_daemon  
**Created:** 2026-04-16  
**Maintainer:** AI

---

## Overview

This document outlines the comprehensive test plan for the agent_daemon client modules and CLI.

## Test Categories

### 1. Unit Tests

#### 1.1 BaseClient Tests
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| U-001 | test_base_client_init | Initialize BaseClient with default and custom base_url | Client created successfully | ⬜ |
| U-002 | test_base_client_get | Test GET request with params | Returns parsed JSON response | ⬜ |
| U-003 | test_base_client_post | Test POST request with JSON data | Returns parsed JSON response | ⬜ |
| U-004 | test_base_client_post_json_str | Test POST with JSON string | Returns parsed JSON response | ⬜ |
| U-005 | test_base_client_error_handling | Test API error response (code != 0) | Raises APIError with message | ⬜ |
| U-006 | test_base_client_http_error | Test HTTP error (404, 500) | Raises APIError with status code | ⬜ |
| U-007 | test_base_client_connection_error | Test connection failure | Raises APIError with connection message | ⬜ |
| U-008 | test_format_time | Test time formatting function | Returns YYYY-MM-DD HH:MM:SS format | ⬜ |
| U-009 | test_format_time_none | Test format_time with None input | Returns "N/A" | ⬜ |

#### 1.2 SessionClient Tests
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| U-010 | test_session_client_health_check | Test health check endpoint | Returns True for healthy server | ⬜ |
| U-011 | test_session_client_list_sessions | Test listing sessions | Returns list of session dicts | ⬜ |
| U-012 | test_session_client_list_sessions_with_filters | Test listing with session_ids filter | Returns filtered sessions | ⬜ |
| U-013 | test_session_client_list_sessions_empty | Test listing with no sessions | Returns empty list | ⬜ |
| U-014 | test_session_client_get_session | Test getting single session | Returns session dict with status | ⬜ |
| U-015 | test_session_client_get_session_not_found | Test getting non-existent session | Handles error gracefully | ⬜ |
| U-016 | test_session_client_delete_sessions | Test deleting sessions | Returns success response | ⬜ |
| U-017 | test_session_client_process_session | Test processing session | Returns processing info | ⬜ |
| U-018 | test_session_client_process_session_no_messages | Test processing with no pending messages | Returns appropriate message | ⬜ |
| U-019 | test_print_session_same_id_name | Test display when session_id == session_name | Shows only one identifier | ⬜ |
| U-020 | test_print_session_different_id_name | Test display when session_id != session_name | Shows both identifiers | ⬜ |
| U-021 | test_print_session_with_task | Test display with task content | Shows task information | ⬜ |

#### 1.3 MessageClient Tests
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| U-022 | test_message_client_send_message | Test sending message | Returns success response | ⬜ |
| U-023 | test_message_client_send_message_with_processed_id | Test sending with processed_msg_id | Returns success response | ⬜ |
| U-024 | test_message_client_list_messages | Test listing messages | Returns list of message dicts | ⬜ |
| U-025 | test_message_client_list_messages_with_task | Test listing messages with task_id/task_result | Shows task info in output | ⬜ |
| U-026 | test_message_client_list_messages_empty | Test listing with no messages | Returns empty list | ⬜ |
| U-027 | test_print_message_user_role | Test display for user message | Shows correct role formatting | ⬜ |
| U-028 | test_print_message_assistant_role | Test display for assistant message | Shows correct role formatting | ⬜ |
| U-029 | test_print_message_with_task | Test display with task_id and task_result | Shows >>> task_id and >>> task_result | ⬜ |
| U-030 | test_print_message_full_content | Test that full message content is displayed | No truncation or ellipsis | ⬜ |

#### 1.4 TaskClient Tests
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| U-031 | test_task_client_set_task_result | Test setting task result | Returns success response | ⬜ |
| U-032 | test_task_client_list_tasks | Test listing tasks | Returns list of task dicts | ⬜ |
| U-033 | test_task_client_list_tasks_with_filters | Test listing with task_ids filter | Returns filtered tasks | ⬜ |
| U-034 | test_task_client_list_tasks_empty | Test listing with no tasks | Returns empty list | ⬜ |
| U-035 | test_print_task | Test task display formatting | Shows correct format with all fields | ⬜ |
| U-036 | test_print_task_with_result | Test task display with result | Shows --- separator and result | ⬜ |
| U-037 | test_print_task_full_message | Test that full message content is displayed | No truncation or ellipsis | ⬜ |

### 2. Integration Tests

#### 2.1 End-to-End Workflows
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| I-001 | test_full_session_lifecycle | Create session → Send messages → Process → Get results | Complete workflow succeeds | ⬜ |
| I-002 | test_message_processing_flow | Send message → Trigger processing → Verify task created | Task created and result set | ⬜ |
| I-003 | test_multiple_messages_batch | Send multiple messages → Process batch → Verify all handled | All messages processed | ⬜ |
| I-004 | test_session_cleanup | Create old session → Run cleanup cron → Verify deleted | Session and messages removed | ⬜ |
| I-005 | test_concurrent_session_access | Multiple clients accessing same session | No race conditions | ⬜ |

#### 2.2 CLI Integration Tests
| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| I-006 | test_cli_health_check | Run `topsailai_agent_client health` | Shows server status | ⬜ |
| I-007 | test_cli_list_sessions | Run `topsailai_agent_client list-sessions` | Shows formatted session list | ⬜ |
| I-008 | test_cli_get_session | Run `topsailai_agent_client get-session --session-id xxx` | Shows session details | ⬜ |
| I-009 | test_cli_send_message | Run `topsailai_agent_client send-message --message "test"` | Message sent successfully | ⬜ |
| I-010 | test_cli_list_messages | Run `topsailai_agent_client list-messages --session-id xxx` | Shows formatted message list | ⬜ |
| I-011 | test_cli_list_tasks | Run `topsailai_agent_client list-tasks --session-id xxx` | Shows formatted task list | ⬜ |
| I-012 | test_cli_set_task_result | Run `topsailai_agent_client set-task-result ...` | Task result set successfully | ⬜ |
| I-013 | test_cli_process_session | Run `topsailai_agent_client process-session --session-id xxx` | Session processed | ⬜ |
| I-014 | test_cli_delete_sessions | Run `topsailai_agent_client delete-sessions xxx yyy` | Sessions deleted | ⬜ |
| I-015 | test_cli_verbose_mode | Run commands with `-v` flag | Shows full JSON output | ⬜ |

### 3. Edge Case & Exception Tests

| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| E-001 | test_empty_session_id | Use empty string as session_id | Handles gracefully with error | ⬜ |
| E-002 | test_invalid_session_id | Use non-existent session_id | Returns appropriate error | ⬜ |
| E-003 | test_malformed_time_filter | Use invalid time format | Handles or rejects appropriately | ⬜ |
| E-004 | test_negative_pagination | Use negative offset/limit | Handles or rejects appropriately | ⬜ |
| E-005 | test_very_long_message | Send message with 10MB content | Handles without crash | ⬜ |
| E-006 | test_special_characters | Send message with special chars/emoji | Preserves content correctly | ⬜ |
| E-007 | test_server_unavailable | Client when server is down | Shows connection error | ⬜ |
| E-008 | test_timeout_handling | Slow server response | Handles timeout appropriately | ⬜ |
| E-009 | test_duplicate_task_result | Set result for same task twice | Handles appropriately | ⬜ |
| E-010 | test_empty_task_result | Set empty string as task result | Stores empty result | ⬜ |

### 4. Display Format Tests

| Test ID | Test Name | Description | Expected Result | Status |
|---------|-----------|-------------|-----------------|--------|
| D-001 | test_time_format_seconds_only | Verify time shows only to seconds | Format: YYYY-MM-DD HH:MM:SS | ⬜ |
| D-002 | test_session_display_same_id_name | session_id == session_name | Shows only one identifier | ⬜ |
| D-003 | test_message_display_task_info | Message with task_id/task_result | Shows >>> task_id and >>> task_result | ⬜ |
| D-004 | test_task_display_format | Task display format | `[time] task=[id] session=[id] msg=[id]` | ⬜ |
| D-005 | test_task_result_separator | Task with result | Shows `---` before result | ⬜ |
| D-006 | test_split_line_usage | Verify SPLIT_LINE used correctly | `===...===` (80 chars) | ⬜ |
| D-007 | test_no_truncation | Long content in messages/tasks | Full content displayed | ⬜ |

---

## Test Execution Order

### Phase 1: Unit Tests (U-001 to U-037)
1. Run all BaseClient tests first
2. Run SessionClient tests
3. Run MessageClient tests
4. Run TaskClient tests

### Phase 2: Integration Tests (I-001 to I-015)
1. Start test server with test database
2. Run end-to-end workflow tests
3. Run CLI integration tests

### Phase 3: Edge Case Tests (E-001 to E-010)
1. Run boundary condition tests
2. Run error handling tests

### Phase 4: Display Format Tests (D-001 to D-007)
1. Verify all output formatting matches specification

---

## Success Criteria

- All unit tests pass (37/37)
- All integration tests pass (15/15)
- All edge case tests pass (10/10)
- All display format tests pass (7/7)
- Total: 69/69 tests passing

## Notes

- Use `export HOME=/path/to/tests/integration` when running integration tests
- Check `/topsailai/log/agent_daemon.log` for server-side logs during testing
- Run tests with `-v` flag for verbose output when debugging
