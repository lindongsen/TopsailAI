---
maintainer: AI
author: DawsonLin
---
# Plugin tool prompts resolve the wrong module

Trigger: assistant tool migration to an explicitly loaded plugin. Prompt lookup and reload hardcoded the core namespace, dropping optional-plugin policy text. Imported helper functions retain their core __module__, so that attribute cannot identify the registration owner.

Repair: capture registration module provenance through an optional discovery output; registry owns the mapping and prompt/observation/reload lookup prefers it. Keep existing env defaults and explicit-only loading unchanged.

Verification: in progress; see .task/check_20261104T140911_agent-tool-to-plugin.md.
