---
maintainer: human
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
ProjectRootFolder: /root/ai/TopsailAI
programming_language: python
test_framwork: pytest

reviewer: km-k25
developer: mm-m25
tester: km-k25
---
# Test

目标:发挥你的想象力，丰富测试用例，保证测试质量。

## Under the workspace

Important Documents:
- readme.md

refer to folders:
- docs/
- tests/

NOTE: The execution time of integration testing is very long. It is recommended to set the tool_call timeout to 600 seconds when executing pytest.

Read relevant folders and files to familiarize oneself with the project.

## Live Integration Test

1. topsailai_agent_daemon, basic functional of server
2. topsailai_agent_client, all of operations of client

[Remember] Always check the `docs/` folder before initiating any tests.
Focus on this log file for errors: /topsailai/log/agent_daemon.log
