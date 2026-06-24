---
programming_language: python
---

# TopsailAI Agent

AI-Agent Core, Agent Workers

## Logical Components

1. Common Utils
2. Agent Core       -> Agent Enginering Framework
3. Agent Workers    -> Worker Entry

Folder details can be got from `test.md`

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

---

## Logs that need attention

How to retrieve log:
```
LogFile: `{TOPSAILAI_HOME}/log/chat.log`, TOPSAILAI_HOME is environment variable, default is `/topsailai`
Use command `topsailai_check_log` to review log content.
Use command `grep -C 10 "{time}" {LogFile}` to print NUM lines of output context for log
```

H3 title format: `LOG_ATTENTION: {content}` -> DONOT CHANGE THE FORMAT, REFER TO BIN FILE `topsailai_check_log`!

### LOG_ATTENTION: "[0-9] CRITICAL -"

Some critical logs

### LOG_ATTENTION: "[0-9]\- LLM Mistake: give final due to duplicate to"

- LLM Lazy execution
- LLM Make mistake in the final

### LOG_ATTENTION: "[0-9]\- LLM Mistake: invalid json string"

LLM output unexpected content

### LOG_ATTENTION: "[0-9]\- LLM Service:"

LLM service errors

### LOG_ATTENTION: '"raw_text": "missing tool_call"'

- LLM make mistake
- MAX_TOKENS is too small

### LOG_ATTENTION: "[0-9]\- Heavy Task Trigger"

Task execution time is too long
