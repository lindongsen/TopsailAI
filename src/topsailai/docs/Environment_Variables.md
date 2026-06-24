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
| `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` | `128000` | Token threshold for triggering Agent2LLM context summarization. Set to `0` to disable. |
| `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` | `0` | Token threshold for triggering User2Agent (session) context summarization. Set to `0` to disable (default). |

### Details

- `CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS` defines the token ceiling against which the ratio `token_count / token_max` is computed. When the ratio reaches `0.8` (configurable via `token_ratio` in code), the context is considered exceeded.
- `CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH` defines the message-count ceiling. If the value is set below `27`, the effective threshold remains `27`.
- `CONTEXT_MESSAGES_SLIM_THRESHOLD_UNCACHED_TOKENS` provides an independent token budget for uncached tokens. The effective threshold is approximately `uncached_token_max * token_ratio`. For example, with the default `27000` and `token_ratio=0.8`, archiving is triggered when uncached tokens reach about `21600`.
- `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` is checked by `ContextRuntimeAgent2LLM.is_need_summarize_for_processing()`. When the current Agent2LLM token usage (`TokenStat.current_tokens`) exceeds this threshold, summarization is triggered in addition to the existing message-count check. Setting this variable to `0` disables the token-based check.
- `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` is checked by `ContextRuntimeData.is_need_summarize_for_processed()`. When the current User2Agent (session) token usage (`TokenStat.current_tokens`) exceeds this threshold, summarization is triggered in addition to the existing message-count check. The default is `0`, which disables the token-based check.

The first three variables are read at `ThresholdContextHistory` initialization time and can be overridden per process. `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` and `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` are read on each call to their respective `is_need_summarize_*` methods.
