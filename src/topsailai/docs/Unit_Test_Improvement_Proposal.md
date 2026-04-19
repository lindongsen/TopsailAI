---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai
programming_language: python
---

# Unit Test Improvement Proposal

**Generated**: 2026-04-19
**Reviewer**: km-k25
**Developer**: mm-m25

## Executive Summary

This proposal outlines the gaps in unit test coverage for the TopsailAI Agent project and provides a prioritized plan for enhancing test coverage. The analysis covers 130 source files and 91 existing unit test files.

## Current Test Coverage Analysis

### Statistics
- **Source Files**: 130 Python files
- **Unit Test Files**: 91 test files
- **Coverage**: ~70% of modules have some test coverage

### Existing Test Coverage by Module

| Module | Test Files | Coverage Status |
|--------|-----------|-----------------|
| logger/ | 2 files | Good coverage |
| human/ | 1 file | Basic coverage |
| prompt_hub/ | 1 file | Basic coverage |
| skill_hub/ | 4 files | Good coverage (missing skill_hook.py) |
| context/ | 12 files | Extensive coverage |
| ai_base/ | 10+ files | Good coverage |
| ai_team/ | 2 files | **Missing critical tests** |
| workspace/ | 20+ files | Extensive coverage |
| tools/ | 15+ files | Good coverage |

## Identified Gaps

### 1. CRITICAL: Missing Unit Tests for ai_team Module

**Files without tests:**
- `/root/ai/TopsailAI/src/topsailai/ai_team/common.py` - Session ID generation
- `/root/ai/TopsailAI/src/topsailai/ai_team/constants.py` - Default constants
- `/root/ai/TopsailAI/src/topsailai/ai_team/manager.py` - Team manager logic
- `/root/ai/TopsailAI/src/topsailai/ai_team/member_agent.py` - Member agent system prompt

**Impact**: The ai_team module is core to the multi-agent collaboration workflow. Missing tests here could lead to:
- Session management failures
- Incorrect role assignments
- System prompt generation errors

### 2. HIGH: Missing Unit Tests for skill_hub/skill_hook.py

**File**: `/root/ai/TopsailAI/src/topsailai/skill_hub/skill_hook.py`

**Functions/Classes to test:**
- `get_hooks()` - Hook registration and caching
- `SkillHookData` - Hook data initialization
- `SkillHookHandler` - Hook execution lifecycle

**Impact**: Skill hooks are critical for extending skill functionality. Missing tests could cause:
- Hook execution failures
- Session lock/refresh issues
- Plugin integration problems

### 3. MEDIUM: Incomplete Test Coverage for Existing Modules

#### ai_team/role.py
- `get_manager_name()` - Environment variable handling
- `get_member_name()` - Environment variable handling
- `get_manager_prompt()` - Prompt formatting
- `get_member_prompt()` - Prompt formatting with values file

#### skill_hub/skill_repo.py
- `list_skills()` - Skill listing functionality
- `install_skill()` - Full installation flow (mocked)
- `uninstall_skill()` - Full uninstallation flow

## Improvement Proposal

### Priority 1: ai_team Module Tests (CRITICAL)

#### 1.1 test_topsailai_ai_team_common.py
Test `common.py` functions:
- `get_session_id()` - Test session ID generation from environment and fallback

#### 1.2 test_topsailai_ai_team_constants.py
Test `constants.py`:
- Verify `DEFAULT_HEAD_TAIL_OFFSET` value

#### 1.3 test_topsailai_ai_team_manager.py
Test `manager.py` classes and functions:
- `AITeamManager` class initialization
- `create_team()` method
- `assign_task()` method
- `get_member_status()` method
- Team lifecycle management

#### 1.4 test_topsailai_ai_team_member_agent.py
Test `member_agent.py` functions:
- `extend_system_prompt()` - Environment variable setting
- `get_system_prompt()` - System prompt assembly
- Integration with role module

### Priority 2: skill_hook.py Tests (HIGH)

#### 2.1 test_topsailai_skill_hub_skill_hook.py
Test `skill_hook.py`:
- `get_hooks()` - Hook loading and caching
- `SkillHookData.__init__()` - Initialization with various configs
- `SkillHookData.init()` - Environment-based configuration
- `SkillHookHandler._call_hook()` - Hook execution
- `SkillHookHandler.handle_before_call_skill()` - Pre-skill hooks
- `SkillHookHandler.handle_after_call_skill()` - Post-skill hooks

### Priority 3: Enhanced Coverage for Existing Tests (MEDIUM)

#### 3.1 Enhance test_topsailai_ai_team_role.py
Add tests for:
- Environment variable edge cases
- Values file reading in `get_member_prompt()`
- Error handling for missing files

#### 3.2 Enhance test_topsailai_skill_hub_skill_repo.py
Add tests for:
- `list_skills()` with various folder structures
- `install_skill()` with mocked git operations
- `uninstall_skill()` with file system operations

## Implementation Order

1. **Week 1**: Priority 1 - ai_team module tests
   - test_topsailai_ai_team_common.py
   - test_topsailai_ai_team_constants.py
   - test_topsailai_ai_team_manager.py
   - test_topsailai_ai_team_member_agent.py

2. **Week 2**: Priority 2 - skill_hook tests
   - test_topsailai_skill_hub_skill_hook.py

3. **Week 3**: Priority 3 - Enhanced coverage
   - Enhance existing test files
   - Add edge case tests

## Expected Outcomes

After implementing this proposal:
- **ai_team module**: 100% test coverage
- **skill_hook module**: 100% test coverage
- **Overall project coverage**: Increase from ~70% to ~85%
- **Critical path coverage**: All multi-agent collaboration code tested

## Test Design Guidelines

1. **Mock external dependencies**: Use unittest.mock for file system, environment variables
2. **Test edge cases**: Empty inputs, invalid inputs, boundary conditions
3. **Test error handling**: Verify proper exceptions are raised
4. **Use pytest fixtures**: For common setup/teardown operations
5. **Follow existing patterns**: Match style of existing test files

## Appendix: File Mapping

### Source Files to Test Files Mapping

| Source File | Test File | Status |
|-------------|-----------|--------|
| ai_team/common.py | test_topsailai_ai_team_common.py | MISSING |
| ai_team/constants.py | test_topsailai_ai_team_constants.py | MISSING |
| ai_team/manager.py | test_topsailai_ai_team_manager.py | MISSING |
| ai_team/member_agent.py | test_topsailai_ai_team_member_agent.py | MISSING |
| ai_team/role.py | test_topsailai_ai_team_role.py | EXISTS (needs enhancement) |
| skill_hub/skill_hook.py | test_topsailai_skill_hub_skill_hook.py | MISSING |
| skill_hub/skill_repo.py | test_topsailai_skill_hub.py | EXISTS (needs enhancement) |
| skill_hub/skill_tool.py | test_topsailai_skill_hub_skill_tool.py | EXISTS |

---

**Next Step**: Proceed to Phase 2 - Iterative Code Refinement to implement the missing test files.
