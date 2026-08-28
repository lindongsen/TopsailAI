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

Open pending Human review and commit. Independent verification classified three items as real and one as partly real. Items 1–3 are fixed in the current unstaged working tree; Item 4 is partially fixed and retains a deferred representation-migration task.

The completed root-cause record remains [issue-agent2llm-summary-orphan-tool-message-400.md](./done/issue-agent2llm-summary-orphan-tool-message-400.md); its incident narrative is not duplicated here.

## Verification Verdicts

| Follow-up | Verdict | Current-code evidence | Status |
|-----------|---------|-----------------------|--------|
| Non-retryable 400 markers were too broad | REAL | The previous `_match_non_retryable_bad_request()` lowercased the whole `BadRequestError` string and applied `marker in message`; built-ins included the generic field names `function_call_output` and `tool_call_id`, so messages such as `Malformed function_call_output item` or `Temporary gateway validation failure for tool_call_id` fast-failed instead of retrying. | Fixed |
| Direct multi-tool and end-to-end tests were missing | REAL | Test collection and source search found no request-boundary cases for two declared calls with both/one output, no pairing assertion under `TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS=1`, and no real summarization-to-request-builder regression. | Fixed |
| Orphan-drop warning lacked bounded context | REAL | `drop_orphaned_tool_messages()` previously logged only `tool_call_id`; it omitted message index and tool name. | Fixed |
| Residual session producers were not pair-aware | PARTLY-REAL | `cut_messages()` used a count-only tail slice and was safely fixable. Arbitrary `del_session_messages()` cannot reliably infer pairing because persisted `tool_calls` is a Python-stringified value. | Partially fixed; migration deferred |

## Fixed: Contextual Non-Retryable 400 Classification

Built-in classification now uses contextual conjunction rules rather than treating generic protocol field names as sufficient by themselves:

- The proven incident phrase `no tool call found` still fails immediately.
- `function_call_output` requires either `no matching function_call` or `no function call found`.
- `tool_call_id` requires either `not found` or `preceding message`.
- `TOPSAILAI_LLM_NON_RETRYABLE_BAD_REQUEST_MARKERS` remains a case-insensitive, semicolon-separated provider-extension mechanism. Configured substring rules extend and cannot disable the built-ins.
- The extension default is now empty so the environment template does not re-enable the former broad field-name behavior.

Positive tests retain first-attempt failure for `No tool call found for function call output with call_id fc_...` and contextual variants. Negative tests prove unrelated HTTP 400 text that merely mentions `function_call_output` or `tool_call_id` still follows the configured retry policy and can recover.

## Fixed: Multi-Tool and End-to-End Regression Coverage

Permanent tests now cover:

- one assistant declaration containing `call_A` and `call_B` with both outputs present;
- the same declaration with only one output present, preserving the deliberate policy that unresolved trailing declarations are not dropped;
- request construction with `TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS=1`, proving the API parameter does not bypass message sanitization;
- real `summarize_messages_for_processing()` followed by real `build_parameters_for_chat()` and `format_messages()`, proving no orphaned tool result reaches the outgoing request.

## Fixed: Bounded Orphan-Drop Warning Context

The deletion warning now records message `index`, `tool_call_id`, and tool `name` when present. It deliberately excludes tool-result content because results can be large or sensitive. Tests assert the bounded fields and confirm result content is absent from logs.

## Partially Fixed: Session Producer Pairing

`context/ctx_manager.py::cut_messages()` now expands the retained tail start through `expand_tail_start_for_tool_pairing()`, bounded by the retained head. Session load truncation therefore no longer starts with a tool result whose declaring assistant was cut away.

### Deferred: Arbitrary Persisted-Session Deletion

`ContextRuntimeData.del_session_messages()`, `/ctx.del_msg`, and `tool_delete_messages_for_processed()` still delete the requested persisted-session indexes exactly. Pair-aware deletion is deferred because `context/chat_history_manager/__base.py` stores `tool_calls` with Python `str(...)`, not normalized JSON. Reusing the shared pairing helpers directly would silently provide incomplete behavior for historical and current persisted rows.

A complete follow-up must:

- persist `tool_calls` as normalized JSON;
- load both normalized JSON and legacy Python-stringified rows safely;
- define migration and malformed-row behavior;
- add pair-aware deletion only after the representation is reliably parseable;
- test deletion through both human instruction and agent-tool entry points.

This is a representation migration rather than a small sanitizer fix and is deliberately not half-implemented here. Outgoing requests remain protected by pair-aware session-tail truncation, Agent2LLM session-import sanitization, and the default request-boundary sanitizer.

### Deferred: Configured Hook Merge Semantics

Changing `TOPSAILAI_HOOK_BEFORE_LLM_CHAT` from replacement to append/merge semantics would alter a public configuration contract beyond this issue’s bounded fixes. It remains a separate design decision; operators who replace the default list must explicitly include the pairing hook.

## Verification

Affected test files pass individually:

| Test file | Result |
|-----------|--------|
| `tests/unit/test_topsailai_ai_base_llm_base.py` | 69 passed |
| `tests/unit/test_topsailai_ai_base_llm_hooks_hook_before_chat_tool_call_pairing.py` | 18 passed |
| `tests/unit/test_topsailai_utils_message_tool_pairing.py` | 35 passed |
| `tests/unit/test_topsailai_ai_base_llm_control_base_class.py` | 42 passed |
| `tests/unit/test_topsailai_context_ctx_manager.py` | 58 passed |
| `tests/unit/test_topsailai_workspace_context_agent2llm.py` | 89 passed |

The official runner `python tests/run_tests.py -w 4 --timeout 180` completed with `Total=206, Passed=206, Failed=0` in 161.981 seconds. Its log is `.tmp/fix_followups/run_tests.log`. No change in this issue is committed or staged.
