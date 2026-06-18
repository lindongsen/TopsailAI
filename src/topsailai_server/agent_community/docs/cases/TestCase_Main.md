---
maintainer: human
---

# Main TestCases

## 测试维度

1. 权限测试，api_key.role，不同角色的权限不同
2. 集群多节点的模拟测试
3. 触发agent的测试:
  -> 多groups并行触发agent的测试
  -> mock_agent的答复时间测试，设定不同的sleep时间的测试场景
  -> mentions中只有多个 worker-agents，没有manager-agent, 能够并发执行的测试场景
