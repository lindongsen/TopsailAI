---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/tools/human_tool.py
  - /TopsailAI/src/topsailai/utils/env_tool.py
  - /TopsailAI/src/topsailai/utils/thread_local_tool.py
  - /TopsailAI/src/topsailai/workspace/agent/hooks/pre_run_input.py
  - /TopsailAI/src/topsailai/docs/Environment_Variables.md
---

# Issue: `ask_decision` `unavailable` semantics are mis-documented (timeout/TTY causality and non-interactive gate)

## Summary

`docs/Environment_Variables.md` (Human Decision Tool section) describes
`status="unavailable"` as a consequence of the timeout configuration combined
with TTY presence:

> `TOPSAILAI_HUMAN_DECISION_TIMEOUT` | `0` | ... `0` = infinite, but only
> honored when an interactive TTY is present; otherwise returns `unavailable`
> immediately.

The implementation has no such coupling. Availability and timeout are two
independent, sequentially evaluated gates, and the availability gate does not
depend on the timeout value at all. The wording invites two wrong operational
conclusions: that setting a positive timeout avoids `unavailable`, and that a
TTY is the only availability criterion.

## Evidence

`tools/human_tool.py::ask_decision` (evaluation order):

1. Line 266-267: `if not isinstance(question, str) or not question.strip(): return build_result("unavailable", default, -1)`
2. Line 269-271: `if options is not None: if not isinstance(options, list): return build_result("unavailable", default, -1)`
3. Line 276-279: timeout resolution — `if timeout_seconds is None: timeout_seconds = _get_default_timeout()` / `elif timeout_seconds <= 0: timeout_seconds = None`
4. Line 282-284: `if _is_sub_agent_context(): return build_result("unavailable", default, -1)`
5. Line 287-290: `with_timeout, plain = _resolve_input_funcs()` / `if not _has_usable_input_source(with_timeout, plain): return build_result("unavailable", default, -1)`

`_has_usable_input_source()` (line 72-80) accepts three alternative sources, in
priority order, and only the last two are related to interactivity:

```python
if with_timeout or plain:      # thread-local runtime input (session pipe / agent input)
    return True
if not env_tool.is_interactive_mode():   # TOPSAILAI_INTERACTIVE_MODE == "0"
    return False
return sys.stdin.isatty()
```

`_is_sub_agent_context()` (line 84-87) is `get_thread_var(KEY_AGENT_DEEP, 0) > 1`,
i.e. nested `AgentBase.run()` in the *same* thread (`ctxm_set_agent` is the only
increment site, `utils/thread_local_tool.py::ctxm_set_agent`).

`_get_default_timeout()` (line 24-32) only maps `TOPSAILAI_HUMAN_DECISION_TIMEOUT`
to `None` for `<= 0` / non-numeric values; it never inspects TTY or interactive
mode and never produces `unavailable`.

## Concrete mismatches

### Timeout value cannot influence availability

`unavailable` is decided at line 282-290, before any read is attempted. The
resolved `timeout_seconds` is not part of the predicate. Therefore
`TOPSAILAI_HUMAN_DECISION_TIMEOUT=60` or an explicit `timeout_seconds=5` still
returns `unavailable` immediately in a non-interactive, sub-agent, or
bad-argument context. Conversely, `0` (infinite) does not itself cause
`unavailable`; it only means "no deadline" once a usable source exists.

### "interactive TTY" is neither necessary nor sufficient

- Not necessary: inside an `AgentChat` session, `workspace/agent/hooks/pre_run_input.py`
  registers both thread-local input functions, so `_has_usable_input_source()`
  returns `True` on the first branch even with no TTY (input arrives through the
  session named pipe).
- Not sufficient: a TTY does not save a nested-agent call, because the
  sub-agent guard at line 282 runs before the input-source check.

### `TOPSAILAI_INTERACTIVE_MODE=0` does not reliably yield `unavailable`

`pre_run_set_agent_runtime_input` is registered by `call_hooks_pre_run()`, which
`AgentChat.run()` invokes unconditionally (`workspace/agent/agent_shell_base.py:279`)
and the hook itself has no interactive-mode gate. So with
`TOPSAILAI_INTERACTIVE_MODE=0` inside an agent session, the first branch wins and
`ask_decision` performs a blocking session-pipe read and returns `timeout` after
the deadline — not `unavailable`. The `TOPSAILAI_INTERACTIVE_MODE=0 -> unavailable`
path only applies to processes that never installed the runtime input hooks
(direct `llm_shell`, standalone scripts, tool calls executed outside an
`AgentChat` run).

### Resolved: `unavailable` no longer conflates caller misuse with "no channel"

Resolved on 2026-08-27. Argument validation failures now return
`status="invalid_request"` with a machine-readable `reason`, while genuine
nested-agent and absent-input-source conditions retain `status="unavailable"`.
The LLM-facing `PROMPT` documents both statuses and instructs callers to correct
invalid arguments before retrying. The remaining findings in this issue are
unchanged and remain open.

### Sub-agent detection is thread-scoped and can silently miss

`KEY_AGENT_DEEP` lives in thread-local storage. A nested agent executed in a new
thread (for example `tools/agent_tool.py::async_multitasks_agent_writer`, which
spawns `threading.Thread` per task) starts at depth `0`, so the sub-agent guard
does not fire; that thread also has no runtime input hooks, so it falls through
to the interactive/TTY check and may block on `input()` from a worker thread.
The guard therefore neither guarantees sub-agent protection across threads nor
is it documented as thread-scoped.

## Impact

- Operators tune `TOPSAILAI_HUMAN_DECISION_TIMEOUT` expecting it to control
  `unavailable`, which it cannot.
- `TOPSAILAI_INTERACTIVE_MODE=0` is expected to make the tool fail fast, but in
  the main agent path it instead blocks for the full timeout.
- Argument bugs are reported as an infrastructure condition, hiding caller errors.

## Suggested remediation (docs-first, no behavior change required)

- Rewrite the `TOPSAILAI_HUMAN_DECISION_TIMEOUT` description: state that the
  timeout only bounds the wait after a usable input source has been found, and
  that availability is decided independently and earlier.
- Document the three-tier availability rule (thread-local runtime input, then
  `TOPSAILAI_INTERACTIVE_MODE`, then `sys.stdin.isatty()`) and that the runtime
  input hooks make the tool usable without a TTY.
- Document that `TOPSAILAI_INTERACTIVE_MODE=0` does not short-circuit inside an
  `AgentChat` session because the session pipe is registered regardless.
- Document that argument validation failures also return `unavailable`, and that
  the sub-agent guard is thread-local (`KEY_AGENT_DEEP > 1`).
- Optional code follow-up (separate decision): add a machine-readable reason
  field (for example `reason: invalid_question|invalid_options|sub_agent|no_input_source`)
  so callers can branch, and consider a distinct status for argument errors.

## Related minor inconsistency (same module, low severity)

`_get_max_answer_length()` returns `2000` when
`TOPSAILAI_HUMAN_DECISION_MAX_ANSWER_LENGTH` parses to a non-positive integer,
but `8000` when the value is non-numeric, while
`docs/Environment_Variables.md` documents only the `30000` default and no
fallback values. The two different fallback constants look unintentional.

## Reproduction / verification notes

Read-only analysis only; no source modified. Cross-checked against
`tests/unit/test_topsailai_tools_human_tool.py`:
`test_sub_agent_context_returns_unavailable`, `test_no_input_source_returns_unavailable`,
`test_invalid_question_returns_unavailable`, `test_non_list_options_returns_unavailable`,
`test_default_timeout_zero_means_infinite`, `test_default_timeout_unset_returns_none`,
`test_input_fallback_enforces_positive_timeout`. The tests patch
`_has_usable_input_source` / `_resolve_input_funcs` directly, so no test asserts
the documented timeout-to-availability coupling; the mismatch is documentation-only.

## Additional note: `PROMPT` claims "never raises", but prompt rendering is unguarded

The tool-facing `PROMPT` in `tools/human_tool.py` states:

> The tool ALWAYS returns a structured dictionary (never raises)

`ask_decision` calls `prompt = _build_prompt(question, options, eff_allow_free_text, default)`
(line 292) outside any `try`. `_build_prompt` executes
`template.format(question=..., options=..., default=...)` when
`TOPSAILAI_HUMAN_DECISION_PROMPT_TEMPLATE` is set. A template containing an
unknown placeholder (for example `{answer}` or a stray `{`/`}` in literal text)
raises `KeyError` / `ValueError` from `str.format`, which propagates out of
`ask_decision` instead of degrading to `unavailable`. This is a second
doc-vs-code mismatch in the same module and the same "graceful degradation"
contract; the fix is either to guard `_build_prompt` and fall back to the
built-in rendering, or to drop the absolute "never raises" claim.

## Follow-up scalar normalization
On 2026-08-27, explicit human direction changed the request-boundary policy. `allow_free_text` is now an integer flag (`1`/`0`, strings converted with `int()`, no truthy vocabulary) and `timeout_seconds` actively parses finite numeric strings; both advertise those types in `TOOLS_INFO`. Other malformed scalars still return `invalid_request`, and this does not alter the open timeout/availability, TTY, thread-scoped sub-agent, prompt-template, or answer-length findings above.
