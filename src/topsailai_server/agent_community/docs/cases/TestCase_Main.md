---
maintainer: human
---

# Main TestCases

WorkFlow: Make Test-Plans(CAN BE Multiple Files) according to docs (NO NEED READ CODE) -> Perform Test-Plans -> Found Any Issues And STOP -> Fix Issues -> Review Code for the Issues -> Continue Test-Plans

## 测试维度

1. 权限测试，api_key.role，不同角色的权限不同
2. 集群多节点的模拟测试
3. 触发agent的测试:
  -> 多groups并行触发agent的测试
  -> mock_agent的答复时间测试，设定不同的sleep时间的测试场景
  -> mentions中只有多个 worker-agents，没有manager-agent, 能够并发执行的测试场景

---

## Manual-Test

TASK: Use cli-terminal to do test, ! cli-terminal MUST run in tmux !
GOAL: Finish Manual-Test for all of functionals/features.
