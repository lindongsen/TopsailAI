---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - ai_base/llm_base.py
  - utils/message_tool.py
  - context/ctx_manager.py
  - workspace/context/ctx_runtime.py
  - workspace/context/agent_tool.py
  - issues/done/issue-agent2llm-summary-orphan-tool-message-400.md
---

# Issue: Follow-Ups From the Orphan Tool Message 400 Review

## Status

Open. These items came out of the third independent review (reviewer `gpt56sol-programmer`) of
the orphan-tool-message 400 fix program. The reviewer's verdict was **GO-WITH-FOLLOW-UPS**: the
program was committed as-is and the residual items are recorded here instead of delaying it.

None of the items below blocks the committed fix. They are ordered by priority.

## Background

The completed defect record lives in
[issues/done/issue-agent2llm-summary-orphan-tool-message-400.md](./done/issue-agent2llm-summary-orphan-tool-message-400.md).
Its symptom, root cause, evidence chain, fixes A-D, operational mitigation, and verification are
not repeated here; read that file first for context.

## Follow-Up: Non-Retryable 400 Markers Are Broader Than the Proven Provider Phrase

**Severity:** major (non-blocking)

### Evidence

The built-in markers in `ai_base/llm_base.py:27-31` are:

| Marker | Specificity |
|--------|-------------|
| `no tool call found` | Specific — this is the exact proven provider wording |
| `function_call_output` | Generic — a provider protocol item type |
| `tool_call_id` | Generic — a provider protocol field name |

`_match_non_retryable_bad_request()` at `ai_base/llm_base.py:83-106` performs case-insensitive
**substring** matching over the whole `BadRequestError` string, so any 400 whose text merely
mentions one of these names now raises on the first attempt.

### Impact

Deterministic request-shape errors such as `Invalid type for tool_call_id` or
`Malformed function_call_output item` would fast-fail. That is arguably still correct, because the
old retry loop re-sent a byte-identical payload and could not recover. The genuine risk is a
gateway that mis-reports a transient provider-side failure as HTTP 400 while echoing one of these
field names in the message: that case used to recover on retry and now would not.

Rate limiting normally returns HTTP 429 rather than 400, so a rate-limit message matching these
markers is unlikely.

### Recommended Action

- Replace the generic markers with complete known provider phrases, or require contextual
  combinations, for example:
  - `function_call_output` together with `no matching function_call`
  - `tool_call_id` together with `not found` or `preceding message`
- Add **negative** tests proving that unrelated or transient 400 text which merely contains a
  generic field name still follows the normal retry policy. Today the positive cases are covered;
  the negative boundary is not.

## Follow-Up: Missing Direct Multi-Tool-Call Sanitizer Tests

**Severity:** minor

### Evidence

The shared helpers handle multiple declarations correctly by construction — every ID declared by an
assistant message is added to the declared set before later tool messages are evaluated
(`utils/message_tool.py`) — and the existing tests cover the pieces separately:

| Existing coverage | Test |
|-------------------|------|
| Multiple declared IDs | `test_multiple_ids_keep_declaration_order` |
| Pruning a multi-call group | `test_tool_index_pulls_owner_and_sibling_replies`, `test_delete_tool_removes_owner_and_siblings` |
| Hook removes an orphan | hook test module for `ai_base/llm_hooks/hook_before_chat/tool_call_pairing.py` |

What is missing at the **request boundary**:

1. One assistant declaring `call_A` and `call_B` with **both** outputs present — assert nothing is
   dropped.
2. One assistant declaring `call_A` and `call_B` with **only one** output present — assert the
   present output is kept. This locks in the deliberate policy of not dropping trailing unresolved
   tool calls.
3. The `TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS=1` path. Note `parallel_tool_calls` only changes the
   API request parameter (`ai_base/llm_control/base_class.py:301-305`) and does not affect message
   sanitization, so this test is a guard against a future change coupling the two.

Also valuable: one permanent end-to-end regression test chaining the real
`summarize_messages_for_processing()` into `build_parameters_for_chat()` / `format_messages()`. The
third reviewer had to write that probe ad hoc to prove the incident path is closed end to end; a
committed test would keep that proof alive.

## Follow-Up: Orphan-Drop Warning Lacks Bounded Context

**Severity:** minor

### Evidence

`utils/message_tool.py:239-244` logs only:

```
drop orphaned tool message: tool_call_id=<id>
```

This satisfies the project rule that every deletion is logged, and it would have surfaced the
incident call id directly. It does not include the message index, the tool name, or which layer
produced the orphan.

### Recommended Action

Add the message index and, when the field is present, the tool `name`. Do **not** log the tool
result content: it can be arbitrarily large and may carry sensitive data. Keep any preview bounded
and off by default if it is added at all.

## Follow-Up: Residual Non-Pair-Aware Producers Rely on the Request-Boundary Safety Net

**Severity:** minor

### Evidence

Two producers can still split a tool-call pair:

| Producer | Location | Why it is not pair-aware |
|----------|----------|--------------------------|
| Session head/tail truncation on load | `context/ctx_manager.py:449-458` (`cut_messages()`), used by `workspace/agent/agent_chat_base.py:194-209`, team offset via `cli/team_agent.py:117-126` | Still a pure count-based `messages[:offset] + messages[-offset:]` |
| `/ctx.del_msg` and `tool_delete_messages_for_processed()` | `workspace/context/instruction.py`, `workspace/context/agent_tool.py:43-59`, `workspace/context/ctx_runtime.py:160-209` | Routes to `ContextRuntimeData.del_session_messages()`, which deletes exactly the requested indexes |

The session layer cannot currently detect pairing because it stores `tool_calls` stringified
(`context/chat_history_manager/__base.py:299-303`).

Both paths are covered by two safety nets: the sanitizer applied when session messages are copied
into Agent2LLM (`workspace/context/agent.py:135-159`) and the default pre-chat hook applied to every
outgoing request.

### Impact

The safety net disappears if an operator sets `TOPSAILAI_HOOK_BEFORE_LLM_CHAT`, because setting
that variable **replaces** the default hook list and therefore removes the pairing sanitizer. This
footgun is documented in `docs/Environment_Variables.md` and `env_template`, but it remains a
configuration-reachable regression. Until the producers themselves are fixed, a persisted session
can also stay internally inconsistent between rebuilds even though outgoing requests stay valid.

### Recommended Action

- Make `cut_messages()` pair-aware by reusing the shared helpers in `utils/message_tool.py`.
- And/or normalize the persisted session `tool_calls` representation so session-layer pruning can
  become pair-aware, which would also let `del_session_messages()` be fixed.
- Consider appending the pairing sanitizer to a configured hook list instead of replacing the
  defaults, so the safety net cannot be disabled by configuration.

## Scope Note

Deliberately not addressed in the committed change: each item above either changes behaviour beyond
the defect's single logical change (marker strictness, hook-list merge semantics) or adds tests and
log fields that were not required to close the incident. Recording them here keeps the committed
diff minimal and the follow-ups traceable.
