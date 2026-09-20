---
maintainer: AI
references:
  - ai_base/agent_base.py
  - ai_base/agent_runtime.py
  - ai_base/agent_types/context.py
  - context/tool_stat.py
  - utils/thread_local_tool.py
---

# Feature: Centralized Agent Runtime Access

## Overview

TopsailAI centralizes frequently used agent-scoped runtime objects behind `AgentBase.runtime`. The runtime facade provides one typed and discoverable access path for the current agent, LLM model, token statistics, tool statistics, request statistics, state visualizer, Agent2LLM messages, Agent-scoped tools, and maximum token setting.

The intended access chain for code that cannot receive explicit dependencies is:

```text
get_agent_object() -> AgentBase -> agent.runtime -> runtime component
```

This design keeps `AgentBase` as the runtime aggregation root while avoiding additional process-global access points.

## Motivation

Runtime objects were previously reached through several unrelated paths, including nested `agent.llm_model` attributes, dynamically attached statistics, thread-local helpers, and module-level fallbacks. This caused several problems:

- Callers needed to know internal object layout instead of using a stable runtime boundary.
- `ToolStat` ownership was unclear because it could be found on the model, the agent, or a module default.
- Ownership and shutdown responsibilities were difficult to distinguish from convenience access.
- Direct attribute chains made component replacement and test doubles more fragile.
- Adding another global registry would have increased shared mutable state and concurrency risk.

The centralized runtime facade makes access consistent without changing the established ownership model.

## Core Design

### AgentBase as the Aggregation Root

`AgentBase` remains the authoritative agent-scoped runtime object. It constructs and owns its normal runtime dependencies and exposes one `AgentRuntime` instance through `self.runtime`.

`AgentRuntime` is both:

- a typed facade for frequently used runtime objects; and
- the container for components whose ownership belongs at the agent runtime level.

It currently exposes:

- `agent`
- `llm_model`
- `token_stat`
- `tool_stat`
- `agent2llm_messages`
- `available_tools`
- `llm_request_stat`
- `state_visualizer`
- `max_tokens`

`agent2llm_messages` dynamically returns the current `agent.messages` list. It represents the temporary Agent2LLM ReAct context and is not the persistent User2Agent messages managed by `ContextRuntimeData`.

`available_tools` dynamically returns the current Agent-scoped `agent.available_tools` mapping without taking ownership or maintaining a second registry. Tool registration and removal must continue through the Agent's management methods.

### Current-Agent Location Remains Separate

Thread-local state continues to locate only the current `AgentBase`. It does not independently register every runtime component. Callers that require current-agent access derive all runtime shortcuts from `get_agent_object().runtime`.

`AgentContextInstance` remains a compatibility-oriented current-agent locator. Its `runtime` property delegates to the current agent, and it does not duplicate the component resolution rules maintained by `AgentRuntime`.

## Ownership and Lifecycle

The ownership model is explicit:

```text
AgentBase owns LLMModel
LLMModel owns TokenStat
AgentRuntime owns ToolStat
```

`AgentRuntime` borrows references to objects owned by `AgentBase` or `LLMModel`; it does not duplicate ownership and must not close those objects. In particular, `AgentBase` remains responsible for closing `LLMModel`.

This distinction prevents convenience access from becoming a second lifecycle manager and avoids duplicate cleanup.

## Implementation Principles

### Dynamic Read-Only Properties

Borrowed components are exposed through dynamic read-only properties rather than cached snapshots. If an agent component such as `llm_model` is replaced, later runtime access resolves the current object automatically.

### Weak Agent Reference

`AgentRuntime` keeps a weak reference to its agent. The facade therefore does not create a strong reference cycle or extend the agent lifetime. Access after the agent has been collected fails explicitly rather than returning stale state.

### Import Boundaries

Type-only references to `AgentBase` use `TYPE_CHECKING` so runtime imports do not create a circular dependency between the agent and its facade.

### Duck-Typed Compatibility

The facade accepts compatible agent-shaped objects instead of requiring a strict runtime `isinstance` check. This keeps lightweight test doubles practical while preserving the production contract through the expected attributes.

### Typed Surface, Not a General Registry

`AgentRuntime` exposes explicit, stable properties. It must not become a Service Locator containing every runtime object, including session state, configuration, hooks, or task state. It must not absorb process-global registries, provider pools, static configuration, independent `LLMChat` objects, or other objects outside the Agent lifecycle.

## Access Priority

Runtime access follows this priority:

1. Pass the concrete dependency explicitly when the call boundary supports dependency injection.
2. Use an explicitly available agent and access the component through `agent.runtime` when a runtime shortcut is appropriate.
3. In tools, hooks, callbacks, and similar boundaries where explicit propagation is impractical, locate the current agent with `get_agent_object()` and derive the component from its `runtime` facade.
4. Preserve a documented compatibility fallback only where legacy agent shapes or no-agent operation are part of the existing contract.

New process-global runtime entry points must not be introduced. Independent `LLMModel` or `LLMChat` flows that have no agent continue to manage and access their own components directly.

## Compatibility Rules

- Existing public compatibility properties remain available while callers migrate incrementally.
- `get_agent_tool_stat()` prefers `agent.runtime.tool_stat` but retains legacy and no-agent fallbacks where required.
- `AgentContextInstance.max_tokens` prefers the current runtime and retains its environment fallback when no current agent is available.
- Migration must occur by logical module so each change remains independently testable and reviewable.

## Future Evolution

The current-agent locator uses thread-local storage because it matches the existing synchronous execution model. A migration to `contextvars.ContextVar` should be considered only when TopsailAI introduces or demonstrates concurrent asynchronous agent tasks in the same thread, task-context propagation requirements, or a reproducible context-isolation failure.

If that condition is met, the locator implementation may change while preserving the public access chain through `get_agent_object().runtime`. The runtime facade itself should remain the stable component boundary.
