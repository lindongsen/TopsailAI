---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - ai_base/llm_base.py
  - workspace/agent/agent_shell_base.py
  - utils/input_tool.py
  - utils/thread_local_tool.py
  - utils/env_tool.py
---

# Issue: LLM Chat Retry Exhaustion Should Not Exit Directly in Interactive Mode

## Status

Resolved. Full unit and BDD regression gates passed on 2026-09-07.

## Problem

When `LLMChat.chat()` exhausts its retry loop, it unconditionally raises
`Exception("chat to LLM is failed")` at `ai_base/llm_base.py:1288`. The
exception propagates up through the agent loop to `AgentChat.run()` in
`workspace/agent/agent_shell_base.py`, which catches it, sets the session meta
status to `"error"`, and re-raises — terminating the agent process.

In interactive mode the user is left with no chance to intervene: the agent
simply dies after a long blind retry window, discarding all in-progress work.

### Real Incident

Session `20260904T153008` (manager agent, model `DeepSeek-V4-Flash-Preview`):
the LLM service returned the special retry response `服务器繁忙，请稍后再试。`
for 18 consecutive attempts (17:14:13 → 17:36:45). The `chat()` retry loop
(`retry_times = 17`, `for i in range(100)`, `if i > retry_times: break`)
exhausted all attempts and raised `"chat to LLM is failed"`, killing the
manager at 17:37:02 with session meta `status: error`. The coordinated qrew
6A.5 work was left incomplete and the next atomic task was never dispatched.

## Current Behavior

1. `chat()` retry loop: `ai_base/llm_base.py:1077-1288`
   - `retry_times = 17` (line 1077)
   - `for i in range(100)` (line 1084)
   - `if i > retry_times: break` (line 1099)
   - final `raise Exception("chat to LLM is failed")` (line 1288)
2. The `except (KeyError, Exception)` branch (lines 1279-1286) already offers an
   interactive `>>> LLM Retry [yes/no]` prompt on the main thread, but the
   special-response path (`ModelServiceError` / `LLMServiceSpecialResponseError`,
   lines 1240-1267) never reaches that prompt — it just sleeps and retries until
   the loop breaks and raises.
3. `AgentChat.run()` (`agent_shell_base.py:114-140`) catches the exception,
   calls `update_session_meta_status("error", ...)`, and re-raises → process exit.

## Desired Behavior

In interactive mode (`env_tool.is_interactive_mode()`, default true), when the
retry loop is exhausted the agent should NOT exit directly. Instead it should
present the user with a choice, for example:

- **Retry** — continue the retry loop (reset the attempt counter / keep trying).
- **Back to chat (user2agent)** — return control to the main agent loop so the
  user can type a new message or decide the next step, instead of losing the
  session.
- **Exit / Abort** — keep the current behavior (raise and exit).

In non-interactive mode the current behavior (raise and exit) should be
preserved so automation still fails fast.

## Proposed Implementation Direction

- In `chat()` (`llm_base.py`), before the final `raise`, check
  `env_tool.is_interactive_mode()` and prompt the user with a menu using the
  existing input helpers (`get_agent_runtime_input()` /
  `input_yes_or_no()` / `input_message()`).
- For "Back to chat", raise a dedicated, catchable signal (e.g. a new
  `LLMChatFailedError` or reuse `AgentEndProcess`) that the agent loop in
  `agent_shell_base.py` catches and treats as "return to user input" — i.e.
  continue the `while True` loop to read the next message, mirroring the
  existing `HardInterruptError` handling (lines 398-404) which sets
  `self.interrupted = True` and continues.
- For "Retry", reset the retry counter and `continue` the loop.
- Keep the existing `>>> LLM Retry [yes/no]` prompt in the generic
  `except (KeyError, Exception)` branch consistent with the new menu.

## Design Considerations

- The special-response path (`服务器繁忙` etc.) currently bypasses the
  interactive prompt entirely; the new menu must be reachable from that path
  too, not only from the generic exception branch.
- A 23-minute blind retry window is too long to leave the user without control;
  consider surfacing the choice earlier (e.g. after a configurable number of
  consecutive special responses) rather than only at final exhaustion.
- The "Back to chat" path must not corrupt session state: the failed turn should
  be recorded so the user can decide whether to retry the same request or send a
  new one.
- Non-interactive callers (sub-agents, automation, `TOPSAILAI_INTERACTIVE_MODE=0`)
  must keep the fail-fast raise so they do not hang waiting for input.

## Verification

- Interactive mode: exhaust the retry loop (e.g. force a persistent
  `服务器繁忙` response) and confirm the menu appears with Retry / Back to chat /
  Exit; each choice behaves as specified.
- Non-interactive mode: confirm the exception still raises and the process exits
  with session meta `status: error`.
- Regression: existing retry-loop unit tests in
  `tests/unit/test_topsailai_ai_base_llm_control_base_class.py` and related
  suites must continue to pass.
