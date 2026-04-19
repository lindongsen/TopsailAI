---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai
ProjectFolder: /root/ai/TopsailAI/src/topsailai
ProjectRootFolder: /root/ai/TopsailAI
programming_language: python
TestsFolder: /root/ai/TopsailAI/src/topsailai/tests
DocsFolder: /root/ai/TopsailAI/src/topsailai/docs
---

# Test Execution Checklist

## Common Utils Module (Priority 1)

### Logger Tests
- [x] test_topsailai_logger_base_logger.py (23 tests) ✅ — Covers setup_logger, AgentFormatter, log levels, multi-handler, file logging
- [x] test_topsailai_logger_log_chat.py (8 tests) ✅ — Covers log_chat function, message formatting, file output

### Utils Tests
- [x] test_topsailai_utils_format_tool_xml.py (10 tests) ✅ — Covers XML formatting, escaping, nested structures
- [x] test_topsailai_utils_hook_tool.py (15 tests) ✅ — Covers hook registration, execution, chaining, error handling
- [x] test_topsailai_utils_hash_tool.py (13 tests) ✅ — Covers hash computation, file hashing, consistency, edge cases
- [x] test_topsailai_utils_time_tool.py (23 tests) ✅ — Covers time formatting, parsing, timezone handling, edge cases
- [x] test_topsailai_utils_file_tool.py (25 tests) ✅ — Covers file operations, locking, fuzzy matching, edge cases

### Human Tests
- [ ] test_topsailai_human.py — ⏳ Pending

## Agent Core Module (Priority 2)

### Tools Tests
- [ ] test_topsailai_tools.py — ⏳ Pending

### Context Tests
- [ ] test_topsailai_context.py — ⏳ Pending

### Prompt Hub Tests
- [ ] test_topsailai_prompt_hub.py — ⏳ Pending

### AI Base Tests
- [ ] test_topsailai_ai_base.py — ⏳ Pending

## Agent Workers Module (Priority 3)

### Workspace Tests
- [ ] test_topsailai_workspace.py — ⏳ Pending

### AI Team Tests
- [ ] test_topsailai_ai_team.py — ⏳ Pending

### Skill Hub Tests
- [ ] test_topsailai_skill_hub.py — ⏳ Pending

## Test Execution Summary

| Module | Completed Tests | Total Tests | Status |
|--------|----------------|-------------|--------|
| Common Utils - Logger | 31 | 31 | ✅ Complete |
| Common Utils - Utils | 86 | 86 | ✅ Complete |
| Common Utils - Human | 0 | TBD | ⏳ Pending |
| Agent Core | 0 | TBD | ⏳ Pending |
| Agent Workers | 0 | TBD | ⏳ Pending |
| **Total** | **117** | **117+** | **In Progress** |

## Test Quality Metrics

| Metric | Value | Notes |
|--------|-------|-------|
| Total completed test files | 7 | All passing (107 passed) |
| Total completed test cases | 117 | All passing |
| Average test count per file | ~17 | Well-distributed coverage |
| Files under 700-line limit | 7/7 ✅ | All comply with coding requirements |
| English comments only | 7/7 ✅ | All comply with coding requirements |
| Edge case coverage | High | Unicode, empty inputs, error paths covered |

## Next Steps

1. **Priority 1 Remaining**: Create `test_topsailai_human.py` for the human module
2. **Priority 2**: Create tests for Agent Core modules (tools, context, prompt_hub, ai_base)
3. **Priority 3**: Create tests for Agent Worker modules (workspace, ai_team, skill_hub)
4. **Integration Tests**: Plan integration test suite after all unit tests are complete    lock.release = Mock()
    return lock

@pytest.fixture
def mock_env():
    """Mock environment variables"""
    env = {"TEST_VAR": "test_value"}
    return env

@pytest.fixture
def mock_tokenizer():
    """Mock tokenizer for testing"""
    tokenizer = Mock()
    tokenizer.count_tokens = Mock(return_value=100)
    return tokenizer

@pytest.fixture
def mock_summarizer():
    """Mock summarizer for testing"""
    summarizer = Mock()
    summarizer.summarize = Mock(return_value="summary")
    return summarizer

@pytest.fixture
def sample_messages():
    """Sample messages for testing"""
    return [
        {"role": "system", "content": "You are a helpful assistant"},
        {"role": "user", "content": "Hello"},
        {"role": "assistant", "content": "Hi there!"}
    ]

@pytest.fixture
def mock_hooks():
    """Mock hooks for testing"""
    hooks = []
    for i in range(3):
        hook = Mock()
        hook.__name__ = f"hook_{i}"
        hooks.append(hook)
    return hooks
```

### Required Test Utilities

```python
# tests/unit/utils/test_helpers.py

import json
from contextlib import contextmanager

def assert_json_equal(actual, expected):
    """Assert two JSON strings are equal"""
    assert json.loads(actual) == json.loads(expected)

def assert_raises_with_message(exception_class, message, func, *args, **kwargs):
    """Assert function raises exception with specific message"""
    try:
        func(*args, **kwargs)
        assert False, f"Expected {exception_class.__name__}"
    except exception_class as e:
        assert message in str(e), f"Expected '{message}' in '{str(e)}'"

@contextmanager
def mock_context_manager(mock_obj):
    """Context manager for mocking"""
    try:
        yield mock_obj
    finally:
        pass
```

---

## Execution Timeline

### Week 1: Phase 1 - Critical Core
- Day 1-2: ai_base/prompt_base.py tests
- Day 3-4: workspace/task/task_tool.py tests
- Day 5: workspace/context/ctx_runtime.py tests
- Day 6-7: workspace/context/agent2llm.py tests

### Week 2: Phase 2 - Agent Workers
- Day 1-2: workspace/agent/agent_chat_base.py tests
- Day 3: workspace/context/agent.py tests
- Day 4: workspace/context/base.py tests
- Day 5: workspace/context/instruction.py tests
- Day 6: ai_team/manager.py tests
- Day 7: ai_team/member_agent.py tests

### Week 3: Phase 3 - Skill Hub
- Day 1-2: skill_hub/skill_hook.py tests
- Day 3-7: Phase 4 extensions (as time permits)

### Week 4: Phase 4-5 - Extensions & Polish
- Day 1-3: Remaining extension tests
- Day 4-5: Integration testing
- Day 6-7: Documentation and review

---

## Success Criteria

### Coverage Targets
- Phase 1 (P1): >80% line coverage, >75% branch coverage
- Phase 2 (P2): >70% line coverage, >65% branch coverage
- Phase 3 (P3): >70% line coverage, >65% branch coverage
- Phase 4-5 (P4-P5): >60% line coverage, >55% branch coverage

### Quality Criteria
- All tests pass in CI/CD pipeline
- No flaky tests
- Test execution time < 5 minutes for full suite
- No regressions in existing test suite
- All new tests have docstrings
- All tests follow naming convention: `test_<module>_<function>_<scenario>`

### Review Checklist
- [ ] Tests are independent (no test depends on another)
- [ ] Tests are deterministic (same input always produces same output)
- [ ] Tests use appropriate mocks (no external dependencies)
- [ ] Tests cover happy path and error paths
- [ ] Tests have clear assertions
- [ ] Tests are well-documented

---

## Notes

### Mocking Strategy
1. **External Dependencies**: Always mock external services (LLM APIs, databases, file systems)
2. **Internal Dependencies**: Mock at module boundaries to isolate units
3. **State Management**: Use fixtures to manage test state
4. **Cleanup**: Ensure all mocks are cleaned up after each test

### Test Data Management
1. Use fixtures for common test data
2. Keep test data close to tests
3. Use factory functions for complex objects
4. Avoid hardcoding values that might change

### Debugging Failed Tests
1. Run with `-v` flag for verbose output
2. Use `--pdb` to drop into debugger on failure
3. Check mock call counts with `assert_called_once()`
4. Verify mock call arguments with `assert_called_with()`

---

## Appendix: Test File Mapping

| Source Module | Test File | Priority |
|---------------|-----------|----------|
| ai_base/prompt_base.py | tests/unit/ai_base/test_prompt_base_enhanced.py | P1 |
| workspace/task/task_tool.py | tests/unit/workspace/task/test_task_tool.py | P1 |
| workspace/context/ctx_runtime.py | tests/unit/workspace/context/test_ctx_runtime.py | P1 |
| workspace/context/agent2llm.py | tests/unit/workspace/context/test_agent2llm.py | P1 |
| workspace/agent/agent_chat_base.py | tests/unit/workspace/agent/test_agent_chat_base_enhanced.py | P2 |
| workspace/context/agent.py | tests/unit/workspace/context/test_agent_context.py | P2 |
| workspace/context/base.py | tests/unit/workspace/context/test_context_base.py | P2 |
| workspace/context/instruction.py | tests/unit/workspace/context/test_instruction.py | P2 |
| ai_team/manager.py | tests/unit/ai_team/test_manager_enhanced.py | P2 |
| ai_team/member_agent.py | tests/unit/ai_team/test_member_agent_enhanced.py | P2 |
| skill_hub/skill_hook.py | tests/unit/skill_hub/test_skill_hook.py | P3 |
| workspace/context/summary_tool.py | tests/unit/workspace/context/test_summary_tool.py | P4 |
| workspace/context/agent_tool.py | tests/unit/workspace/context/test_agent_tool.py | P4 |
| workspace/agent/hooks/ | tests/unit/workspace/agent/hooks/test_hooks.py | P4 |
| workspace/agent/agent_constants.py | tests/unit/workspace/agent/test_agent_constants.py | P4 |
| workspace/plugin_instruction/skill.py | tests/unit/workspace/plugin_instruction/test_skill_plugin.py | P4 |
| workspace/plugin_instruction/agent.py | tests/unit/workspace/plugin_instruction/test_agent_plugin.py | P4 |
| workspace/plugin_instruction/stat.py | tests/unit/workspace/plugin_instruction/test_stat.py | P4 |
| workspace/plugin_instruction/env.py | tests/unit/workspace/plugin_instruction/test_env_plugin.py | P4 |
| ai_base/agent_types/replan.py | tests/unit/ai_base/agent_types/test_replan.py | P5 |
| ai_base/llm_hooks/hook_after_chat/__init__.py | tests/unit/ai_base/llm_hooks/test_hook_after_chat_init.py | P5 |
| ai_base/llm_hooks/hook_before_chat/__init__.py | tests/unit/ai_base/llm_hooks/test_hook_before_chat_init.py | P5 |
