---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_agent_chats

Multi-turn interactive chat with a single AI agent.

## Purpose

Runs a continuous conversational session with one AI agent. Unlike
`topsailai_agent_chat` (single turn) or `topsailai_agent_plan_tasks`
(sub-agent orchestration), this tool keeps talking until the user exits. It is
a single-agent workflow: the `agent_tool` is disabled to prevent recursive
agent calls, and no `subagent_tool` is enabled.

## Invocation

```bash
./topsailai_agent_chats.py [message ...]
```

Because the script is registered in `../bin/` as `topsailai_agent_chats`, you
can also run it as:

```bash
topsailai_agent_chats [message ...]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `message` | Optional initial chat content. |

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Configuration

Configured through environment variables:

- `TOPSAILAI_SESSION_ID` — session identifier for maintaining conversation
  history. Takes precedence over `SESSION_ID`.
- `SESSION_ID` — session identifier used when `TOPSAILAI_SESSION_ID` is not set.
  When neither variable carries a non-blank value, a session identifier is
  generated automatically (see below).
- `SYSTEM_PROMPT` — a file path or inline content for the system prompt.
- `CHAT_MULTI_LINE` — enables multi-line input (set to `1` by the `bin/` wrapper).
- `DEBUG` — debug verbosity (set to `1` by the `bin/` wrapper).

### Automatic session identifier

When neither `TOPSAILAI_SESSION_ID` nor `SESSION_ID` carries a non-blank value,
the command generates a session identifier before the agent starts, so every
chat run owns a session record, a session stdout file, and resumable history
instead of running without an identity.

- Resolution order: `TOPSAILAI_SESSION_ID`, then `SESSION_ID`, then generate.
  A configured value is used verbatim; a blank or whitespace-only value counts
  as unset.
- Generated format: the compact local timestamp `YYYYMMDDHHMMSS`, for example
  `20261105172015`. This is the same format the launcher uses, so chat sessions
  sort by creation time and stay recognizable in the session list.
- The effective identifier is exported through both `TOPSAILAI_SESSION_ID` and
  `SESSION_ID`, so the agent library, the session record, and any child process
  agree on one identity.
- The generated identifier is printed once as `session_id: <id>` when the agent
  library does not print it itself. The library prints that line only in
  interactive, non-debug runs, so the `bin/` wrapper (which sets `DEBUG=1`)
  shows the line from this command instead. A configured identifier is never
  announced by this command.

### Continuing history across turns

The `bin/topsailai_agent_chats` wrapper exports
`TOPSAILAI_AGENT2LLM_KEEP_MESSAGES_ACROSS_TURNS=1`. With this flag enabled, the
Agent2LLM message list is preserved across user2agent turns (instead of being
reset), so each round inherits the previous history and the conversation
continues seamlessly.

This differs from `topsailai_agent_plan_tasks`, which does not set the flag and
therefore starts each user2agent dialogue with a clean context.

## Examples

```bash
# Start an interactive multi-turn chat
topsailai_agent_chats

# Chat with an initial message
topsailai_agent_chats "Hello, let us review the project"

# Use a persistent session and a system prompt file
SESSION_ID=my-session SYSTEM_PROMPT=/path/to/system.txt topsailai_agent_chats

# Without any session variable, an identifier is generated and printed
topsailai_agent_chats

# Show help
topsailai_agent_chats -h
```

## Notes

- This is a single-agent, multi-turn chat; the `agent_tool` is disabled to
  avoid recursive agent calls.
- Exit by typing `exit`, `quit`, or pressing `Ctrl+C`.
- Session history can be maintained through `TOPSAILAI_SESSION_ID` or
  `SESSION_ID`; when neither is set, a `YYYYMMDDHHMMSS` timestamp is generated
  and printed so the run can be resumed later. Because that identifier is
  digits-only, `/cd`, `/send`, and `/resume` read it as a 1-based list index;
  select the session by its list position, or pass the identifier explicitly
  where a literal value is accepted.
