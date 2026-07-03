---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# AI-Added Features

## Context User Messages

Added an agent-dimension `context_user_messages` list to `PromptBase` that is seeded from `TOPSAILAI_CONTEXT_USER_MESSAGE` (file path or raw text). When non-empty, the items are combined into a single user message using the `---\n<content>\n---` separator format and injected at the start of each session via `new_session()`. The `_build_context_message()` helper is role-agnostic so future `context_xxx_messages` (e.g. `context_assistant_messages`) can reuse the same formatting logic. `reset_messages()` preserves `context_user_messages` because it is agent-dimension state.

## Duplicate Tool-Call Detection

Implemented infrastructure to detect consecutive duplicate tool calls in the agent ReAct loop. The purpose is to catch accidental or model-induced repeated invocations of the same tool with the same arguments, which can waste tokens, trigger rate limits, or loop forever.

Key logic:
- `ToolStat._normalize()` serializes tool arguments deterministically (sorted dict keys, sorted sets, stable list/tuple handling) so semantically identical calls produce identical signatures.
- `ToolStat.is_last_call_duplicate()` compares the most recent recorded call with the previous one using the normalized signature.
- `get_agent_tool_stat()` retrieves the `ToolStat` instance bound to the current agent via thread-local storage, ensuring per-agent isolation instead of sharing a global counter.
- `record_tool_call()` now routes through the agent-bound `ToolStat` so duplicate detection is scoped to the active agent.
- `detect_duplicate_tool_call()` decorator is defined and ready to wrap `exec_tool_func()` in `ai_base/agent_types/tool.py`, but is intentionally not applied yet pending human approval.

System impact: Existing behavior is unchanged because the decorator is not wired in. Once applied, duplicate calls will be detectable at execution time, enabling future mitigation such as returning a cached result, emitting a warning, or aborting the loop.

## Input History Rotation

Added size-based rotation for the JSONL input history file (`input_history.jsonl`) so it no longer grows without bound.

Key logic:
- Two new environment variables control rotation: `TOPSAILAI_INPUT_HISTORY_MAX_SIZE` (default 1048576 bytes, i.e. 1 MiB) and `TOPSAILAI_INPUT_HISTORY_MAX_BACKUP` (default 1 backup).
- `append_input_history_jsonl()` checks the current history file size before appending. If the size exceeds the configured maximum, it rotates existing backups and renames the current file to the first backup slot.
- Values below 0 for either variable disable rotation or backup retention respectively.
- Rotation is performed before writing the new entry, so the active history file always stays near or below the configured size.

System impact: Prevents long-running sessions from producing an unbounded `input_history.jsonl`. Existing history is preserved as `.1.jsonl` (and higher indexes up to the backup limit) before truncation.
