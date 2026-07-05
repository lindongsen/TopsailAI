# MEMO: Agent Core

This document collects design notes, conventions, and known pitfalls for the **Agent Core** layer:

- `prompt_hub/` — Prompt Management & External
- `skill_hub/` — Skill Management & External
- `tools/` — Agent Tools
- `context/` — Context Messages Management
- `ai_base/` — LLM / Agent Engineering Framework

## Core Modules

### Thread-Local Agent Object

References:
- ai_base/agent_base.py
- ai_base/llm_base.py
- ai_base/prompt_base.py
- context/token.py
- utils/thread_local_tool.py

During agent execution, the current `agent_object` (an `AgentBase` instance) is stored in thread-local storage. This allows any code running within the same thread — particularly tools — to access the active agent's state without explicit parameter passing.

The thread-local utilities are provided by `utils/thread_local_tool.py`:

- `ctxm_set_agent(agent_obj)` — Context manager that sets the agent object in thread-local storage for the duration of the context. It also tracks recursion depth via `KEY_AGENT_DEEP` and enforces a maximum depth of `MAX_AGENT_DEEP` (default 3).
- `get_agent_object()` — Retrieves the current agent object from thread-local storage, or `None` if not set.

**Typical use case in tools:**

When a tool needs to inspect or use the current agent's messages, it can retrieve the agent object from thread-local storage:

```python
from topsailai.utils.thread_local_tool import get_agent_object

def my_tool():
    agent = get_agent_object()
    if agent:
        messages = agent.messages
        # Use messages for context-aware processing
```

**Accessing related runtime objects:**

From the agent instance, you can also reach the underlying LLM model and its token statistics:

```python
from topsailai.utils.thread_local_tool import get_agent_object

def my_tool():
    agent = get_agent_object()
    if agent and agent.llm_model:
        llm_model = agent.llm_model          # LLMModel instance (ai_base/llm_base.py)
        token_stat = agent.llm_model.tokenStat  # TokenStat instance (context/token.py)
```


## Tool Execution Entry Point

**Date:** 2026-06-27
**File:** `/TopsailAI/src/topsailai/ai_base/agent_types/tool.py`

### Conclusion
The immediate entry point for executing a single tool call is the standalone function `exec_tool_func(tool_func, args, tool_name)` in `/TopsailAI/src/topsailai/ai_base/agent_types/tool.py`.

### What it does
- Calls `tool_func(**args)`.
- Catches exceptions (except `AgentToolCallException`, which is re-raised).
- Records the call via `tool_stat.record_tool_call(...)`.
- Truncates the stringified result if it exceeds `TOPSAILAI_TOOL_CALL_MAXIMUM_RETURN`.
- Returns the raw result, a truncated string, or an error string.

### Caller context
`exec_tool_func` is invoked by `StepCallTool.execute_step_action()` in the same file, which is part of the ReAct step loop. `execute_step_action()` is responsible for:
- Parsing the tool-call step.
- Resolving the tool name via `get_tool_func(tools, tool)`.
- Calling `exec_tool_func`.
- Handling `AgentFinalAnswer` to complete the task.

### Note for maintainers
When tracing how an agent invokes a tool, start at `StepCallTool.execute_step_action()` for the step-loop perspective, and at `exec_tool_func()` for the actual tool-function invocation, exception handling, and result truncation.

### Context Archiving via `link_message`

References:
- ai_base/prompt_base.py
- context/chat_history_manager/__base.py
- context/ctx_manager.py

The agent keeps a running message history in `agent.messages` (managed by `PromptBase`). As the conversation grows, the context can exceed token or length thresholds. To keep the active context slim without losing information, the system archives oversized message fragments into persistent storage and replaces them with lightweight references.

This archiving logic is triggered automatically inside `PromptBase.append_message()` via `PromptBase.call_hooks_ctx_history()`:

1. **Session recording** — If a session ID exists, the last appended message is persisted via `hook.add_session_message()` (unless it is a system message).
2. **Threshold check** — `ThresholdContextHistory.is_exceeded()` evaluates whether the context needs slimming. It checks:
   - Message count against `CONTEXT_MESSAGES_SLIM_THRESHOLD_LENGTH` (default 43, minimum 27).
   - Token usage ratio against `CONTEXT_MESSAGES_SLIM_THRESHOLD_TOKENS` (default 128000) multiplied by `token_ratio` (0.8).
   - Prefers `agent.llm_model.tokenStat.uncached_tokens` when available; falls back to `count_tokens(str(messages))`.
3. **Archive pass** — When exceeded, each configured context-history manager (`ChatHistoryBase`) runs `link_messages(messages)`.

The actual archive transformation is implemented in `context/chat_history_manager/__base.py` by `ContextManager.link_messages()`:

- **Scan range** — Processes messages from `NON_SYSTEM_PROMPT_MESSAGE_INDEX` (default 3) up to `index_end=-11`, i.e. it skips the system prompts at the head and the most recent messages at the tail.
- **Eligible roles** — Ignores `system` and plain `user` messages, except user messages that carry a `tool_call_id` (tool observations).
- **Eligible content** — Only `action` and `observation` step names are considered for archiving.
- **Size gate** — A content fragment is archived only when `len(str(content_dict)) > max_size` (default 1024 bytes).
- **Storage** — `ContextManager._link_msg_id()` stores the original content in `chat_history_messages` keyed by an MD5 `msg_id`, creates a session mapping, and replaces the in-place content with:

```json
{"step_name": "archive", "raw_text": "retrieve_msg by msg_id=<msg_id>"}
```

- **Cleanup** — After archiving, `tool_calls` are removed from the message (but `tool_call_id` is intentionally preserved to avoid `bad_request_error`).

Archived messages can later be retrieved by `msg_id` using `ContextManager.retrieve_message(msg_id)` or loaded for an entire session via `retrieve_messages(session_id)`.

**Key design considerations:**

- Archiving is transparent to the LLM: the active context still contains a placeholder, while the heavy payload lives in persistent storage.
- Only `action`/`observation` payloads are archived because they tend to be the largest and are less critical for immediate reasoning than recent user/assistant turns.
- The tail window (`index_end=-11`) is preserved so the most recent context remains fully materialized for the next LLM call.
- Errors during hook execution are caught and logged; a failure in one manager does not block the others.

### new_session and context_message persistence

In `PromptBase.new_session()`, `context_message` and `user_message` are appended as two separate user messages. Although `append_message()` calls `call_hooks_ctx_history()` to persist the latest message immediately, this only happens when the thread-local `KEY_SESSION_ID` is set.

1. `thread_local KEY_SESSION_ID` is intentionally used as a switch to control whether new messages are persisted to the session.
2. `llm_shell` sets `KEY_SESSION_ID`, but `agent_shell` does NOT set `KEY_SESSION_ID`. `agent_shell` intentionally does **not** set `thread_local KEY_SESSION_ID`, so `PromptBase.new_session()` → `append_message()` → `call_hooks_ctx_history()` is a no-op for persistence in the agent path.
3. `PromptBase.new_session()` is only for initializing in-memory `messages`; it is unrelated to persistent session storage. There is no "Session-ID timing gap". Persistent storage is handled later by workspace-layer hooks that already have `session_id`.

## MEMO: Database-Management Purity Rule

**Date:** 2026-07-05
**Files:**
- `/TopsailAI/src/topsailai/context/chat_history_manager/sql.py`
- `/TopsailAI/src/topsailai/context/session_manager/sql.py`

### Conclusion
Methods tightly related to database management must remain pure management layers and must not contain business logic.

### What this means
- `context/chat_history_manager/sql.py` and `context/session_manager/sql.py` are responsible only for storing, retrieving, and deleting records.
- They should not make agent-level decisions, interpret message semantics, trigger side effects such as LLM calls, or encode workflow rules.
- Business logic — including summarization, context pruning, task interpretation, and agent orchestration — belongs in higher layers such as `workspace/context/`, `ai_base/`, or dedicated manager wrappers.

### Examples of concerns to keep out
- Deciding whether a message should be archived or summarized.
- Interpreting `step_name` values to drive behavior.
- Calling hooks, tools, or LLMs.
- Enforcing application-level invariants that are not required for data integrity.

### Note for maintainers
- When adding a new method to `ChatHistorySQLAlchemy` or `SessionSQLAlchemy`, ask whether it is purely about data management. If it requires domain knowledge beyond the schema, move it to a higher-level module.
- Keep SQL managers thin: create, read, update, delete, list, and simple cleanup are acceptable; everything else should be layered above.


### Coding Conventions for Context Runtime

The context runtime classes (`ContextRuntimeData`, `ContextRuntimeAgent2LLM`, and their base `ContextRuntimeBase`) manage two message stores:

- `self.messages` — messages in the **User2Agent** layer (persisted session messages).
- `self.ai_agent.messages` — messages in the **Agent2LLM** layer (ephemeral ReAct context).

To keep persistence, summarization, and token accounting consistent, all mutations to these lists must go through the provided accessor/mutator methods.

#### Rule

> `TopsailAI/src/topsailai/workspace/context/ctx_runtime.py` 对 `self.messages` 的变更必须使用 `self.set_messages`、`self.append_message`、`self.reset_messages` 等方法，不可以直接操作 `self.messages = xxx`。

The same discipline applies to `self.ai_agent.messages` in `workspace/context/agent2llm.py`: prefer `self.ai_agent.messages += [...]` or slice-based reassignment only when the logic explicitly intends to replace the list, and always keep summarization/token hooks in mind.

#### Approved methods for `self.messages`

| Method | Purpose | Defined in |
|--------|---------|------------|
| `self.append_message(message)` | Append a single message dict. | `workspace/context/base.py` |
| `self.set_messages(value)` | Replace the entire list with a new list (clears and extends in-place). | `workspace/context/base.py` |
| `self.reset_messages()` | Reload messages from session storage via `ctx_manager`. | `workspace/context/base.py` |

#### Why this matters

1. **Single source of truth**: `set_messages()` clears the existing list and extends it in place, avoiding accidental aliasing of the internal list with an external object.
2. **Persistence parity**: `append_message()` and `reset_messages()` are used by `ContextRuntimeData.add_session_message()` and `summarize_messages_for_processed()` to keep the in-memory `self.messages` synchronized with the persisted session store.
3. **Token accounting**: After summarization, `ContextRuntimeAgent2LLM.summarize_messages_for_processing()` calls `self.ai_agent.llm_model.tokenStat.add_msgs(...)`; direct assignment can bypass this bookkeeping.
4. **Task-message preservation**: Summarization logic splits and re-merges task messages; using the controlled mutators ensures the preserved messages end up in the right order.

#### Practical examples

```python
# GOOD: append a message
self.append_message({"role": "user", "content": "hello"})

# GOOD: replace the whole list safely
self.set_messages(new_messages)

# GOOD: reload from session storage
self.reset_messages()

# BAD: direct assignment bypasses the controlled mutator
self.messages = new_messages
```

#### Agent2LLM layer notes

In `workspace/context/agent2llm.py`, `del_agent_messages()` and `summarize_messages_for_processing()` mutate `self.ai_agent.messages` directly because they operate on the ephemeral ReAct context and must preserve the work-memory prefix (`self.ai_agent.messages[:index]`). When modifying that layer, always preserve the prefix returned by `self.ai_agent.get_work_memory_first_position()` and update `tokenStat` afterward when tokens change materially.

---

## Summarize Trigger Logic

Both the **User2Agent** and **Agent2LLM** layers use a two-threshold strategy to decide when to summarize context. The entry points are `is_need_summarize_for_processed()` (User2Agent, in `workspace/context/ctx_runtime.py`) and `is_need_summarize_for_processing()` (Agent2LLM, in `workspace/context/agent2llm.py`).

### Summarization Implementation Location

| Layer | Trigger / Decision | Actual Summarization Logic |
|-------|-------------------|---------------------------|
| **User2Agent** | `is_need_summarize_for_processed()` in `workspace/context/ctx_runtime.py` | `summarize_messages_for_processed()` in `workspace/context/ctx_runtime.py` |
| **Agent2LLM** | `is_need_summarize_for_processing()` in `workspace/context/agent2llm.py` | `summarize_messages_for_processing()` in `workspace/context/agent2llm.py` |

Both implementations share the same final message structure:

```
new_messages = head_portion + [summary_answer] + [last_user_message]
```

- `head_portion` — messages from the start of the list up to and including the first `role=user, step_name=task` message.
- `summary_answer` — a single assistant message produced by `_summarize_messages()` (defined in `workspace/context/base.py`), which receives the current runtime messages as input.
- `last_user_message` — the final user message in the original list, preserved unchanged so the next turn still has a user prompt to respond to.

### Runtime Message Variables

The messages that are evaluated and summarized are the **runtime** message lists held by each context-runtime class:

| Layer | Class | Runtime Message Variable | Defined in |
|-------|-------|--------------------------|------------|
| **User2Agent** | `ContextRuntimeData` | `self.messages` | `workspace/context/ctx_runtime.py` |
| **Agent2LLM** | `ContextRuntimeAgent2LLM` | `self.ai_agent.messages` | `workspace/context/agent2llm.py` |

These variables contain the current in-memory conversation context. The summarization methods read from them, produce the `summary_answer`, and then rebuild the list as `head_portion + [summary_answer] + [last_user_message]`.

### Common Threshold Mechanism

Both methods first call `_get_quantity_threshold(env_key)` (defined in `workspace/context/base.py`) to obtain a randomized message-count threshold. Each layer uses its own environment variable, falling back to the legacy shared variable only when the layer-specific one is not configured:

1. Read the layer-specific quantity threshold (`TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD` for User2Agent, `TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD` for Agent2LLM) as an integer.
2. If the layer-specific value is unset, empty, `0`, or negative, fall back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`.
3. If the fallback value is also `0`, negative, or unset, quantity-based summarization is disabled.
4. Otherwise, combine the configured value with a small random prime (`13, 17, 19, 23`) and return the larger one.

This randomization avoids synchronized summarization spikes across multiple agents.

### User2Agent — `is_need_summarize_for_processed()`

- **Quantity check**: compares `len(self.messages)` (the persisted User2Agent session messages) against the randomized quantity threshold.
- **Token check**: reads `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` (default `0`, i.e. disabled). If set to a positive value, compares `self.ai_agent.llm_model.tokenStat.current_tokens` against it.
- **Trigger**: returns `True` if either the quantity threshold or the token threshold is exceeded.

### Agent2LLM — `is_need_summarize_for_processing()`

- **Quantity check**: builds an extended candidate list from fixed primes `[23, 27, 29, 31, 37, 41, 43, 47]`, appends the configured quantity threshold, and optionally appends `quantity_threshold * 2`. It then picks a random value from this list and ensures it is at least the configured threshold. Finally it compares `len(self.ai_agent.messages)` against this value.
- **Token check**: reads `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` (default `128000`). If positive, compares `self.ai_agent.llm_model.tokenStat.current_tokens` against it.
- **Trigger**: returns `True` if either the quantity threshold or the token threshold is exceeded.

### Key Differences

| Aspect | User2Agent (`is_need_summarize_for_processed`) | Agent2LLM (`is_need_summarize_for_processing`) |
|--------|-----------------------------------------------|-----------------------------------------------|
| Source messages | `self.messages` (persisted session) | `self.ai_agent.messages` (ephemeral ReAct context) |
| Quantity env var | `TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD` (falls back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`) | `TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD` (falls back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD`) |
| Token env var | `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` (default `0`, disabled) | `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` (default `128000`) |
| Randomization | Random prime vs configured value | Extended prime list, may include `2x` configured value |
| Summary persistence | Saves summary into session/memory and deletes old raw messages | Replaces agent messages with summary while preserving head offset, session messages, and last user message |

### Environment Variables

See `docs/Environment_Variables.md` and `env_template` for full details. The relevant variables are:

- `TOPSAILAI_USER2AGENT_MESSAGES_QUANTITY_THRESHOLD` — message-count threshold for User2Agent summarization. Falls back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD` when unset/empty/0/negative.
- `TOPSAILAI_AGENT2LLM_MESSAGES_QUANTITY_THRESHOLD` — message-count threshold for Agent2LLM summarization. Falls back to `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD` when unset/empty/0/negative.
- `TOPSAILAI_CONTEXT_MESSAGES_QUANTITY_THRESHOLD` — legacy shared message-count threshold used as a fallback by both layers.
- `TOPSAILAI_AGENT2LLM_TOKEN_SUMMARIZE_THRESHOLD` — token threshold for Agent2LLM summarization.
- `TOPSAILAI_USER2AGENT_TOKEN_SUMMARIZE_THRESHOLD` — token threshold for User2Agent summarization (disabled by default).
- `TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP` — number of head messages to retain after summarization.
- `TOPSAILAI_CTX_SUMMARY_KEEP_SESSION_MESSAGES` — whether Agent2LLM summary should keep User2Agent session messages.

Note: the context-history "slimming" thresholds (`CONTEXT_MESSAGES_SLIM_THRESHOLD_*`) are a separate mechanism handled by `PromptBase.call_hooks_ctx_history()` and archive oversized `action`/`observation` payloads without producing a summary.

### Why Agent2LLM Uses a Larger Quantity-Threshold Pool

The two conversation layers have very different message rates, so their quantity-threshold randomization is tuned separately:

- **User2Agent** is the human↔agent layer. It receives messages only when the human sends input, so the message count grows slowly.
- **Agent2LLM** is the agent↔LLM layer while the agent is actively working. A single human task can trigger many ReAct turns, tool calls, and observations, so the message count grows much faster.

Because one user2agent message can spawn many agent2llm messages, Agent2LLM uses a larger candidate pool (`[23, 27, 29, 31, 37, 41, 43, 47]` plus optional `quantity_threshold * 2`) and enforces `max(random_choice, quantity_threshold)`. This raises the effective ceiling for the busier layer and avoids summarizing the agent's working context too aggressively in the middle of task execution, while still guaranteeing the threshold never drops below the configured value.

## Adding Messages to a Session

There are two primary ways to add a message to a session.

### 1. CLI Script

**File:** `/TopsailAI/cli/topsailai_session_add_message.py`

A thin wrapper around `workspace.llm_shell.get_llm_chat()`.

| Item | Detail |
|------|--------|
| **Purpose** | Prepare an `LLMChat` instance for a given session with an initial user message. |
| **Entry point** | `python /TopsailAI/cli/topsailai_session_add_message.py -s <session_id> -m <message>` |
| **Key parameters** | `-s/--session_id` (required), `-m/--message` (required); `session_id` falls back to `env_tool.get_session_id()` if omitted. |
| **Side effects** | Loads existing session messages via `ctx_manager.get_messages_by_session()`; creates the session via `ctx_manager.create_session(session_id, task=message)` if it does not exist; appends the new message to the in-memory `PromptBase`. It does **not** call `LLMChat.chat()`, so no LLM request is made and no assistant reply is produced. Persistence of the new message depends on the configured chat-history managers and any hooks triggered later. |

### 2. Direct API

**File:** `/TopsailAI/src/topsailai/context/ctx_manager.py`

**Function:** `add_session_message(session_id: str, message: dict) -> bool`

| Item | Detail |
|------|--------|
| **Purpose** | Persist a raw message dictionary directly to all configured chat-history managers. |
| **Entry point** | `from topsailai.context import ctx_manager; ctx_manager.add_session_message(session_id, message)` |
| **Key parameters** | `session_id` — target session; `message` — message dict (e.g., `{"role": "user", "content": "..."}`). |
| **Side effects** | Reads `CONTEXT_HISTORY_MANAGERS` to obtain manager instances; calls `mgr.add_session_message(message, session_id=session_id)` for each. Returns `True` only if at least one manager is configured and the message is handed to it. Does **not** create the session, acquire locks, or trigger summarization hooks. |

### When to Use Which

- Use the **CLI script** when you want to bootstrap an `LLMChat` session with a user message without running a full agent loop.
- Use **`ctx_manager.add_session_message()`** when you need to append a pre-built message dict to session storage directly from code.

## Constants and Message Definitions

References:
- `ai_base/constants.py`

The `ai_base/constants.py` file centralizes common constants used across the agent framework, including message roles, `step_name` values, and message content dictionary keys.

### Message Roles

| Constant | Value | Description |
|----------|-------|-------------|
| `ROLE_USER` | `"user"` | Messages from the human user. |
| `ROLE_ASSISTANT` | `"assistant"` | Messages generated by the AI assistant. |
| `ROLE_SYSTEM` | `"system"` | System-level messages and prompts. |
| `ROLE_TOOL` | `"tool"` | Messages containing tool execution results. |

### Step Names

`step_name` values identify the type or purpose of a message content block in the agent's internal message flow.

| Constant | Value | Description |
|----------|-------|-------------|
| `STEP_NAME_TASK` | `"task"` | Represents a task or user request. |
| `STEP_NAME_ACTION` | `"action"` | Represents a tool/action invocation. |
| `STEP_NAME_THOUGHT` | `"thought"` | Represents the agent's reasoning or thought. |
| `STEP_NAME_INQUIRY` | `"inquiry"` | Represents an inquiry or question. |
| `STEP_NAME_FINAL` | `"final"` | Represents the final answer. |
| `STEP_NAME_OBSERVATION` | `"observation"` | Represents the result/observation from a tool or environment. |

### Message Content Keys

Message content is commonly represented as a dictionary using the following keys.

| Constant | Value | Description |
|----------|-------|-------------|
| `MSG_KEY_STEP_NAME` | `"step_name"` | Key for the step name field. |
| `MSG_KEY_RAW_TEXT` | `"raw_text"` | Key for the raw text payload. |
| `MSG_KEY_TOOL_CALL` | `"tool_call"` | Key for the tool call identifier/name. |
| `MSG_KEY_TOOL_ARGS` | `"tool_args"` | Key for the tool call arguments. |

### Other Constants

| Constant | Value | Description |
|----------|-------|-------------|
| `LLM_KEYWORD_MISTAKE` | `"LLM Mistake"` | Keyword prefix used in logs for LLM mistake events. |
| `LLM_KEYWORD_SERVICE` | `"LLM Service"` | Keyword prefix used in logs for LLM service events. |
| `DEFAULT_LLM_SLOW_CHAT_THRESHOLD` | `60` | Default threshold in seconds for detecting slow LLM chats. |
| `NON_SYSTEM_PROMPT_MESSAGE_INDEX` | `3` | Starting index for non-system messages when processing context history. |


## Known Pitfall: `_get_token_calculation_messages` Override in `ContextRuntimeData`

**File:** `workspace/context/ctx_runtime.py`
**Related:** `workspace/context/base.py` (`_summarize_runtime_messages`, `_get_current_tokens`)

### Problem

`ContextRuntimeData` previously overrode `_get_token_calculation_messages()` with:

```python
def _get_token_calculation_messages(self):
    return self.messages
```

This override unconditionally returned the **User2Agent** session messages (`self.messages`), bypassing the base-class logic that returns `self.ai_agent.messages` when an agent is present.

### Impact

When `_summarize_runtime_messages()` in `workspace/context/base.py` called `self._get_token_calculation_messages()` during **Agent2LLM** summarization, it received the wrong message source. The summarizer could end up consuming User2Agent session messages instead of the ephemeral Agent2LLM messages it was supposed to summarize.

### Fix

The override was removed from `ContextRuntimeData`. The base implementation now handles both layers correctly:

```python
def _get_token_calculation_messages(self):
    if self.ai_agent:
        return self.ai_agent.messages[:]
    return self.messages[:]
```

### Lesson

Do **not** override layer-aware accessors in subclasses unless the layer semantics genuinely change. `ContextRuntimeData` is the concrete runtime class used for both User2Agent and Agent2LLM operations; overriding a shared accessor here silently broke Agent2LLM token calculation and summarization.


## Context Runtime Design Convention

**Applies to:** `workspace/context/base.py`, `workspace/context/agent2llm.py`, `workspace/context/ctx_runtime.py`

### Class Hierarchy

```
ContextRuntimeBase
  └── ContextRuntimeAgent2LLM
        └── ContextRuntimeData
```

- `ContextRuntimeBase` defines the shared runtime state (`session_id`, `messages`, `ai_agent`) and common helpers.
- `ContextRuntimeAgent2LLM` adds behavior for the **Agent2LLM** layer (agent → LLM ReAct context).
- `ContextRuntimeData` extends the same instance to add **User2Agent** layer behavior (user → agent session messages).

Because `ContextRuntimeAgent2LLM` is the parent of `ContextRuntimeData`, both layers operate on the **same `ContextRuntime` instance**. `self.messages` (User2Agent session) and `self.ai_agent.messages` (Agent2LLM context) coexist on one object.

### Design Rule

1. **Common/shared methods must live in `ContextRuntimeBase`.**
   Examples: `append_message`, `set_messages`, `reset_messages`, `_summarize_messages`, `_get_quantity_threshold`, `_get_head_offset_to_keep_in_summary`.

2. **Layer-specific methods must use distinct names rather than overriding a base method with different semantics.**
   - Agent2LLM layer uses the `*_for_processing` suffix:
     - `summarize_messages_for_processing`
     - `is_need_summarize_for_processing`
     - `del_agent_messages`
   - User2Agent layer uses the `*_for_processed` suffix or session-oriented names:
     - `summarize_messages_for_processed`
     - `is_need_summarize_for_processed`
     - `del_session_messages`
     - `add_session_message`

3. **Do not override layer-aware accessors in subclasses.**
   A subclass such as `ContextRuntimeData` must not override a base method like `_get_token_calculation_messages()` to return a different message layer. Because the instance is shared, such an override silently changes behavior for both layers. If a layer genuinely needs a different accessor, introduce a new method with a layer-specific name instead.

### Why This Matters

Overriding a shared accessor in a subclass breaks polymorphic expectations: callers in the base class (e.g. `_summarize_runtime_messages` or `_get_current_tokens`) invoke the method expecting the layer-appropriate message source, but the override forces every caller to receive the same layer. Since `ContextRuntimeData` is the concrete runtime used by the agent shell, the override affected both User2Agent and Agent2LLM code paths.

### Practical Checklist

- Before adding a method to `ContextRuntimeAgent2LLM` or `ContextRuntimeData`, ask whether it is truly layer-specific.
- If it is layer-specific, give it a name that clearly identifies the layer (`*_for_processing` / `*_for_processed`).
- If it is shared, move it to `ContextRuntimeBase`.
- Avoid overriding methods defined in `ContextRuntimeBase`; prefer adding new, explicitly named methods.

## MEMO: `last_user_message` intentionally scans the User2Agent layer

**Date:** 2026-06-26
**File:** `/TopsailAI/src/topsailai/workspace/context/base.py` (`last_user_message` property)
**Discussion:** Review of context-runtime override/mutator pitfalls

### Conclusion
The `last_user_message` property intentionally scans `self.messages` (the **User2Agent** persisted session layer), even when it is used from the **Agent2LLM** summarization path.

### Rationale
- `self.messages` holds the real human-to-agent conversation.
- `self.ai_agent.messages` holds the ephemeral agent-to-LLM ReAct context, which contains internal `user` role messages such as tool observations and task injections.
- When summarizing the Agent2LLM context, the "last user message" that must be preserved is the most recent **real human input**, not an internal ReAct/tool message.
- Therefore, scanning `self.messages` is the correct design choice.

### Note for maintainers
Do not change `last_user_message` to scan `self.ai_agent.messages`. If a future use case genuinely needs the last user-like message inside the Agent2LLM layer, add a new layer-specific helper instead of modifying this property.

## MEMO: `_get_token_calculation_messages` returns `self.ai_agent.messages` by design

**Date:** 2026-06-26
**File:** `/TopsailAI/src/topsailai/workspace/context/base.py` (`_get_token_calculation_messages`)
**Discussion:** Review challenge from Human.Topsail

### Conclusion
`_get_token_calculation_messages()` intentionally returns `self.ai_agent.messages` whenever an agent is present, even when called from the User2Agent summarization path.

### Rationale
- `self.messages` (User2Agent persisted session) is loaded as the starting prefix of `self.ai_agent.messages` via `ContextRuntimeAIAgent.add_runtime_messages()`.
- Therefore `self.ai_agent.messages` already contains `self.messages`.
- `self.ai_agent.messages` represents the complete runtime context that the LLM actually sees, including both the human↔agent conversation and the agent's internal ReAct messages.
- Using `self.ai_agent.messages` for token calculation and runtime-mode summarization gives a consistent, complete view of the active context for both User2Agent and Agent2LLM layers.

### Note for maintainers
Do not change `_get_token_calculation_messages()` to return `self.messages` for User2Agent calls. If a future use case genuinely needs to count only the User2Agent session messages, add a new layer-specific helper instead of modifying this shared accessor.

## MEMO: Context Summarization Message Ordering Convention

**Date:** 2026-07-02
**Files:**
- `/TopsailAI/src/topsailai/workspace/context/base.py`
- `/TopsailAI/src/topsailai/workspace/context/ctx_runtime.py`
- `/TopsailAI/src/topsailai/workspace/context/agent2llm.py`

### Convention
After context summarization, the rebuilt message list must follow this order:

```
head_portion + head_offset + tail_offset + [summary_answer] + [last_user_message]
```

In plain terms: **preserve the original head and tail messages first, then add the summary answer, then the last user message**. Duplicates must be skipped.

### Terminology
- `head_portion` — messages from the beginning up to and including the first `role=user, step_name=task` message.
- `head_offset` — the first `head_offset_to_keep` messages kept verbatim (read from `TOPSAILAI_CONTEXT_MESSAGES_HEAD_OFFSET_TO_KEEP`).
- `tail_offset` — the last `tail_offset_to_keep` messages kept verbatim (read from `TOPSAILAI_CONTEXT_MESSAGES_TAIL_OFFSET_TO_KEEP`).
- `summary_answer` — exactly one assistant message produced by the LLM summarizer.
- `last_user_message` — exactly one final user message kept at the tail.

> **Note:** `head_portion` and `head_offset` are often spoken of together as "head"; the same applies to `tail_portion` and `tail_offset` as "tail". The principle is simply `[head + tail] + [summary] + [last_user_message]`.

### No Duplicates
When merging preserved head/tail messages with the summary and last user message, always check `if msg not in new_messages` before appending. This prevents the same message from appearing twice when, for example, the last user message is also part of the head portion or tail offset.

### Applies To
Both summarization paths must follow this convention:
- **User2Agent** — `ContextRuntimeData.summarize_messages_for_processed()` in `workspace/context/ctx_runtime.py`.
- **Agent2LLM** — `ContextRuntimeAgent2LLM.summarize_messages_for_processing()` in `workspace/context/agent2llm.py`.

### Note for maintainers
When modifying summarization logic, keep this ordering invariant intact. If a future use case needs a different ordering, add a new method or configuration path rather than silently changing the shared convention.

## MEMO: Agent2LLM Runtime Message Injection

**Date:** 2026-07-03
**Files:**
- `/TopsailAI/src/topsailai/ai_base/agent2llm_message_source.py`
- `/TopsailAI/src/topsailai/ai_base/agent_base.py`
- `/TopsailAI/src/topsailai/workspace/agent/runtime_message_sources/file.py`
- `/TopsailAI/src/topsailai/workspace/agent/hooks/pre_run_agent2llm_source.py`

### Conclusion
The agent can inject runtime messages into the Agent2LLM context before each LLM call. The mechanism uses an abstract `Agent2LLMMessageSource` registered in thread-local storage by a pre-run hook and consumed by `AgentRun._run()`.

### Components

1. **Abstract interface** — `ai_base/agent2llm_message_source.py` defines `Agent2LLMMessageSource` with `consume_messages()`. It also provides thread-local helpers and `apply_agent2llm_message_source(agent)`, which appends consumed messages at the tail of `agent.messages` as `user` role `observation` content dicts.
2. **Source implementations** — `workspace/agent/runtime_message_sources/` contains concrete sources. The `file` source reads JSONL from a configured file, parses valid lines, clears the file only after successful parsing, and skips invalid lines with warnings.
3. **Pre-run hook** — `workspace/agent/hooks/pre_run_agent2llm_source.py` creates the configured source and registers it in thread-local storage during `AgentChat.run()`.
4. **Trigger point** — `AgentRun._run()` calls `self._inject_runtime_messages()` at the top of each ReAct loop iteration, immediately before `self.llm_model.chat(...)`.

### Environment Variables

- `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_ENABLED` — master switch (`0`/`1`). **Default is `1` (enabled).**
- `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_SOURCE` — source type (`file` by default).
- `TOPSAILAI_AGENT2LLM_INJECT_MESSAGE_FILE` — JSONL file path for the `file` source. When empty, defaults to `{FOLDER_WORKSPACE_TASK}/{session_id}.{pid}.session.agent2llm_inject_messages.jsonl`, where `session_id` falls back to `env_tool.get_session_id()` or `"topsailai"`.

### JSONL Message Format

The `file` source reads one message per line. Each line must be a JSON object with at least a `role` and a `content` field. Two content forms are supported:

1. **Simple format** — plain text content:
   ```json
   {"role": "user", "content": "plain text"}
   ```
   This is wrapped internally as a structured `observation` message before injection.

2. **Structured format** — already formatted as an internal content dict:
   ```json
   {"role": "user", "content": {"step_name": "observation", "raw_text": "..."}}
   ```
   Lines that already contain `step_name` and `raw_text` are passed through unchanged.

3. **Optional `ts` field** — creation timestamp for representation/logging:
   ```json
   {"role": "user", "content": "...", "ts": "2026-07-04T12:34:56.789012+00:00"}
   ```
   The `ts` field is produced automatically when messages are written via `write_message()` / `produce_message()`. It is **stripped before injection** into the Agent2LLM context and never reaches `agent.add_user_message`.

### Key Design Points

- `ai_base` does not import any `workspace/` modules; it only reads the source from thread-local storage.
- The default file path follows the session-scoped pipe/stdout filename convention: `{session_id}.{pid}.session.agent2llm_inject_messages.jsonl` under `FOLDER_WORKSPACE_TASK`, so concurrent processes do not collide.
- The `ts` field is representation-only and is removed by `apply_agent2llm_message_source()` before the message is processed.
- The file source registers an `atexit` handler that deletes the inject file when the process exits, preventing stale JSONL files from accumulating.
### Note for maintainers

When adding a new source type, implement `Agent2LLMMessageSource`, register it in `workspace/agent/runtime_message_sources/__init__.py`, and update `pre_run_agent2llm_source.py` if the source requires additional configuration. Do not change `ai_base/agent_base.py` unless the trigger semantics change.

## MEMO: Strict Prompt Construction Order Requirement

**Date:** 2026-06-27
**Files Changed:**
- `src/topsailai/prompt_hub/prompt_tool.py`
- `src/topsailai/tools/base/common.py`
- `src/topsailai/tools/story_memory_tool.py`

### Conclusion
Prompt construction has a strict ordering requirement: tool names, module names, prompt keys, and memory titles must be sorted into a deterministic, lexicographical order before the final prompt is assembled. The change enforces this by replacing set/dict iteration with `sorted()` and by using `OrderedDict` for tool documentation.

### What Changed

1. **`prompt_hub/prompt_tool.py`**
   - `get_prompt_by_tools()` now sorts `modules` and `prompt_keys` before iterating.
   - `generate_prompt_by_tools()` now sorts `tools_name` before generating the tool prompt.

2. **`tools/base/common.py`**
   - `tools_doc` is now an `OrderedDict` instead of a plain `dict`.
   - Tool names from both `tools_name` and `tools_map` are sorted before being added to `tools_doc`.

3. **`tools/story_memory_tool.py`**
   - Memories are now read in sorted title order and rendered as Markdown sections.

### Why It Matters

- **Determinism:** Without explicit sorting, set/dict iteration order can vary across Python processes or versions. The same tool set could produce prompts in different orders, leading to inconsistent LLM behavior and cache misses.
- **Reproducibility:** A fixed order makes unit tests, prompt snapshots, and debugging predictable.
- **Stability:** `OrderedDict` guarantees that once tool docs are inserted in sorted order, downstream consumers iterate over them in that exact order.
- **Clarity:** Sorting gives the LLM a consistent visual structure (module prompts first, then individual tool prompts), which helps the model reliably locate tool documentation.

### Note for maintainers

When adding new prompt-assembly logic or modifying tool-prompt generation, always ensure iteration over tools, modules, prompt keys, or memory titles is deterministic. Prefer `sorted()` for collections and `OrderedDict` when order must be preserved through multiple processing stages. Do not rely on the implicit ordering of plain `dict` or `set` objects for prompt construction.

## MEMO: Context Environment Information in System Prompt

**Date:** 2026-06-27
**File:** `/TopsailAI/src/topsailai/context/prompt_env.py`

### Conclusion
Context environment information can be added to the system prompt through `/TopsailAI/src/topsailai/context/prompt_env.py`.

### What it does
- `generate_prompt_for_env()` builds an `# Environment` block that includes:
  - `CurrentDate` — current date in ISO 8601 format.
  - `CurrentSystem` — OS information (`uname`, `/etc/issue`).
  - `CurrentProject` — `TOPSAILAI_PROJECT_WORKSPACE` and `TOPSAILAI_PWD`.
  - Optional custom content from `ENV_PROMPT` (file path or raw text).

### Relevant environment variables
See `docs/Environment_Variables.md` for full details:
- `ENV_PROMPT` — custom environment prompt (file path or raw text).
- `TOPSAILAI_PROJECT_WORKSPACE` / `TOPSAILAI_PROJECT_FOLDER` — project folder injected into the prompt.
- `TOPSAILAI_PWD` — working directory at process startup injected into the prompt.
- `SYSTEM_PROMPT` / `SYSTEM_PROMPT_EXTRA_FILES` — general system-prompt extension mechanisms that may consume or coexist with the environment block.

### Note for maintainers
When modifying how environment context is injected into the system prompt, keep `prompt_env.py` in sync with the variables documented in `docs/Environment_Variables.md`. Any new environment fields added here should also be documented there.

## MEMO: `/ctx.btw` Instruction

**Date:** 2026-07-04
**File:** `/TopsailAI/src/topsailai/workspace/context/instruction.py`

### Conclusion
`/ctx.btw` injects a "by the way" message into the Agent2LLM ephemeral context at runtime.

### Usage
```
/ctx.btw <word> [<word> ...]
```
- Positional arguments are joined with a single space to form the message content.
- The role is always `user`; no `role` argument is accepted.

### Implementation
- Method: `ctx_btw(self, *args)`.
- Appended message format:
  ```python
  {"role": "user", "content": '{"step_name": "observation", "raw_text": "<assembled_content>"}'}
  ```
  The `content` field is a JSON string produced by `json.dumps(observation_content)`, where `observation_content` contains `step_name` and `raw_text` keys. This keeps the injected observation consistent with other serialized message payloads.
- Uses constants `STEP_NAME_OBSERVATION`, `MSG_KEY_STEP_NAME`, `MSG_KEY_RAW_TEXT` from `ai_base/constants.py`.
- Appended via `self.ai_agent.messages += [...]`; direct assignment is avoided.

### Note for maintainers
When adding similar runtime-injection instructions, keep message construction as a plain dict, serialize the content to a JSON string, and append through the context-runtime mutator convention.

## MEMO: SKILL.md Configuration Items

**Date:** 2026-07-03
**File:** `/TopsailAI/src/topsailai/skill_hub/skill_tool.py`

`SKILL.md` uses YAML frontmatter between `---` delimiters. The following fields are recognized by the skill hub:

### Core Fields

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Skill identifier used in the skill registry prompt. |
| `description` | string | Short summary shown in the skill registry prompt. |

### Special Configuration Items

| Field | Type | Description |
|-------|------|-------------|
| `preload_docs` | list[string] | Documents or directories to load automatically when `overview_skill` is called. Each entry is a relative path inside the skill folder. If it points to a directory, all `.md` files are collected recursively and sorted. |
| `flag_overview` | int/bool | When set to a non-empty truthy value, the skill registry prompt includes the full overview content for this skill (instead of only the description). Also respects `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS`. |

### Example

```yaml
---
name: my-skill
description: Demonstrates skill configuration items.
preload_docs:
  - references/
  - docs/guide.md
flag_overview: 1
---
```

### Notes

- `preload_docs` is processed by `_expand_preload_doc_entry()` and loaded in `overview_skill_native()`.
- `flag_overview` is parsed in `parse_skill_folder()` and checked in `SkillInfo.markdown`.
- Any additional frontmatter fields are stored in `skill_info.all` but are not interpreted by the built-in skill hub unless custom code reads them.


## MEMO: Skill Hub Environment Variables

**Date:** 2026-07-03
**Files:** `/TopsailAI/src/topsailai/skill_hub/skill_tool.py`, `/TopsailAI/src/topsailai/skill_hub/skill_repo.py`, `/TopsailAI/src/topsailai/skill_hub/skill_hook.py`

The skill hub is controlled by several environment variables. They are documented in `docs/Environment_Variables.md` and used in the skill hub implementation:

| Variable | Default | Description |
|----------|---------|-------------|
| `TOPSAILAI_PLUGIN_SKILLS` | `""` | Plugin skill directories separated by `;`. Supports searching folders up to `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH`. |
| `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH` | `3` | Maximum recursion depth when searching for plugin skills. Also used by `skill_repo.list_skills()` when scanning `FOLDER_SKILL`. |
| `TOPSAILAI_DISABLED_SKILLS` | `""` | Skills to disable. |
| `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS` | `""` | Skills whose overview should be loaded into the prompt. Can be a `;`-separated list of skill names or `*` for all. |
| `TOPSAILAI_SESSION_LOCK_ON_SKILLS` | `""` | Lock session before calling these skills. |
| `TOPSAILAI_SESSION_REFRESH_ON_SKILLS` | `""` | Refresh session after calling these skills. |
| `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP` | `"ai-community=86400"` | Skill call timeout map. Format: `skill_folder=timeout` separated by `;`. |
| `TOPSAILAI_HOOK_MODULE_SKILLS` | `""` | Skill hook module directory paths separated by `;`. |

### Notes

- `TOPSAILAI_PLUGIN_SKILLS` is read by `skill_tool.load_skills()` to discover additional skill folders outside `FOLDER_SKILL`.
- `TOPSAILAI_SEARCH_SKILLS_MAX_DEPTH` controls how many directory levels are scanned when looking for `SKILL.md` / `skill.md` files.
- `TOPSAILAI_LOAD_OVERVIEW_INTO_PROMPT_SKILLS` interacts with the per-skill `flag_overview` frontmatter field: a skill is loaded into the prompt if either its own `flag_overview` is truthy or its name matches this environment variable.
- `TOPSAILAI_CALL_SKILL_TIMEOUT_MAP` lets callers override the default timeout for individual skills when invoking them through `skill_tool.call_skill()`.
- `TOPSAILAI_SESSION_LOCK_ON_SKILLS` and `TOPSAILAI_SESSION_REFRESH_ON_SKILLS` are used by `skill_hook.py` to coordinate session state around skill calls.
- `TOPSAILAI_HOOK_MODULE_SKILLS` registers external hook modules that can intercept skill lifecycle events.

## MEMO: LLM-Related Logging

**Date:** 2026-07-04
**File:** `/TopsailAI/src/topsailai/ai_base/constants.py`

### Conclusion
Logs emitted by LLM-related functionality should be prefixed with the keywords defined in `ai_base/constants.py` so that LLM mistakes and service issues can be quickly identified and filtered. Prefer the `print_*` helpers in `utils/print_tool.py` for these logs because they write to both the project logger and the console consistently.

### Defined Keywords

```python
# LLM mistake keyword
LLM_KEYWORD_MISTAKE = "LLM Mistake"
# LLM service keyword
LLM_KEYWORD_SERVICE = "LLM Service"
```

| Constant | Value | Usage |
|----------|-------|-------|
| `LLM_KEYWORD_MISTAKE` | `"LLM Mistake"` | Prefix logs that record incorrect, malformed, or otherwise problematic LLM outputs (e.g., bad tool-call formats, missing arguments, unexpected final answers). |
| `LLM_KEYWORD_SERVICE` | `"LLM Service"` | Prefix logs that record LLM service-level events (e.g., API errors, retries, timeouts, first-byte latency warnings). |

### Preferred Print Helpers

Use the helpers in `utils/print_tool.py` for LLM-related diagnostics:

| Helper | Level | Behavior |
|--------|-------|----------|
| `print_info(msg)` | info | Logs and prints an info message. |
| `print_warning(msg)` | warning | Logs and prints a warning message. |
| `print_error(msg, exception=False)` | error | Logs and prints an error message; pass `exception=True` to include the current exception traceback. |
| `print_critical(msg)` | critical | Logs and prints a critical message. |

### Example

```python
from topsailai.ai_base.constants import LLM_KEYWORD_MISTAKE, LLM_KEYWORD_SERVICE
from topsailai.utils.print_tool import print_warning, print_error

print_warning(f"{LLM_KEYWORD_SERVICE}: first byte timeout after {timeout}s")
print_error(f"{LLM_KEYWORD_MISTAKE}: tool call missing required arguments")
```

### Note for maintainers
When adding new logging around LLM behavior, prefer these constants over ad-hoc strings and use `utils/print_tool.print_*` over raw `logger.*` calls. Keeping the keyword set small and the output path consistent makes log aggregation, alerting, and interactive debugging easier.
