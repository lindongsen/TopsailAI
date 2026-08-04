---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Issue: Control Channel Idle Accept Delays Agent Exit

## Problem

An idle control-channel listener can remain blocked in `accept()` while the agent exits. `ControlServer.stop()` joined its server thread for up to five seconds, and normal agent-loop exits commonly reached this path through the registered process-exit callback.

## Resolution

`ControlServer.stop()` now makes a local connection to the listener after setting its stop event. This releases the accept loop before the listener is closed, allowing the existing thread join to complete promptly. A regression test verifies that stopping a server configured with a 30-second accept timeout completes in under one second.

## Verification

`tests/run_tests.py --sequential --retries 0 workspace/control_channel/test_handler.py workspace/control_channel/test_protocol.py workspace/control_channel/test_server.py test_topsailai_workspace_agent_agent_shell_base.py` passed: 4 of 4 test files.
