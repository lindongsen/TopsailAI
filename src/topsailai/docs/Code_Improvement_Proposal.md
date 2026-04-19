---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai
programming_language: python
---

# Code Improvement Proposal

## Overview

This document outlines the unit test enhancement plan for the TopsailAI Agent project.

**Last Updated:** 2026-04-19

## Current Test Coverage Status

### Existing Unit Tests (✓)

The following modules already have unit test coverage:

#### Common Utils
| Module | Test File | Coverage Status |
|--------|-----------|-----------------|
| logger/log_chat.py | test_topsailai_logger_log_chat.py | ✓ Basic |
| logger/base_logger.py | test_topsailai_logger_base_logger.py | ✓ Basic |
| utils/env_tool.py | test_topsailai_utils_env_tool.py | ✓ Basic |
| utils/thread_local_tool.py | test_topsailai_utils_thread_local_tool.py | ✓ Basic |
| utils/hook_tool.py | test_topsailai_utils_hook_tool.py | ✓ Basic |
| utils/time_tool.py | test_topsailai_utils_time_tool.py | ✓ Basic |
| utils/file_tool.py | test_topsailai_utils_file_tool.py | ✓ Basic |
| utils/json_tool.py | test_topsailai_utils_json_tool.py | ✓ Basic |
| utils/hash_tool.py | test_topsailai_utils_hash_tool.py | ✓ Basic |
| utils/print_tool.py | test_topsailai_utils_print_tool.py | ✓ Basic |
| utils/format_tool.py | test_topsailai_utils_format_tool.py | ✓ Basic |
| utils/format_tool_xml.py | test_topsailai_utils_format_tool_xml.py | ✓ Basic |
| utils/text_tool.py | test_topsailai_utils_text_tool.py | ✓ Basic |
| utils/module_tool.py | test_topsailai_utils_module_tool.py | ✓ Basic |
| utils/thread_tool.py | test_topsailai_utils_thread_tool.py | ✓ Basic |
| utils/cmd_tool.py | test_topsailai_utils_cmd_tool.py | ✓ Basic |
| human/role.py | test_topsailai_human_role.py | ✓ Basic |

#### Agent Core
| Module | Test File | Coverage Status |
|--------|-----------|-----------------|
| ai_base/constants.py | test_topsailai_ai_base_constants.py | ✓ Basic |
| ai_base/prompt_base.py | test_topsailai_ai_base_prompt_base.py | ✓ Basic |
| ai_base/prompt_base_threshold.py | test_topsailai_ai_base_prompt_base_threshold.py | ✓ Basic |
| ai_base/agent_base.py | test_topsailai_ai_base_agent_base.py | ✓ Basic |
| ai_base/llm_base.py | test_topsailai_ai_base_llm_base.py | ✓ Basic |
| ai_base/tool_call.py | test_topsailai_ai_base_tool_call.py | ✓ Basic |
| ai_base/agent_types/exception.py | test_topsailai_ai_base_agent_types_exception.py | ✓ Basic |
| ai_base/agent_types/context.py | test_topsailai_ai_base_agent_types_context.py | ✓ Basic |
| ai_base/agent_types/tool.py | test_topsailai_ai_base_agent_types_tool.py | ✓ Basic |
| ai_base/agent_types/_template.py | test_topsailai_ai_base_agent_types__template.py | ✓ Basic |
| ai_base/agent_types/init.py | test_topsailai_ai_base_agent_types_init.py | ✓ Basic |
| ai_base/agent_types/react.py | test_topsailai_ai_base_agent_types_react.py | ✓ Basic |
| ai_base/agent_types/react_community.py | test_topsailai_ai_base_agent_types_react_community.py | ✓ Basic |
| ai_base/agent_types/plan_and_execute.py | test_topsailai_ai_base_agent_types_plan_and_execute.py | ✓ Basic |
| ai_base/llm_control/message.py | test_topsailai_ai_base_llm_control_message.py | ✓ Basic |
| ai_base/llm_control/exception.py | test_topsailai_ai_base_llm_control_exception.py | ✓ Basic |
| ai_base/llm_control/base_class.py | test_topsailai_ai_base_llm_control_base_class.py | ✓ Basic |
| ai_base/llm_control/llm_mistakes/bad_request_error.py | test_topsailai_ai_base_llm_control_llm_mistakes_bad_request_error.py | ✓ Basic |
| ai_base/llm_control/llm_mistakes/base_init.py | test_topsailai_ai_base_llm_control_llm_mistakes_base_init.py | ✓ Basic |
| ai_base/llm_hooks/executor.py | test_topsailai_ai_base_llm_hooks_executor.py | ✓ Basic |
| ai_base/llm_hooks/hook_before_chat/only_one_system_message.py | test_topsailai_ai_base_llm_hooks_hook_before_chat_only_one_system_message.py | ✓ Basic |
| ai_base/llm_hooks/hook_after_chat/kimi.py | test_topsailai_ai_base_llm_hooks_hook_after_chat_kimi.py | ✓ Basic |
| ai_base/llm_hooks/hook_after_chat/minimax.py | test_topsailai_ai_base_llm_hooks_hook_after_chat_minimax.py | ✓ Basic |
| ai_base/agent_tool.py | test_topsailai_ai_base_agent_tool.py | ✓ Basic |
| prompt_hub/prompt_tool.py | test_topsailai_prompt_hub_prompt_tool.py | ✓ Basic |
| skill_hub/__init__.py | test_topsailai_skill_hub.py | ✓ Basic |
| skill_hub/skill_repo.py | test_topsailai_skill_hub_skill_repo.py | ✓ Basic |
| skill_hub/skill_tool.py | test_topsailai_tools_skill_tool.py | ✓ Basic |
| context/token.py | test_topsailai_context_token.py | ✓ Basic |
| context/ctx_manager.py | test_topsailai_context_ctx_manager.py | ✓ Basic |
| context/ctx_safe.py | test_topsailai_context_ctx_safe.py | ✓ Basic |
| context/common.py | test_topsailai_context_common.py | ✓ Basic |
| context/chat_history_manager/__init__.py | test_topsailai_context_chat_history_manager.py | ✓ Basic |
| context/chat_history_manager/sql.py | test_topsailai_context_chat_history_manager_sql.py | ✓ Basic |
| context/chat_history_manager/sql_clean.py | test_topsailai_context_chat_history_manager_sql_clean.py | ✓ Basic |
| context/session_manager/sql.py | test_topsailai_context_session_manager_sql.py | ✓ Basic |
| context/prompt_env.py | test_topsailai_context_prompt_env.py | ✓ Basic |

#### Tools
| Module | Test File | Coverage Status |
|--------|-----------|-----------------|
| tools/base.py | test_topsailai_tools_base.py | ✓ Basic |
| tools/time_tool.py | test_topsailai_tools_time_tool.py | ✓ Basic |
| tools/cmd_tool.py | test_topsailai_tools_cmd_tool.py | ✓ Basic |
| tools/file_tool.py | test_topsailai_tools_file_tool.py | ✓ Basic |
| tools/file_tool_utils_file_read_line.py | test_topsailai_tools_file_tool_utils_file_read_line.py | ✓ Basic |
| tools/file_readonly_tool.py | test_topsailai_tools_file_readonly_tool.py | ✓ Basic |
| tools/file_write.py | test_topsailai_tools_file_write.py | ✓ Basic |
| tools/file_insert.py | test_topsailai_tools_file_insert.py | ✓ Basic |
| tools/file_replace.py | test_topsailai_tools_file_replace.py | ✓ Basic |
| tools/agent_tool.py | test_topsailai_tools_agent_tool.py | ✓ Basic |
| tools/ctx_tool.py | test_topsailai_tools_ctx_tool.py | ✓ Basic |
| tools/story_tool.py | test_topsailai_tools_story_tool.py | ✓ Basic |
| tools/story_memory_tool.py | test_topsailai_tools_story_memory_tool.py | ✓ Basic |
| tools/collaboration_tool.py | test_topsailai_tools_collaboration_tool.py | ✓ Basic |
| tools/sandbox_tool.py | test_topsailai_tools_sandbox_tool.py | ✓ Basic |
| tools/subagent_tool.py | test_topsailai_tools_subagent_tool.py | ✓ Basic |
| tools/stat.py | test_topsailai_context_tool_stat.py | ✓ Basic |

#### Agent Workers
| Module | Test File | Coverage Status |
|--------|-----------|-----------------|
| workspace/lock_tool.py | test_topsailai_workspace_lock_tool.py | ✓ Basic |
| workspace/print_tool.py | test_topsailai_workspace_print_tool.py | ✓ Basic |
| workspace/input_tool.py | test_topsailai_workspace_input_tool.py | ✓ Basic |
| workspace/folder_constants.py | test_topsailai_workspace_folder_constants.py | ✓ Basic |
| workspace/context/__init__.py | test_topsailai_workspace_context.py | ✓ Basic |
| workspace/agent/__init__.py | test_topsailai_workspace_agent.py | ✓ Basic |
| workspace/agent/agent_shell_base.py | test_topsailai_workspace_agent_shell.py | ✓ Basic |
| workspace/llm_shell.py | test_topsailai_workspace_llm_shell.py | ✓ Basic |
| workspace/hook_instruction.py | test_topsailai_workspace_hook_instruction.py | ✓ Basic |
| workspace/plugin_instruction.py | test_topsailai_workspace_plugin_instruction.py | ✓ Basic |
| ai_team/__init__.py | test_topsailai_ai_team.py | ✓ Basic |
| ai_team/role.py | test_topsailai_ai_team_role.py | ✓ Basic |

---

## Missing Unit Tests (Priority Order)

### Priority 1: Core Infrastructure (Critical)

These modules are fundamental to the system and require comprehensive testing:

| Module | Priority | Rationale | Test Scenarios |
|--------|----------|-----------|----------------|
| `ai_base/prompt_base.py` | P1 | Core prompt management | • Message append/reset operations<br>• Threshold context history calculations<br>• Hook execution flows<br>• Message serialization/deserialization<br>• Environment prompt integration |
| `workspace/task/task_tool.py` | P1 | Task lifecycle management | • Task ID generation<br>• TaskData initialization<br>• TaskUtil load/dump operations<br>• File locking in ctxm_process_task<br>• Task status transitions<br>• TeeOutput functionality |
| `workspace/context/ctx_runtime.py` | P1 | Runtime context management | • Session message operations<br>• Message deletion with indexes<br>• Summarization triggers<br>• Context manager integration |
| `workspace/context/agent2llm.py` | P1 | Agent-to-LLM conversion | • Message deletion logic<br>• Summarization with offsets<br>• Threshold detection<br>• Session message preservation |

### Priority 2: Agent Workers (High)

| Module | Priority | Rationale | Test Scenarios |
|--------|----------|-----------|----------------|
| `workspace/agent/agent_chat_base.py` | P2 | Core agent chat controller | • Hook registration and execution<br>• Message routing<br>• Session initialization<br>• Answer formatting<br>• Final answer hooks |
| `workspace/context/agent.py` | P2 | AI Agent context | • Runtime message management<br>• Session message addition<br>• Agent initialization hooks |
| `workspace/context/base.py` | P2 | Base context classes | • Abstract method compliance<br>• Property accessors<br>• Message list operations |
| `workspace/context/instruction.py` | P2 | Instruction handling | • Instruction parsing<br>• Runtime instruction management |
| `ai_team/manager.py` | P2 | Team management | • Member list generation<br>• Team prompt generation<br>• System prompt assembly<br>• Environment variable handling |
| `ai_team/member_agent.py` | P2 | Member agent setup | • System prompt extension<br>• Member prompt retrieval |

### Priority 3: Skill Hub Extensions (Medium-High)

| Module | Priority | Rationale | Test Scenarios |
|--------|----------|-----------|----------------|
| `skill_hub/skill_hook.py` | P3 | Skill execution hooks | • Hook registration<br>• Before/after skill hooks<br>• Session lock/refresh detection<br>• Skill matching logic |

### Priority 4: Workspace Extensions (Medium)

| Module | Priority | Rationale | Test Scenarios |
|--------|----------|-----------|----------------|
| `workspace/context/summary_tool.py` | P4 | Message summarization | • Summary generation<br>• Message compression |
| `workspace/context/agent_tool.py` | P4 | Agent tool integration | • Tool registration<br>• Agent tool execution |
| `workspace/agent/hooks/` | P4 | Agent hooks | • Hook loading<br>• Hook execution order |
| `workspace/agent/agent_constants.py` | P4 | Constants validation | • Default values<br>• Constant definitions |
| `workspace/plugin_instruction/skill.py` | P4 | Skill plugin | • Skill loading<br>• Skill execution |
| `workspace/plugin_instruction/agent.py` | P4 | Agent plugin | • Agent plugin loading |
| `workspace/plugin_instruction/stat.py` | P4 | Statistics | • Stat collection |
| `workspace/plugin_instruction/env.py` | P4 | Environment | • Env variable handling |

### Priority 5: AI Base Extensions (Medium)

| Module | Priority | Rationale | Test Scenarios |
|--------|----------|-----------|----------------|
| `ai_base/agent_types/replan.py` | P5 | Replan agent type | • Replanning logic<br>• Plan adjustment |
| `ai_base/llm_hooks/hook_after_chat/__init__.py` | P5 | Hook initialization | • Module loading |
| `ai_base/llm_hooks/hook_before_chat/__init__.py` | P5 | Hook initialization | • Module loading |

---

## Test Enhancement Recommendations

### 1. Improve Existing Test Coverage

Several existing tests could be enhanced with:
- **Edge case testing**: Empty inputs, None values, boundary conditions
- **Error handling**: Exception paths, invalid inputs
- **Integration scenarios**: Cross-module interactions
- **Mock external dependencies**: Database, file system, environment variables

### 2. New Test Patterns to Implement

```python
# Example: Testing context managers
class TestTaskTool:
    def test_ctxm_process_task_success(self):
        """Test successful task processing with context manager"""
        pass
    
    def test_ctxm_process_task_lock_failure(self):
        """Test task processing when lock cannot be acquired"""
        pass

# Example: Testing complex state transitions
class TestPromptBase:
    def test_message_reset_clears_history(self):
        """Test that reset_messages clears non-system messages"""
        pass
    
    def test_threshold_exceeded_triggers_hooks(self):
        """Test that exceeding token threshold calls context hooks"""
        pass
```

### 3. Test Data Requirements

Create comprehensive test fixtures in `/root/ai/TopsailAI/src/topsailai/tests/unit/conftest.py`:
- Mock session data
- Sample agent configurations
- Test message histories
- Mock environment variables

---

## Implementation Plan

### Phase 1: Critical Core (Week 1)
1. `ai_base/prompt_base.py` - Comprehensive PromptBase testing
2. `workspace/task/task_tool.py` - Task lifecycle testing
3. `workspace/context/ctx_runtime.py` - Runtime context testing
4. `workspace/context/agent2llm.py` - Agent-to-LLM conversion testing

### Phase 2: Agent Workers (Week 2)
1. `workspace/agent/agent_chat_base.py` - Agent chat controller testing
2. `workspace/context/agent.py` - Agent context testing
3. `ai_team/manager.py` - Team management testing
4. `ai_team/member_agent.py` - Member agent testing

### Phase 3: Skill & Extensions (Week 3)
1. `skill_hub/skill_hook.py` - Skill hook testing
2. `workspace/context/` extensions
3. `workspace/plugin_instruction/` modules

### Phase 4: Polish & Integration (Week 4)
1. Enhance existing tests with edge cases
2. Add integration tests
3. Performance testing for critical paths
4. Documentation updates

---

## Success Criteria

- [ ] All Priority 1 modules have >80% test coverage
- [ ] All Priority 2 modules have >70% test coverage
- [ ] All new tests pass in CI/CD pipeline
- [ ] No regressions in existing test suite
- [ ] Test execution time < 5 minutes for full suite

---

## Notes

- Tests should use pytest fixtures for setup/teardown
- Mock external dependencies (database, file system, network)
- Use parameterized tests for multiple input scenarios
- Follow existing test naming conventions: `test_<module>_<function>_<scenario>`
- Add docstrings to all test functions explaining the test purpose
