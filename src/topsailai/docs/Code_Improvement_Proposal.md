---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai
ProjectFolder: /root/ai/TopsailAI/src/topsailai
ProjectRootFolder: /root/ai/TopsailAI/
programming_language: python
TestsFolder: /root/ai/TopsailAI/src/topsailai/tests
DocsFolder: /root/ai/TopsailAI/src/topsailai/docs
IssuesFolder: /root/ai/TopsailAI/src/topsailai/issues
---

# Code Improvement Proposal: Unit Test Enhancement

## Overview

This proposal identifies test gaps across the TopsailAI Agent project and provides actionable recommendations for enhancing unit test coverage, following the priority order defined in `test.md`.

## Current Test Coverage Summary

### Existing Tests (23 files, ~6573 lines)

| Category | Test File | Lines | Source Module |
|----------|-----------|-------|---------------|
| **Common Utils** | test_topsailai_utils_hash_tool.py | 411 | utils/hash_tool.py |
| | test_topsailai_utils_file_tool.py | 411 | utils/file_tool.py |
| | test_topsailai_utils_json_tool.py | 411 | utils/json_tool.py |
| | test_topsailai_utils_thread_local_tool.py | 182 | utils/thread_local_tool.py |
| | test_topsailai_utils_thread_tool.py | 127 | utils/thread_tool.py |
| | test_topsailai_utils_time_tool.py | 72 | utils/time_tool.py |
| | test_topsailai_utils_print_tool.py | 411 | utils/print_tool.py |
| | test_topsailai_utils_format_tool.py | 411 | utils/format_tool.py |
| | test_topsailai_utils_text_tool.py | 411 | utils/text_tool.py |
| | test_topsailai_utils_module_tool.py | 411 | utils/module_tool.py |
| | test_topsailai_utils_cmd_tool.py | 411 | utils/cmd_tool.py |
| | test_topsailai_utils_env_tool.py | 411 | utils/env_tool.py |
| **Agent Core** | test_topsailai_tools_file_tool.py | 411 | tools/file_tool.py |
| | test_topsailai_tools_file_tool_utils_file_read_line.py | 411 | tools/file_tool_utils/file_read_line.py |
| | test_topsailai_context_chat_history_manager_sql.py | 411 | context/chat_history_manager/sql.py |
| | test_topsailai_context_chat_history_manager_sql_clean.py | 411 | context/chat_history_manager/sql_clean.py |
| | test_topsailai_context_session_manager_sql.py | 411 | context/session_manager/sql.py |
| | test_topsailai_ai_base_agent_types_tool.py | 411 | ai_base/agent_types/tool.py |
| | test_topsailai_ai_base_llm_hooks_hook_after_chat_minimax.py | 411 | ai_base/llm_hooks/hook_after_chat/minimax.py |
| **Agent Workers** | test_topsailai_skill_hub_skill_tool.py | 411 | skill_hub/skill_tool.py |
| | test_topsailai_skill_hub_skill_repo.py | 411 | skill_hub/skill_repo.py |
| **Other** | test_topsailai_context_tool_stat.py | 411 | context/tool_stat.py |

## Gap Analysis: Missing Tests

### Priority 1: Common Utils (logger, utils, human)

#### 1.1 logger Module — **NO TESTS EXIST**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `logger/base_logger.py` | 52 | `setup_logger(name, log_file, level)` — logger creation, file handler setup, console handler setup, level configuration | **HIGH** |
| `logger/log_chat.py` | 14 | `logger` instance — verify logger name, verify console-only output (no file), verify default DEBUG level | **HIGH** |

**Test Gaps**:
- No validation that `setup_logger` creates a logger with correct name
- No validation that file handler is added when `log_file` is provided
- No validation that console handler is always present
- No validation that log level is configurable
- No validation that `log_chat.py` logger instance is properly initialized

#### 1.2 utils Module — **Partial Coverage (12/14 modules tested)**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `utils/hook_tool.py` | 105 | `HookManager` class — register, execute, hook ordering, error handling | **HIGH** |
| `utils/format_tool_xml.py` | 105 | XML formatting functions — `format_to_xml`, `parse_from_xml`, edge cases with special characters | **MEDIUM** |

**Test Gaps**:
- `hook_tool.py`: No tests for hook registration, execution order, error propagation, duplicate hook handling
- `format_tool_xml.py`: No tests for XML formatting/parsing, special character handling, malformed input

#### 1.3 human Module — **NO TESTS EXIST**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `human/role.py` | 30 | `get_human_name(human_name)` — env variable fallback, default name, prefix handling | **HIGH** |

**Test Gaps**:
- No tests for `get_human_name()` with explicit name
- No tests for `get_human_name()` with env variable `TOPSAILAI_HUMAN_NAME`
- No tests for `get_human_name()` default fallback to "DawsonLin"
- No tests for `HUMAN_STARTSWITH` prefix auto-addition
- No tests for name already having prefix (no double-prefix)

---

### Priority 2: Agent Core (tools, context, prompt_hub, ai_base)

#### 2.1 tools Module — **Partial Coverage (2/12+ modules tested)**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `tools/ctx_tool.py` | 40 | `retrieve_msg(msg_id)` — message retrieval from archived context | **HIGH** |
| `tools/story_memory_tool.py` | 105 | `write_memory`, `read_memory`, `list_memories`, `delete_memory` — CRUD operations on story memory | **HIGH** |
| `tools/story_tool.py` | 105 | Story/context management functions | **MEDIUM** |
| `tools/sandbox_tool.py` | 105 | Sandbox execution functions | **MEDIUM** |
| `tools/collaboration_tool.py` | 105 | Collaboration/coordination functions | **MEDIUM** |
| `tools/cmd_tool.py` | 105 | Command execution wrapper | **MEDIUM** |
| `tools/time_tool.py` | 105 | Time-related tool functions | **MEDIUM** |
| `tools/file_readonly_tool.py` | 105 | Read-only file operations | **MEDIUM** |
| `tools/skill_tool.py` | 105 | Skill invocation tool | **MEDIUM** |
| `tools/subagent_tool.py` | 105 | Sub-agent spawning/management | **LOW** |
| `tools/agent_tool.py` | 105 | Agent tool base functions | **LOW** |
| `tools/base/*.py` | varies | Base tool classes and utilities | **LOW** |

**Test Gaps**:
- `ctx_tool.py`: No tests for `retrieve_msg` with valid/invalid msg_id, no agent object scenario
- `story_memory_tool.py`: No tests for memory CRUD lifecycle, persistence, concurrent access
- All other tool modules: Completely untested

#### 2.2 context Module — **Partial Coverage (3/7+ modules tested)**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `context/prompt_env.py` | 105 | Prompt environment variable management | **HIGH** |
| `context/common.py` | 28 | `get_session_id()` — env variable fallback, date-based generation | **HIGH** |
| `context/ctx_safe.py` | 105 | Safe context access patterns | **MEDIUM** |
| `context/ctx_manager.py` | 105 | Context manager lifecycle | **MEDIUM** |
| `context/token.py` | 105 | Token counting/management | **MEDIUM** |

**Test Gaps**:
- `prompt_env.py`: No tests for environment variable injection into prompts
- `common.py`: No tests for `get_session_id()` with env variable, without env variable, format validation
- `ctx_safe.py`, `ctx_manager.py`, `token.py`: Completely untested

#### 2.3 prompt_hub Module — **NO TESTS EXIST**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `prompt_hub/prompt_tool.py` | 307 | Prompt building, template rendering, variable substitution | **HIGH** |
| `prompt_hub/tools/*.py` | varies | Tool-specific prompt generation | **MEDIUM** |
| `prompt_hub/security/*.py` | varies | Security prompt constraints | **MEDIUM** |
| `prompt_hub/role/*.py` | varies | Role-based prompt templates | **MEDIUM** |
| `prompt_hub/project/*.py` | varies | Project context prompts | **MEDIUM** |
| `prompt_hub/search/*.py` | varies | Search prompt utilities | **MEDIUM** |
| `prompt_hub/context/*.py` | varies | Context prompt builders | **MEDIUM** |
| `prompt_hub/work_mode/*.py` | varies | Work mode prompt templates | **MEDIUM** |
| `prompt_hub/skills/*.py` | varies | Skill prompt templates | **MEDIUM** |
| `prompt_hub/task/*.py` | varies | Task prompt templates | **MEDIUM** |

**Test Gaps**:
- Entire module is untested — 307 lines of core prompt logic with no validation
- No tests for prompt template rendering
- No tests for variable substitution correctness
- No tests for prompt security constraints

#### 2.4 ai_base Module — **Partial Coverage (2/13+ modules tested)**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `ai_base/tool_call.py` | 204 | Tool call parsing, validation, execution | **HIGH** |
| `ai_base/agent_base.py` | 245 | Agent lifecycle, initialization, execution loop | **HIGH** |
| `ai_base/prompt_base.py` | 425 | Prompt construction, system/user message handling | **HIGH** |
| `ai_base/llm_base.py` | 392 | LLM interaction, response parsing, error handling | **HIGH** |
| `ai_base/agent_tool.py` | 169 | Agent tool registration and dispatch | **MEDIUM** |
| `ai_base/llm_control/base_class.py` | 372 | LLM control flow base | **MEDIUM** |
| `ai_base/llm_control/message.py` | 358 | Message construction and management | **MEDIUM** |
| `ai_base/llm_hooks/executor.py` | 75 | Hook executor lifecycle | **MEDIUM** |
| `ai_base/llm_hooks/hook_after_chat/kimi.py` | 65 | Kimi-specific post-chat hook | **LOW** |
| `ai_base/llm_hooks/hook_before_chat/only_one_system_message.py` | 38 | System message dedup hook | **LOW** |
| `ai_base/agent_types/react.py` | 103 | ReAct agent type | **LOW** |
| `ai_base/agent_types/plan_and_execute.py` | 100 | Plan-and-execute agent type | **LOW** |
| `ai_base/constants.py` | 13 | Constants validation | **LOW** |

**Test Gaps**:
- `tool_call.py`: No tests for tool call parsing from LLM responses, validation of malformed calls
- `agent_base.py`: No tests for agent initialization, execution loop, error handling
- `prompt_base.py`: No tests for prompt construction, message ordering, system prompt handling
- `llm_base.py`: No tests for LLM response parsing, retry logic, error handling
- All other modules: Completely untested

---

### Priority 3: Agent Workers (workspace, ai_team, skill_hub)

#### 3.1 workspace Module — **NO TESTS EXIST**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `workspace/lock_tool.py` | 143 | Lock management, concurrent access control | **HIGH** |
| `workspace/print_tool.py` | 161 | Print/output formatting for workspace | **HIGH** |
| `workspace/input_tool.py` | 273 | Input processing and validation | **HIGH** |
| `workspace/task/task_tool.py` | 276 | Task lifecycle management (create, update, complete) | **HIGH** |
| `workspace/context/ctx_runtime.py` | 311 | Runtime context management | **MEDIUM** |
| `workspace/context/instruction.py` | 253 | Instruction processing | **MEDIUM** |
| `workspace/context/base.py` | 252 | Base context class | **MEDIUM** |
| `workspace/context/agent2llm.py` | 196 | Agent-to-LLM message conversion | **MEDIUM** |
| `workspace/context/agent.py` | 112 | Agent context management | **MEDIUM** |
| `workspace/context/agent_tool.py` | 83 | Agent tool context | **MEDIUM** |
| `workspace/context/summary_tool.py` | 50 | Summary generation | **LOW** |
| `workspace/folder_constants.py` | 61 | Folder path constants | **LOW** |
| `workspace/hook_instruction.py` | 312 | Hook instruction processing | **LOW** |
| `workspace/agent/agent_chat_base.py` | 262 | Chat agent base | **LOW** |
| `workspace/agent/agent_shell_base.py` | 248 | Shell agent base | **LOW** |
| `workspace/agent_shell.py` | 246 | Agent shell execution | **LOW** |
| `workspace/llm_shell.py` | 199 | LLM shell execution | **LOW** |

**Test Gaps**:
- Entire module (3891 lines) is completely untested
- No tests for task lifecycle (create → update → complete → DONE file)
- No tests for lock management (acquire, release, timeout)
- No tests for input processing and validation
- No tests for runtime context management

#### 3.2 ai_team Module — **NO TESTS EXIST**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `ai_team/role.py` | 127 | Role definition, member capabilities | **HIGH** |
| `ai_team/manager.py` | 206 | Manager routing, task assignment, coordination | **HIGH** |
| `ai_team/member_agent.py` | 75 | Member agent execution, task handling | **MEDIUM** |
| `ai_team/common.py` | 25 | Common utilities for team | **LOW** |
| `ai_team/constants.py` | 8 | Constants validation | **LOW** |

**Test Gaps**:
- Entire module (441 lines) is completely untested
- No tests for role definition and capability matching
- No tests for manager task routing logic
- No tests for member agent task execution lifecycle

#### 3.3 skill_hub Module — **Partial Coverage (2/3 modules tested)**

| Source File | Lines | Key Functions to Test | Priority |
|-------------|-------|----------------------|----------|
| `skill_hub/skill_hook.py` | 167 | Skill hook registration, execution, lifecycle | **HIGH** |

**Test Gaps**:
- `skill_hook.py`: No tests for hook registration, execution order, error handling

---

## Proposed Test Files (Ordered by Priority)

### Phase 1: Common Utils Tests (Priority 1)

| # | New Test File | Source Module | Key Test Cases |
|---|---------------|---------------|----------------|
| 1 | `tests/unit/test_topsailai_logger_base_logger.py` | `logger/base_logger.py` | setup_logger with name only; setup_logger with file path; setup_logger with level; console handler always present; file handler conditional; logger name correctness |
| 2 | `tests/unit/test_topsailai_logger_log_chat.py` | `logger/log_chat.py` | logger instance name equals "chat"; no file handler (console only); default level is DEBUG |
| 3 | `tests/unit/test_topsailai_utils_hook_tool.py` | `utils/hook_tool.py` | HookManager.register; HookManager.execute in order; error propagation; duplicate hook handling; empty hook list |
| 4 | `tests/unit/test_topsailai_utils_format_tool_xml.py` | `utils/format_tool_xml.py` | format_to_xml basic; format_to_xml special chars; parse_from_xml basic; parse_from_xml malformed; roundtrip format→parse |
| 5 | `tests/unit/test_topsailai_human_role.py` | `human/role.py` | get_human_name explicit; get_human_name from env; get_human_name default; prefix auto-add; no double-prefix |

### Phase 2: Agent Core Tests (Priority 2)

| # | New Test File | Source Module | Key Test Cases |
|---|---------------|---------------|----------------|
| 6 | `tests/unit/test_topsailai_tools_ctx_tool.py` | `tools/ctx_tool.py` | retrieve_msg valid id; retrieve_msg invalid id; retrieve_msg no agent object |
| 7 | `tests/unit/test_topsailai_tools_story_memory_tool.py` | `tools/story_memory_tool.py` | write_memory; read_memory; list_memories; delete_memory; CRUD lifecycle; nonexistent memory |
| 8 | `tests/unit/test_topsailai_tools_story_tool.py` | `tools/story_tool.py` | Story management functions |
| 9 | `tests/unit/test_topsailai_context_prompt_env.py` | `context/prompt_env.py` | Environment variable injection; prompt template with env vars |
| 10 | `tests/unit/test_topsailai_context_common.py` | `context/common.py` | get_session_id with env; get_session_id without env; format validation |
| 11 | `tests/unit/test_topsailai_prompt_hub_prompt_tool.py` | `prompt_hub/prompt_tool.py` | Prompt building; template rendering; variable substitution; security constraints |
| 12 | `tests/unit/test_topsailai_ai_base_tool_call.py` | `ai_base/tool_call.py` | Tool call parsing; validation; malformed input; execution dispatch |
| 13 | `tests/unit/test_topsailai_ai_base_agent_base.py` | `ai_base/agent_base.py` | Agent initialization; execution loop; error handling |
| 14 | `tests/unit/test_topsailai_ai_base_prompt_base.py` | `ai_base/prompt_base.py` | Prompt construction; system message; user message ordering |
| 15 | `tests/unit/test_topsailai_ai_base_llm_base.py` | `ai_base/llm_base.py` | Response parsing; retry logic; error handling |

### Phase 3: Agent Workers Tests (Priority 3)

| # | New Test File | Source Module | Key Test Cases |
|---|---------------|---------------|----------------|
| 16 | `tests/unit/test_topsailai_workspace_lock_tool.py` | `workspace/lock_tool.py` | Lock acquire/release; timeout; concurrent access |
| 17 | `tests/unit/test_topsailai_workspace_print_tool.py` | `workspace/print_tool.py` | Output formatting; special characters; truncation |
| 18 | `tests/unit/test_topsailai_workspace_input_tool.py` | `workspace/input_tool.py` | Input validation; parsing; edge cases |
| 19 | `tests/unit/test_topsailai_workspace_task_task_tool.py` | `workspace/task/task_tool.py` | Task create; update; complete; DONE file creation |
| 20 | `tests/unit/test_topsailai_ai_team_role.py` | `ai_team/role.py` | Role definition; capability matching; member creation |
| 21 | `tests/unit/test_topsailai_ai_team_manager.py` | `ai_team/manager.py` | Task routing; member assignment; coordination logic |
| 22 | `tests/unit/test_topsailai_skill_hub_skill_hook.py` | `skill_hub/skill_hook.py` | Hook registration; execution order; error handling |

---

## Critical Issues from Log Analysis

Based on the log review by @AIMember.mm-m25, the following LLM-related issues should inform test design:

1. **LLM Lazy Execution**: LLM skips `action` step, only outputs `thought` — tests for `tool_call.py` and `agent_base.py` should validate response format enforcement
2. **Missing step_name=action**: Tests for `prompt_base.py` should validate that prompts enforce the `thought → action` pattern
3. **Error Recovery**: Tests for `llm_base.py` should cover retry/recovery logic when LLM produces malformed responses

---

## Summary Statistics

| Category | Source Modules | Existing Tests | Missing Tests | Coverage % |
|----------|---------------|----------------|---------------|------------|
| Common Utils | 14 | 12 | 5 | 86% (by module count, but logger/human fully missing) |
| Agent Core | 30+ | 7 | 15+ | ~23% |
| Agent Workers | 25+ | 2 | 7+ | ~8% |
| **Total** | 69+ | 23 | 22+ | ~33% |

**Recommendation**: Focus on Priority 1 (5 new test files) first, then Priority 2 (10 new test files), then Priority 3 (7 new test files). Total proposed: **22 new test files**.