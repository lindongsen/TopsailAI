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

Items 1–3 and the pair-aware session-tail fix from Item 4 were committed in `f5a0966`. The approved persisted-`tool_calls` fix now normalizes new session writes and validates outgoing messages at a non-bypassable request boundary. Historical database backfill, pair-aware User2Agent deletion, and configured-hook merge semantics remain deferred.

The completed root-cause record remains [issue-agent2llm-summary-orphan-tool-message-400.md](./done/issue-agent2llm-summary-orphan-tool-message-400.md); its incident narrative is not duplicated here.

## Verification Verdicts

| Follow-up | Verdict | Current-code evidence | Status |
|-----------|---------|-----------------------|--------|
| Non-retryable 400 markers were too broad | REAL | The previous `_match_non_retryable_bad_request()` lowercased the whole `BadRequestError` string and applied `marker in message`; built-ins included the generic field names `function_call_output` and `tool_call_id`, so messages such as `Malformed function_call_output item` or `Temporary gateway validation failure for tool_call_id` fast-failed instead of retrying. | Fixed |
| Direct multi-tool and end-to-end tests were missing | REAL | Test collection and source search found no request-boundary cases for two declared calls with both/one output, no pairing assertion under `TOPSAILAI_ENABLE_PARALLEL_TOOL_CALLS=1`, and no real summarization-to-request-builder regression. | Fixed |
| Orphan-drop warning lacked bounded context | REAL | `drop_orphaned_tool_messages()` previously logged only `tool_call_id`; it omitted message index and tool name. | Fixed |
| Residual session producers were not pair-aware | PARTLY-REAL | `cut_messages()` used a count-only tail slice and was safely fixable. Fresh session writes now persist structured `tool_calls`, but arbitrary `del_session_messages()` still deletes exact indexes and historical SDK repr values remain unpairable. | Partially fixed; pair-aware User2Agent deletion and historical backfill deferred |

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

## Design Note: Persisted Session tool_calls Representation

**Verdict: NECESSARY-NOW for forward serialization and request-boundary normalization; a database backfill is NOT NECESSARY now.** The SQL store has no dedicated `tool_calls` column: `chat_history_messages.message` is `TEXT`, containing an outer JSON message. `json_tool.json_dump(..., default=str)` currently converts OpenAI SDK tool-call objects into repr strings. Read-only inspection found 22 non-empty persisted `tool_calls` messages: 21 were lists containing repr strings and one legacy archive-shaped message was one SDK repr string. None exposed an extractable call id; the legacy string failed both `json.loads()` and `ast.literal_eval()`.

A real loaded sample passed through `build_parameters_for_chat()` with `tool_calls` still present as `list[str]`. It is JSON-serializable but violates the OpenAI-compatible `tool_calls` object schema, so a restored session can emit a malformed request. The pairing sanitizers do not remove this malformed assistant field; they only remove orphaned `role="tool"` messages. This is a separate live defect, not merely migration hygiene.

| Option | Scope | Effort | Risk | Benefit | Backfill |
|--------|-------|--------|------|---------|----------|
| A: do nothing | None | S | High for restored native-tool sessions | Keeps current sanitizers only; malformed assistant fields remain reachable | No |
| B: normalize on read only | Session loader plus parser tests | S | Medium: SDK repr is not safely reconstructable with `ast.literal_eval()` | Can accept valid legacy JSON but cannot recover current repr rows | No |
| C: write structured JSON for new rows plus tolerant request-boundary normalization | `json_tool`/session serialization, request formatting, focused tests | M | Low with strict validation and drop-on-malformed fallback | Stops new corruption and prevents old malformed values from reaching the wire | No |
| D: full migration and pair-aware persisted deletion | Option C, one-time backfill, deletion entry points, CLI/tool tests | L | High: legacy SDK repr may be lossy or unparseable | Repairs only rows that can be proven reconstructable and adds atomic deletion | Yes |
| E: runtime-message-based pair-aware deletion | `ctx_runtime.py` deletion paths plus tests | S–M | Medium: works only when runtime messages already contain structured calls | Cheap atomic deletion for fresh structured messages; restored malformed rows still cannot be paired | No |

The earlier claim that pair-aware deletion inherently requires a database backfill was too strong. Deletion can expand indexes from structured in-memory messages, while malformed restored rows use exact deletion and remain protected by normalization. The minimal approved direction is Option C: serialize SDK tool calls to plain dict/list form before persistence, normalize and validate `tool_calls` at the outgoing request boundary, accept already-valid dict/list JSON on read, and drop malformed legacy assistant `tool_calls` with a bounded warning. Do not reconstruct SDK repr with regex or `eval`.

A full backfill or Option D becomes necessary only if operators require historical native-tool conversations to remain replayable with original call pairing, malformed-row volume materially grows, pair-aware persisted deletion becomes a required contract, or sanitization would discard user-visible history. Runtime pair-aware deletion may be added separately after Option C, but it is not a substitute for preventing malformed wire payloads.

### Deferred: Configured Hook Merge Semantics

Changing `TOPSAILAI_HOOK_BEFORE_LLM_CHAT` from replacement to append/merge semantics would alter a public configuration contract beyond this issue’s bounded fixes. It remains a separate design decision; operators who replace the default list must explicitly include the pairing hook.

## Verification

The forward-serialization fix normalizes SDK/Pydantic tool-call objects to plain dict/list values immediately before session persistence. The non-bypassable request boundary normalizes messages before and after configurable formatting hooks, strips unrecoverable legacy repr values with bounded warnings, and then removes their ownerless tool results. No database schema or historical row was changed.

Affected test files pass individually:

| Test file | Result |
|-----------|--------|
| `tests/unit/test_topsailai_context_chat_history_manager___base.py` | 42 passed |
| `tests/unit/test_topsailai_ai_base_llm_control_base_class.py` | 46 passed |
| `tests/unit/test_topsailai_ai_base_multimodal_llm_base.py` | 24 passed |
| `tests/unit/test_topsailai_ai_base_llm_hooks_hook_before_chat_tool_call_pairing.py` | 18 passed |
| `tests/unit/test_topsailai_utils_message_tool_pairing.py` | 35 passed |
| `tests/unit/test_topsailai_context_ctx_manager.py` | 58 passed |
| `tests/unit/test_topsailai_workspace_context_agent2llm.py` | 89 passed |

The first official runner attempt exposed one obsolete multimodal test that asserted an orphan `role="tool"` message survived request construction; its fixture was corrected to include the required assistant owner and then passed individually. The required rerun of `tests/run_tests.py` completed with `Total=206, Passed=206, Failed=0`, exit code `0`, in 303.692 seconds. Database backfill, pair-aware User2Agent deletion, and configured-hook merge semantics remain deferred. No change in this issue is committed or staged.
