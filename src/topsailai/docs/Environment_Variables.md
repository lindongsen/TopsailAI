## Agent2LLM Summary Session-Message Tuning

These variables tune the conditions under which the Agent2LLM summarizer keeps or drops User2Agent session messages when `TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES` is enabled.

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO` | `0.5` | Maximum ratio of the Agent2LLM quantity threshold that the User2Agent session may occupy before session messages are dropped from the Agent2LLM summary. Must be a float in `(0, 1]`. Values outside this range fall back to `0.5`. |
| `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES` | `17` | Minimum number of extra Agent2LLM messages required beyond the User2Agent session length for the summary to be considered worthwhile. Must be a non-negative integer. Negative values fall back to `17`. |

### Details

- `TOPSAILAI_AGENT2LLM_SUMMARY_SESSION_MAX_RATIO` replaces the previous hard-coded division of the Agent2LLM quantity threshold by `2`. For example, with the default `0.5`, if the effective Agent2LLM quantity threshold is `97`, session messages are dropped when the User2Agent session length reaches `int(97 * 0.5) = 48` messages.
- `TOPSAILAI_AGENT2LLM_SUMMARY_MIN_EXTRA_MESSAGES` replaces the previous hard-coded value `17`. If the total Agent2LLM message count is less than `session_msg_len + min_extra_messages`, summarization is skipped because the context is not long enough to justify a summary.

---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
references:
  - /TopsailAI/src/topsailai/env_template
---

# Environment Variables

This document provides a reference for environment variables used by TopsailAI.

## Context History Thresholds

These variables control when the agent archives or summarizes message history to keep the active context slim.

| Variable | Default | Description |
|----------|---------|-------------|
| `CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS` | `128000` | Token budget used as the denominator for the cached-token ratio threshold check. |
| `CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH` | `43` | Maximum number of messages allowed before context slimming is considered. The effective minimum is `27`. |
| `CONTEXT_MESSAGES_SLIM_THRESHOLD_UNCACHED_TOKENS` | `27000` | Token budget used as the denominator for the uncached-token ratio threshold check. |
| `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD` | `97` | Shared fallback message-count threshold. Used by both layers when their layer-specific threshold is not configured. |
| `TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD` | (unset) | Layer-specific message-count threshold for Agent2LLM. Takes precedence over `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`. |
| `TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD` | (unset) | Layer-specific message-count threshold for User2Agent. Takes precedence over `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`. |
| `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` | `128000` | Token threshold for triggering Agent2LLM context summarization. Set to `0` to disable. |
| `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` | `0` | Token threshold for triggering User2Agent (session) context summarization. Set to `0` to disable (default). |
| `TOPSAILAI_CONTEXT_USER_MESSAGE` | (unset) | File path or raw text used as the first `context_user_message`. Combined with other context user messages into a single user message at session start. |
| `TOPSAILAI_REALTIME_TOKEN_CALCULATION` | `0` | When set to `1`, token counts for summarization thresholds are calculated from the actual message content instead of the cached `TokenStat` value. |

### Details

- **Fallback behavior**: each layer first reads its own threshold (`TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD` or `TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD`). If that value is unset, empty, `0`, or negative, the layer falls back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`. If the shared threshold is also unset, empty, `0`, or negative, quantity-based summarization is disabled for that layer.

- `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD` defines the shared message-count ceiling. If the value is set to `0`, negative, or unset, quantity-based summarization is disabled.
- `CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS` defines the token ceiling against which the ratio `token_count / token_max` is computed. When the ratio reaches `0.8` (configurable via `token_ratio` in code), the context is considered exceeded.
- `CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH` defines the message-count ceiling. If the value is set below `27`, the effective threshold remains `27`.
- `CONTEXT_MESSAGES_SLIM_THRESHOLD_UNCACHED_TOKENS` provides an independent token budget for uncached tokens. The effective threshold is approximately `uncached_token_max * token_ratio`. For example, with the default `27000` and `token_ratio=0.8`, archiving is triggered when uncached tokens reach about `21600`.
- `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` is checked by `ContextRuntimeAgent2LLM.is_need_summarize_for_processing()`. When the current Agent2LLM token usage (`TokenStat.current_tokens`) exceeds this threshold, summarization is triggered in addition to the existing message-count check. Setting this variable to `0` disables the token-based check.
- `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` is checked by `ContextRuntimeData.is_need_summarize_for_processed()`. When the current User2Agent (session) token usage (`TokenStat.current_tokens`) exceeds this threshold, summarization is triggered in addition to the existing message-count check. The default is `0`, which disables the token-based check.
- `TOPSAILAI_REALTIME_TOKEN_CALCULATION` controls whether `_get_current_tokens()` calculates tokens from the actual message content (`1`) or uses the cached `TokenStat.current_tokens` value (`0`, default). When enabled, User2Agent tokens are calculated from `self.messages` and Agent2LLM tokens are calculated from `self.ai_agent.messages`. This variable is read on each call to `_get_current_tokens()`.

The first three variables are read at `ThresholdContextHistory` initialization time and can be overridden per process. `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` and `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` are read on each call to their respective `is_need_summarize_*` methods.

## Session Truncation

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET` | (unset) | Team-specific override for the number of messages to keep from the head and tail when truncating session history for team agents. If set to an integer >= 0, takes precedence over `TOPSAILAI_SESSION_HEAD_TAIL_OFFSET`. |
| `TOPSAILAI_SESSION_HEAD_TAIL_OFFSET` | (unset) | Number of messages to keep from the head and tail when truncating session history on agent startup. If unset, falls back to `DEFAULT_HEAD_TAIL_OFFSET` (`7`). Set to `0` to disable truncation and keep all session messages. Used by `AgentChatBase` via `ctx_manager.cut_messages()`. |

For team agents, the effective offset is resolved in this order:
1. `TOPSAILAI_TEAM_SESSION_HEAD_AND_TAIL_OFFSET` if set and its integer value is >= 0.
2. `TOPSAILAI_SESSION_HEAD_TAIL_OFFSET` if set and its integer value is >= 0.
3. `DEFAULT_HEAD_TAIL_OFFSET` (`7`) otherwise.
