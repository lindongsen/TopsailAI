---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# Issue: Agent Process Crashes (Terminated Abnormally) When Tee Log Flush Hits ENOSPC

## Symptom

An agent process (`topsailai.3305591`, `session_id=""`) terminated abnormally on a
production qrew data-hub deployment. The direct cause was an UNCAUGHT
`OSError: [Errno 28] No space left on device` raised from the session tee log flush path.
The filesystem was at 97% capacity (remaining ~13 GB). The process died at
`2026-09-01 02:02:40 (+08:00)`.

## Root Cause

The session tee output class in `workspace/print_tool.py` has NO `try/except` around
`self.log_file.flush()` in its `flush()` method (line 102), nor around `write()` (line 98).
When the disk is full, `flush()` raises `OSError: [Errno 28]`. This exception propagates up
through:

- `ai_base/agent_base.py:284` `self.add_assistant_message(response, ...)` — this call is
  OUTSIDE the step-loop `try/except` (which only catches `AgentNoCareResult` /
  `AgentNeedRefreshSession` starting at line 291), so the `OSError` is not handled there.
- `workspace/agent/agent_shell_base.py:140-145` `run()` catches `Exception`, calls
  `update_session_meta_status("error", ...)` (which ALSO fails due to ENOSPC), then `raise`
  re-raises the original `OSError`.
- No top-level handler → process terminates with an uncaught exception.

Full traceback (from `/root/.topsailai/log/topsailai.log.ec`):

```
agent_shell_base.py:137 run → self._run(*args, **kwargs)
agent_shell_base.py:397 _run → self.ai_agent.run(...)
agent_base.py:149 run → self._run(step_call, user_input)
agent_base.py:284 _run → self.add_assistant_message(response, tool_calls=rsp_msg.tool_calls)
prompt_base.py:556 add_assistant_message → print_step(tool_calls, need_format=False)
print_tool.py:541 print_step → print_with_time(msg)
print_tool.py:510 print_with_time → print(content)
workspace/print_tool.py:98 write → self.flush()
workspace/print_tool.py:102 flush → self.log_file.flush()
OSError: [Errno 28] No space left on device
```

## Impact

Any disk write failure (`ENOSPC`, `EIO`, etc.) on the session tee log path directly kills
the agent process. This is more severe than the related session-meta ENOSPC issue (which is
safely swallowed). The process death leaves misleading session bookkeeping (status stuck at
`running`).

## Contrast With Safe Paths

- `events/backends/file.py:146-157` `write()` catches the `OSError` and returns `False`.
- `workspace/session_meta.py` `_atomic_write` catches it and logs.
- Only `workspace/print_tool.py` tee flush is unguarded.

## Suggested Fix (requires human decision — not applied)

Wrap the tee `write()`/`flush()` in `try/except` (consistent with `events/backends/file.py`
and `workspace/session_meta.py`), logging the failure and degrading gracefully (e.g., fall
back to terminal-only output) instead of letting the `OSError` kill the process. Consider
whether the failure should be surfaced to the agent loop as a warning rather than silently
swallowed.

## Reproduction

Not reproduced locally yet; inferred from production observation (`topsailai.3305591`)
where the filesystem hit `ENOSPC`. A targeted test should fill the target volume (or stub
`flush` to raise `OSError(EACCES/ENOSPC)`) and assert that the process does not terminate
abnormally and that the failure is logged / surfaced rather than crashing the agent.
