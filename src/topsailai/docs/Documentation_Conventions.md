---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
---

# Documentation Conventions

How AI-maintained documentation is split and kept consistent in this project.

## `MEMO.md` Is Index Only

`MEMO.md` is injected into the agent context, so it holds only index entries: a heading, a relative link to the owning document, and at most one summary sentence. It MUST NOT accumulate detailed design notes, conventions, or pitfalls.

Routing for the detail itself:

| Detail kind | Owning document |
|---|---|
| Component-level design and conventions | `MEMO.<Component>.md` (`MEMO.CommonUtils.md`, `MEMO.AgentCore.md`, `MEMO.AgentWorkers.md`) |
| Module behavior and options | that module's `readme.md` |
| Test conventions | `tests/*.md` (for example `tests/bdd.md`) |
| Environment variables | `docs/Environment_Variables.md` |
| API request/response contracts | `docs/API.md` |

Maintenance discipline:

- Write the detail into the owning document first, then add or update the pointer in `MEMO.md`.
- If a `MEMO.md` entry grows past a short summary, move its body to the owning document and replace it with a link.
- Sweep relative links after any move or rename: extract every `](...)` target, resolve it against the file's directory, and grep for inbound references to the old path. A rename git reports as clean can still leave dangling links in both directions.

## `features/90ai-added.md` Is Only for Important Features

Only **important** features are recorded in `features/90ai-added.md`. A small or incremental addition (for example a single `/` instruction, a new environment variable, or a minor display/option tweak) must NOT be appended there, even though the general project convention says to document autonomously implemented capabilities.

### Required documentation for a minor change

- Source code plus unit tests.
- `docs/Environment_Variables.md` when an environment variable is added or its semantics change (factual document, always synced).
- The relevant `readme.md` / `MEMO.*.md` table or section when the change alters module behavior or the instruction list.

### Note for maintainers

When unsure whether a change qualifies as "important", prefer not writing to `features/90ai-added.md` and mention the omission in the final answer; the human can request an entry explicitly. This supersedes the blanket "record every autonomously implemented feature" instruction for low-significance changes.
