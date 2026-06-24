---
maintainer: human
---

# Main TestCases

WorkFlow: Make Test-Plans(CAN BE Multiple Files) according to docs (NO NEED READ CODE) -> Perform Test-Plans -> Found Any Issues And STOP -> Fix Issues (Include unit-test) -> Review Code for the Issues -> Continue Test-Plans

## 测试维度

1. 权限测试，api_key.role，不同角色的权限不同
2. 集群多节点的模拟测试
3. 触发agent的测试:
  - 多groups并行触发agent的测试
  - mock_agent的答复时间测试，设定不同的sleep时间的测试场景
  - mentions中只有多个 worker-agents，没有manager-agent, 能够并发执行的测试场景

## Mock Requirement

- 尽量让Mock脚本具有通用性，让1个mock脚本可以满足多种测试场景需要
- 不同的测试场景可以对应不同的mock脚本

---

## Manual-Test

References:
- TestCase_manual_cli_permissions.md
- TestCase_manual_cli_cluster.md
- TestCase_manual_cli_agent_trigger.md
- TestCase_manual_xxx.md

TASK: Use cli-terminal to do test, ! cli-terminal MUST run in tmux !
GOAL: Finish Manual-Test for all of functionals/features.

## Integration-Test

References:
- TestCase_integration.md
- TestCase_integration_xxx.md

Scripts:
- tests/integration/

TASK: Implement and Perform Integration-Test scripts.
GOAL: Finish Integration-Test for all of functionals/features.
