---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# TopsailAI

TopsailAI is an interactive AI-agent runtime. It provides a command-line interface to watch sessions, send messages, launch agents, and manage workspace tasks, together with a layered engine that drives ReAct-style agent execution.

## Reading the Documentation

The `topsailai` command-line tool can read its own documentation. Use it to explore usage, design notes, environment variables, and known pitfalls.

```bash
# Show help and available documentation commands
topsailai -h

# List all available documents
topsailai --list-docs

# Read a specific document
topsailai --read-doc usage/topsailai.md
topsailai --read-doc memo/MEMO.AgentCore.md
topsailai --read-doc usage/Environment_Variables.md
```

Key document categories:

| Category | Documents |
|----------|-----------|
| CLI usage | `usage/README.md`, `usage/topsailai.md`, `usage/topsailai_*.md` |
| Architecture | `memo/MEMO.md`, `memo/MEMO.AgentCore.md`, `memo/MEMO.AgentWorkers.md`, `memo/MEMO.CommonUtils.md` |
| Configuration | `usage/Environment_Variables.md`, `env_template` |

## Architecture Overview

TopsailAI is organized into three logical layers.

### Common Utils

Cross-cutting infrastructure used by all other layers.

- `logger/` — Unified logging with rotating file handlers, chat-chain vs. module loggers, and identifier fields such as `agent_name` and `session_id`.
- `utils/` — Environment-variable reader, thread-local helpers, instruction/hook framework, and general utilities.
- `human/` — Human-related definitions such as names and identity identifiers.

### Agent Core

The LLM/agent engineering framework.

- `ai_base/` — Agent and LLM base classes, ReAct step loop, tool execution, and prompt construction.
- `prompt_hub/` — Prompt management and external prompt sources.
- `skill_hub/` — Skill discovery, loading, and invocation.
- `tools/` — Tools available to agents.
- `context/` — Session message storage, context runtime, token accounting, and summarization.

### Agent Workers

User-facing worker entry points.

- `workspace/` — Agent shell, LLM shell, input/output tools, print tools, and session lifecycle.
- `ai_team/` — Multi-agent team workflow support.
- `cli/` — Command-line scripts dispatched through `bin/topsailai`.

## Main CLI: `topsailai`

`topsailai` is the primary interactive task watcher and session manager. It scans `{TOPSAILAI_HOME}/workspace/task/` for session stdout/stderr files and lets you watch logs, send messages, and switch scopes.

### Scopes

- `[workspace]` — Default scope. Lists discovered `.stdout`/`.stderr` log files.
- `[project]` — Lists recent sessions that recorded a project workspace.
- `[session:<id>]` — Focused scope for one session.
- `[runtime:<id>]` — Active while streaming a log file.

### Common Commands

| Command | Scope | Description |
|---------|-------|-------------|
| `<number>` | workspace/project | Watch the selected log file or enter the selected session. |
| `/refresh` | workspace/project | Re-scan the task directory. |
| `/send <number> [message]` | workspace | Send a message to a running session. |
| `/send [message]` | session/runtime | Send a message through the session input pipe. |
| `/ctx.btw [message]` | runtime | Inject a by-the-way message into the Agent2LLM context. |
| `/ctx.add_msg [message]` | runtime | Add a persistent message to the User2Agent context. |
| `/agent [<folder>]` | workspace/project | Launch an agent. |
| `/resume <number>` | project | Resume an idle session. |
| `/clean [<number>...]` | workspace | Delete idle stdout files or specific entries. |
| `cd project` | workspace | Switch to project scope. |
| `q`, `quit`, `exit` | any | Leave the current scope or quit. |

Run `topsailai` and use `/help` inside any scope to see the full command list.

## Core Design Mechanisms

### Thread-Local Agent Object

During agent execution the current `AgentBase` instance is stored in thread-local storage. Tools can retrieve it via `topsailai.utils.thread_local_tool.get_agent_object()` to inspect messages, token statistics, or the LLM model without explicit parameter passing.

### Lazy Import for `openai`

The `openai` package has a long import time. Imports involving `openai` or thin wrappers around it are allowed to be deferred until first use, typically via local imports inside functions or methods.

### Session Input Pipe

When `TOPSAILAI_INPUT_PIPE_ENABLED=1`, a running session reads user input from a named pipe instead of `stdin`. The pipe path follows the stdout filename convention:

```
{TOPSAILAI_HOME}/workspace/task/{session_id}.{pid}.session.pipe
```

Messages sent through the pipe must end with a standalone `EOF` line. The CLI `/send` command formats payloads correctly.

### Session Stdout and Pipe Filename Convention

Both the stdout tee file and the input pipe include the process ID to avoid collisions between concurrent processes, and the session ID when one is available:

| Resource | No session ID | With session ID |
|----------|---------------|-----------------|
| Stdout tee | `topsailai.{pid}.session.stdout` | `{session_id}.{pid}.session.stdout` |
| Input pipe | `topsailai.{pid}.session.pipe` | `{session_id}.{pid}.session.pipe` |

### Tool Execution Entry Point

The immediate entry point for executing a single tool call is `exec_tool_func(tool_func, args, tool_name)` in `ai_base/agent_types/tool.py`. It handles invocation, exception catching, result truncation, and tool-call statistics.

### Context Archiving and Summarization

To keep the active context slim, the system uses two complementary mechanisms:

1. **Context archiving** — Large `action`/`observation` payloads are stored by `msg_id` in persistent storage and replaced in the active message list with lightweight `archive` placeholders.
2. **Context summarization** — When message count or token thresholds are exceeded, older messages are summarized into a single assistant message. Separate thresholds exist for the User2Agent layer and the Agent2LLM layer.

### Agent-Runtime Input Injection

Interactive input is injected into `ai_base` through a thread-local function rather than by importing workspace modules from lower layers. `ai_base` code calls `get_agent_runtime_input()` and falls back to the builtin `input()` when no hook has registered an input function.

## Configuration

Most behavior is controlled through environment variables. See the full reference:

```bash
topsailai --read-doc usage/Environment_Variables.md
```

Commonly used variables include:

| Variable | Purpose |
|----------|---------|
| `TOPSAILAI_HOME` | Agent workspace folder for logs, locks, tasks, and memory. |
| `TOPSAILAI_PROJECT_WORKSPACE` | Project folder the agent is allowed to read and write. |
| `OPENAI_MODEL` / `OPENAI_API_KEY` / `OPENAI_API_BASE` | LLM endpoint configuration. |
| `TOPSAILAI_INPUT_PIPE_ENABLED` | Enable pipe-based input for running sessions. |
| `TOPSAILAI_LOG_LEVEL` | Override the default log level. |

## Entry Points

| Path | Purpose |
|------|---------|
| `bin/topsailai` | Main CLI dispatcher. |
| `cli/topsailai.py` | Interactive task watcher implementation. |
| `workspace/agent_shell.py` | Agent worker shell. |
| `workspace/llm_shell.py` | LLM worker shell. |
| `ai_base/agent_base.py` | Core agent execution framework. |
