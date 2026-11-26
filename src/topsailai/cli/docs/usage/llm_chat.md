---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# llm_chat

Single-turn chat directly with a language model.

## Purpose

Runs one exchange with a model and exits. No tools are available, so this is the
simplest way to send one message and read one answer.

## Invocation

```bash
./llm_chat.py [message ...]
```

Because the script is registered in `../bin/` as `llm_chat`, you can also run it
as:

```bash
llm_chat [message ...]
```

## Arguments

| Argument | Description |
|----------|-------------|
| `message` | Optional chat content for the single turn. |

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Environment Variables

- `TOPSAILAI_PRINT_ENABLED` — allows framework display output in noninteractive
  mode. This command defaults it to `0` when it is not configured, so display
  output stays off unless the caller asks for it. A configured value is used
  verbatim, including an empty one.
- `TOPSAILAI_CLI_NEED_TIPS` — when truthy (default `true`), prints the first
  message and the `>>> answer:` prompt. Debug mode suppresses the tips.
- `SESSION_ID` / `TOPSAILAI_SESSION_ID` — session identifier for conversation
  history.
- `SYSTEM_PROMPT` — a file path or inline content for the system prompt.
- `DEBUG` — debug verbosity. The `bin/` wrapper sets it to `0` when unset.

## Examples

```bash
# One turn with an initial message
llm_chat "Summarize the repository layout"

# Keep a session so the exchange is recorded
SESSION_ID=my-session llm_chat "Hello"

# Ask for framework display output explicitly
TOPSAILAI_PRINT_ENABLED=1 llm_chat "Hello"

# Show help
llm_chat -h
```

## Notes

- This is a single-turn chat; the process exits after the answer.
- No tools are available in this mode.
- The `TOPSAILAI_PRINT_ENABLED` default is applied by the command itself before
  the chat object is created, so it does not depend on the caller shell or on a
  project settings file.
