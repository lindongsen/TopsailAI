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
