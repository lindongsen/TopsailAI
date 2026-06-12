# ACS CLI Terminal

## PS1 (Primary Prompt String)

Color: yellow

1. After startup terminal, PS1 should show like this: `acs@{userName}: `
2. After entering group, PS1 should show like this: `acs@{userName}:{groupId}# `

## Command

Format: `/{CLASS}:{ACTION}`, example: `/group:enter`

- type 'exit' or 'quit' is same to '/exit'
- type 'help' is same to '/help'

### Command: /group:list

Show detail group info, including of name, creator etc..

### Interactive

> 不要传参，而是要引导用户输入参数值

Example:
```
/group:create

用户只需要输入 "/group:create"
接下来会有交互式对话去让用户填入必要的参数
```

> group:enter 之后，则进入聊天窗口，消息也会实时更新

## Multi-byte Character Support (Chinese, Emoji, etc.)

This terminal uses `github.com/chzyer/readline` for input handling, which provides:

- **Full UTF-8 support** — Chinese, Japanese, Korean, Emoji, and any Unicode characters work correctly
- **Proper backspace/delete** — Multi-byte characters are erased atomically (no partial character deletion)
- **Cursor movement** — Arrow keys work correctly across multi-byte characters
- **Line editing** — Home, End, Ctrl+A, Ctrl+E, and other readline shortcuts are supported
- **Command history** — Up/Down arrows navigate through previous commands

## NATS Real-time Messaging

When NATS is available (`-nats-url` is set and the server is reachable), the terminal subscribes to the group's JetStream subject (ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX=acs.group.message # e.g. `{ACS_NATS_SUBJECT_GROUP_MESSAGE_PREFIX}.{group_id}`) for instant message delivery.

If NATS is unavailable, the terminal automatically falls back to HTTP polling every 2 seconds.

## Color

- Add ANSI color codes to enhance the UI
- Ensure colors work well on both dark and light terminal backgrounds (use standard ANSI, avoid hard-to-read combinations)
- Provide a `--no-color` flag and `NO_COLOR` env support to disable colors

- DONOT USE `Dim+BrightBlack`

## Time Format

All timestamps displayed in the terminal use the format: `YYYY-MM-DDTHH:MM:SS`, ISO 8601 without timezone or milliseconds.

## Interactive Commands

All management commands support an **interactive mode** — users type the command without any inline arguments, and the terminal prompts step-by-step for each required parameter.

### Backward Compatibility

If inline arguments are provided, the command executes in **non-interactive mode** using those arguments directly. This preserves compatibility with scripts and power users.

### Graceful Cancellation

At any prompt during an interactive flow, pressing **Ctrl+C** or pressing **Enter** without typing anything will cancel the current command and return to the normal prompt.
