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
