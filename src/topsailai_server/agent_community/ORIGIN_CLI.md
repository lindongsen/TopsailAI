---
maintainer: human
programming_language: go
related_technology_stack:
  - postgresql
  - nats
keywords:
  - cloud native
  - k8s
  - ai-agent
  - chat-system
---
# ACS CLI Terminal

This document describes the ACS CLI terminals. There are two terminals:

1. **Legacy full-featured terminal** — `cmd/cli/`. Exposes all ACS operations including accounts, API keys, groups, members, audit logs, and discovery.
2. **Focused group-chat terminal** — `cmd/cli_chat/`. Optimized for group lifecycle, member management, and chat. It uses Claude Code-style natural commands.

## Focused Group-Chat Terminal (`cmd/cli_chat/`)

Build:

```bash
go build -o bin/acs-cli-chat ./cmd/cli_chat
```

Run:

```bash
./bin/acs-cli-chat --api-base http://127.0.0.1:7370 --api-key "$API_KEY" --nats-url nats://localhost:4222 --no-color
```

### Commands

| Command | Description | Example |
|---------|-------------|---------|
| `/group list` | List visible groups | `/group list` |
| `/group create` | Create a new group | `/group create "AI Team" "Research group"` or `/group create --name "AI Team" --context "Research group" --key secret` |
| `/chat <group_id>` | Enter a group chat session | `/chat group-abc123` |
| `/member list` | List members of the current group | `/member list` |
| `/member add` | Add a user or agent member | `/member add worker-1 WorkerOne worker-agent` |
| `/group leave` | Leave the current group chat | `/group leave` |
| `/help` | Show help | `/help` |
| `exit` / `quit` | Exit the CLI | `exit` |

Legacy aliases such as `/group:create`, `/group:list`, `/group:enter`, `/member:add`, and `/member:list` are also supported.

### Authentication

- `--api-key {api_key_id}.{secret}` authenticates with an API key.
- `--login-name {name}` and `--login-password {password}` authenticate with login credentials.
- If no credentials are provided, the terminal prompts interactively.

### PS1 (Primary Prompt String)

Color: yellow

1. After startup terminal, PS1 should show like this: `acs@{userName}: `
2. After entering group, PS1 should show like this: `acs@{userName}:{groupId}# `

### Color

- Add ANSI color codes to enhance the UI
- Ensure colors work well on both dark and light terminal backgrounds (use standard ANSI, avoid hard-to-read combinations)
- Provide a `--no-color` flag and `NO_COLOR` env support to disable colors

- DONOT USE `Dim+BrightBlack`

### Time Format

All timestamps displayed in the terminal use the format: `YYYY-MM-DDTHH:MM:SS`, ISO 8601 without timezone or milliseconds.

### Interactive Commands

All management commands support an **interactive mode** — users type the command without any inline arguments, and the terminal prompts step-by-step for each required parameter.

### Backward Compatibility

If inline arguments are provided, the command executes in **non-interactive mode** using those arguments directly. This preserves compatibility with scripts and power users.

### Graceful Cancellation

At any prompt during an interactive flow, pressing **Ctrl+C** or pressing **Enter** without typing anything will cancel the current command and return to the normal prompt.

## Legacy Full-Featured Terminal (`cmd/cli/`)

The legacy terminal remains available for account, API key, audit log, and admin operations. See the original sections below for its command reference.

## Auto-Completion

When the user is in a group chat (after `/chat <group_id>`), typing `@` should trigger auto-completion suggestions for member names in that group. For example, if group members are "Alice", "Bob", and "agent-1", typing `@A` should suggest "Alice", typing `@B` should suggest "Bob", etc.

## Multi-byte Character Support (Chinese, Emoji, etc.)

This terminal provides:

- **Full UTF-8 support** — Chinese, Japanese, Korean, Emoji, and any Unicode characters work correctly
- **Proper backspace/delete** — Multi-byte characters are erased atomically (no partial character deletion)
- **Cursor movement** — Arrow keys work correctly across multi-byte characters
- **Line editing** — Home, End, Ctrl+A, Ctrl+E, and other readline shortcuts are supported
- **Command history** — Up/Down arrows navigate through previous commands

## NATS Real-time Messaging

When NATS is available (`--nats-url` is set and the server is reachable), the terminal subscribes to the group's JetStream subject (`ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message`, e.g. `{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`) for instant message delivery.

If NATS is unavailable, the terminal automatically falls back to HTTP polling every 2 seconds.
