# Unified Worker Entry

This workspace package is the unified entry point for agent workers.

- `agent_shell.py` : Factory for creating `AgentChat` instances
- `llm_shell.py`   : Direct LLM chat interface (bypasses agent framework)

## Agent-WorkSpace & Agent-WorkFolder

1. `TOPSAILAI_HOME` — The Agent workspace. See `folder_constants.py`. Contains `log`, `lock`, `task`, `story_memory`, etc.
2. `TOPSAILAI_WORK_FOLDER` — The working directory of the Agent process. Contains `.env`, `db`, etc.

---

## Two-Layer Session Model

The system separates conversation into two distinct layers:

| Layer | Direction | Saved | Description |
|-------|-----------|-------|-------------|
| **User2Agent** | User → AI Agent | ✅ Yes | User-facing conversation with the abstract AI agent. Messages persist in session storage via `ctx_manager`. |
| **Agent2LLM** | Agent → LLM | ❌ No | Internal task execution between agent and LLM. Ephemeral — not persisted. Used for ReAct reasoning, tool calls, and single-turn processing. |

### Message Flow

```
User Input
    ↓
[input_tool] ──→ [hook_instruction] intercepts `/` commands
    ↓
[AgentChat.run] ──→ User2Agent: ctx_runtime_data.messages (persisted)
    ↓
[hook_after_init_prompt] loads session messages → ai_agent.messages
    ↓
[ai_agent.run] ──→ Agent2LLM: ai_agent.messages (ephemeral, ReAct loop)
    ↓
[hook_after_new_session] saves final answer → User2Agent session
    ↓
[hook_summarize_messages] compresses context when threshold exceeded
```

---

## Core Modules

### Input & Hook System

#### `input_tool.py`
Interactive input utilities with hook integration.

- **Input Modes**: `input_one_line()`, `input_multi_line()` — single/multi-line user input
- **Hook Interception**: `hook_message()` routes `/` commands through `HookInstruction`; handles `exit`/`quit`
- **Message Source**: `get_message()` reads from CLI args, stdin, files, or interactive prompt
- **History**: readline history persisted to `TOPSAILAI_HOME/.input_history`

#### `hook_instruction.py`
`/` command hook registry and execution.

- **Trigger**: Messages starting with `/` are intercepted as hook commands
- **Hook Management**: `HookInstruction` — register (`add_hook`), delete (`del_hook`), check (`exist_hook`), execute (`call_hook`)
- **Plugin Integration**: Auto-loads hooks from `INSTRUCTIONS` registry on initialization
- **Help System**: Built-in `/help` lists all registered commands

### Agent Shell & Chat Loop

#### `agent_shell.py`
Factory for creating fully configured `AgentChat` instances.

- `get_ai_agent()` — creates `AgentRun` (ReAct agent) with tools, prompts, and configuration
- `get_agent_chat()` — assembles complete chat session:
  - Initializes `ContextRuntimeData`, `ContextRuntimeAIAgent`, `ContextRuntimeInstructions`
  - Creates `HookInstruction` and loads plugin instructions
  - Sets up session, reads initial message, creates `AgentChat`

#### `agent/agent_shell_base.py`
`AgentChat.run()` — the main conversation loop.

- Receives user input (via `input_tool`)
- Calls `ai_agent.run()` for task execution
- Saves assistant responses to **User2Agent** session
- Handles task mode (`task_tool`), session locking (`lock_tool`), tee output
- Supports `only_save_final` mode (saves only final answer, not intermediate steps)

#### `agent/agent_chat_base.py`
`AgentChatBase` — agent controller with hook system.

- **Hooks**:
  - `hooks_pre_run` — executed before each run
  - `hooks_for_final_answer` — executed after final answer (e.g., save summary to session)
  - `hook_after_init_prompt` — loads **User2Agent** session messages into **Agent2LLM**
  - `hook_after_new_session` — saves agent's last message to **User2Agent** session
  - `hook_summarize_messages` — compresses **Agent2LLM** messages when threshold exceeded; detects heavy tasks
- **Heavy Task Detection**: Triggers alert when continuous summarization exceeds threshold

### Context Runtime (Two-Layer Message Management)

#### `context/ctx_runtime.py` — `ContextRuntimeData`
Manages **User2Agent** layer messages.

- `add_session_message(role, message)` — adds message to session + persists via `ctx_manager`
- `del_session_messages(indexes)` — deletes messages by index
- `summarize_messages_for_processed()` — summarizes User2Agent history, persists summary
- `is_need_summarize_for_processed()` — checks if message count exceeds threshold

#### `context/agent2llm.py` — `ContextRuntimeAgent2LLM`
Manages **Agent2LLM** layer messages.

- `del_agent_messages(indexes)` — deletes agent messages by index
- `summarize_messages_for_processing()` — summarizes Agent2LLM context, keeps head offset + session messages + last user message
- `is_need_summarize_for_processing()` — checks if agent messages exceed threshold

#### `context/agent.py` — `ContextRuntimeAIAgent`
Bridge between the two layers.

- `add_session_message()` — saves agent's latest message to **User2Agent** session
- `add_runtime_messages()` — copies **User2Agent** session messages into **Agent2LLM**

#### `context/base.py` — `ContextRuntimeBase`
Base class with shared summarization infrastructure.

- `_summarize_messages()` — uses `llm_shell.get_llm_chat()` to generate summaries
- `_get_quantity_threshold()` — randomizes threshold to avoid synchronized summarization
- `_get_summary_prompt()` — loads summary prompts (task vs memory mode)

#### `context/instruction.py` — `ContextRuntimeInstructions`
Human-facing `/ctx.*` commands.

- `/ctx.clear` — clear session messages
- `/ctx.history` — display message history
- `/ctx.del_msg` — delete message by index
- `/ctx.summarize` — trigger summarization
- `/ctx.story` — save history as story memory

#### `context/agent_tool.py` — `ContextRuntimeAgentTools`
Agent-callable tools for pruning messages in both layers.

- `tool_delete_messages_for_processed()` — prune **User2Agent** messages
- `tool_delete_messages_for_processing()` — prune **Agent2LLM** messages

### LLM Shell

#### `llm_shell.py`
Direct LLM chat interface, bypassing the agent framework.

- `LLMChat` — manages `PromptBase` + `LLMModel` conversation
- `get_llm_chat()` — factory with session support, reads messages from `ctx_manager`
- Used internally by `_summarize_messages()` for context compression

### Plugin Instructions

#### `plugin_instruction/`
Modular `/` commands registered via `INSTRUCTIONS` dict.

| Module | Commands | Purpose |
|--------|----------|---------|
| `env.py` | `/set`, `/get` | Environment variable management |
| `agent.py` | `/system_prompt`, `/tool_prompt`, `/tools`, `/set_llm`, `/llm` | Agent introspection & LLM switching |
| `skill.py` | `/show`, `/load`, `/unload`, `/hooks` | Skill hub management |
| `skill_repo.py` | `/list`, `/install`, `/uninstall` | Skill repository operations |
| `stat.py` | `/tool_call`, `/tool_call_errors`, `/tool_call_reset`, `/tool_call_log` | Tool call statistics |

Loaded by `plugin_instruction/base/init.py` via `get_function_map()`; supports external plugins via `TOPSAILAI_PLUGIN_INSTRUCTIONS`.

### Supporting Utilities

| Module | Purpose |
|--------|---------|
| `folder_constants.py` | Centralized path constants (`TOPSAILAI_HOME`, workspace, memory, lock, log) |
| `lock_tool.py` | Session file locking (`ctxm_try_session_lock`) and general file locks |
| `print_tool.py` | `TeeOutput` (screen + file), `ContentDots` (stream indicator), message formatting |
| `task/task_tool.py` | Task lifecycle management for one-shot executions |
| `agent/hooks/` | Pre-run and post-final-answer hook discovery and execution |

### Thread-Local Agent Object

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

This mechanism is used internally during the **Agent2LLM** execution phase, where the agent framework sets the active agent object before invoking tools.

---

## Module Call Graph

```
agent_shell.get_agent_chat()
    ├── ContextRuntimeData ──→ ctx_manager (session persistence)
    ├── ContextRuntimeAIAgent
    ├── ContextRuntimeInstructions ──→ /ctx.* commands
    ├── HookInstruction ──→ plugin_instruction.INSTRUCTIONS
    ├── get_ai_agent() ──→ AgentRun (ReAct)
    └── AgentChat
            └── .run()
                    ├── input_tool.get_message() ──→ User2Agent input
                    ├── ai_agent.run() ──→ Agent2LLM execution
                    ├── ctx_runtime_data.add_session_message() ──→ persist to User2Agent
                    └── hook_for_final_answer()
```
