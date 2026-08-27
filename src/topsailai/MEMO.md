# TopsailAI Agent

AI-Agent Core, Agent Workers

## Logical Components

1. Common Utils
2. Agent Core       -> Agent Enginering Framework
3. Agent Workers    -> Worker Entry

Folder Details:
```
- Common Utils
  - logger/
  - utils/
  - human/        -> General methods closely related to humans, such as defining names, identity identifiers, etc.

- Agent Core
  - prompt_hub/   -> Prompt Management & External
  - skill_hub/    -> Skill Management & External
  - tools/        -> Agent can use these Tools
  - context/      -> Context Messages Management
  - ai_base/      -> LLM/Agent Enginering Framework

- Agent Workers
  - ai_team/      -> A team work mode
  - workspace/    -> Worker Entry
```

## Split MEMO Documents

The detailed design notes, conventions, and known pitfalls for each logical component have been split into dedicated files:

- [MEMO.CommonUtils.md](./MEMO.CommonUtils.md) — Common Utils (`logger/`, `utils/`, `human/`)
- [MEMO.AgentCore.md](./MEMO.AgentCore.md) — Agent Core (`prompt_hub/`, `skill_hub/`, `tools/`, `context/`, `ai_base/`)
- [MEMO.AgentWorkers.md](./MEMO.AgentWorkers.md) — Agent Workers (`ai_team/`, `workspace/`)

## Architecture Notes

- The **Common Utils** layer provides cross-cutting infrastructure such as logging, thread-local utilities, instruction hooks, and environment/folder resolution.
- The **Agent Core** layer implements the LLM/agent engineering framework, including message constants, context runtime, prompt construction, skill hub, and tool execution.
- The **Agent Workers** layer exposes the user-facing worker entry points, including the workspace shell, agent chat loop, team mode, and session input/output conventions.

For implementation details, environment variables, and coding conventions, refer to the split MEMO files above.

## MEMO: `features/90ai-added.md` Is Only for Important Features

**Date:** 2026-08-27

### Rule

Only **important** features are recorded in `features/90ai-added.md`. A small or incremental addition (for example a single `/` instruction, a new environment variable, or a minor display/option tweak) must NOT be appended there, even though the general project convention says to document autonomously implemented capabilities.

### Required documentation for a minor change

- Source code plus unit tests.
- `docs/Environment_Variables.md` when an environment variable is added or its semantics change (factual document, always synced).
- The relevant `readme.md` / `MEMO.*.md` table or section when the change alters module behavior or the instruction list.

### Note for maintainers

When unsure whether a change qualifies as "important", prefer not writing to `features/90ai-added.md` and mention the omission in the final answer; the human can request an entry explicitly. This supersedes the blanket "record every autonomously implemented feature" instruction for low-significance changes.

## MEMO: Tool Parameter Types Must Assume String-Typed LLM Output

**Date:** 2026-08-27

The full rule lives in [tools/readme.md](./tools/readme.md) — section "Tool Parameter Types Must Assume String-Typed LLM Output".

Summary: LLM response content is non-deterministic, so tool parameters are designed **string-first**; declared `int`/`float` parameters must be converted at runtime and declared `list`/`dict` parameters must attempt `json.loads`, because an argument may arrive as a string. Conversion failures return a machine-readable parameter-error status instead of being disguised as a business status.

## MEMO: BDD Tests for LLM-Related Capabilities Must Drive `llm_mock_server`

**Date:** 2026-08-27

The full rule lives in [tests/bdd.md](./tests/bdd.md) — section "BDD Tests for LLM-Related Capabilities Must Drive `llm_mock_server`".

Summary: any BDD scenario that involves a real LLM interaction must drive `tests/mock/llm_mock_server.py` over the real HTTP/SSE protocol instead of stubbing internal functions, so the client, transport, and parsing layers stay inside the assertion boundary; assert server-side request counts and request bodies, never contact a real external endpoint, and close the scenario's own server and thread in teardown.

## MEMO: `MEMO.md` Is Index Only

`MEMO.md` is injected into the agent context, so it holds only index entries: a heading, a relative link to the owning document, and at most one summary sentence. Details go to the owning doc (`MEMO.<Component>.md`, module `readme.md`, `tests/*.md`, `docs/Environment_Variables.md`, `docs/API.md`); write there first, then link here. Sweep relative links after any move or rename.
