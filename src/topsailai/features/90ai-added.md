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
