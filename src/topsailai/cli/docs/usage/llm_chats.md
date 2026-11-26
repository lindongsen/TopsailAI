---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# llm_chats

Multi-turn chat directly with a language model.

## Purpose

Runs a continuous conversation with a model, up to 100 turns, and exits when the
input channel closes. No tools are available, so this is the conversational
counterpart of `llm_chat`.

## Invocation

```bash
./llm_chats.py [message ...]
```

Because the script is registered in `../bin/` as `llm_chats`, you can also run it
as:

```bash
llm_chats [message ...]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `message` | Optional chat content for the first turn. |

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Environment Variables

- `TOPSAILAI_PRINT_ENABLED` — allows framework display output in noninteractive
  mode. This command defaults it to `0` when it is not configured, so display
  output stays off unless the caller asks for it. A configured value is used
  verbatim, including an empty one.
- `TOPSAILAI_CLI_NEED_TIPS` — when truthy (default `true`), prints the session
  line. Debug mode suppresses the tips.
- `SESSION_ID` / `TOPSAILAI_SESSION_ID` — session identifier for conversation
  history.
- `SYSTEM_PROMPT` — a file path or inline content for the system prompt.
- `TOPSAILAI_CHAT_MULTI_LINE` — enables multi-line input (set to `1` by the
  `bin/` wrapper).
- `DEBUG` — debug verbosity. The `bin/` wrapper sets it to `0` when unset.

## Examples

```bash
# Start a multi-turn conversation
llm_chats

# Start with an initial message
llm_chats "Let us review the design"

# Keep a session across turns
SESSION_ID=my-session llm_chats

# Ask for framework display output explicitly
TOPSAILAI_PRINT_ENABLED=1 llm_chats

# Show help
llm_chats -h
```

## Notes

- The loop stops after 100 turns, or earlier when the input channel closes.
- No tools are available in this mode.
- The `TOPSAILAI_PRINT_ENABLED` default is applied by the command itself before
  the chat object is created, so it does not depend on the caller shell or on a
  project settings file.
