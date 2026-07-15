# `bin/` — Executable Command Registry

This directory contains the command-line entry points that are intended to be exposed on the user's `PATH`.

Each entry here is one of:

- a **shell script** that bootstraps and dispatches to a CLI implementation,
- a **symbolic link** to such a shell script, or
- a **compiled binary**.

## Quick Start

Add this directory to your shell's `PATH`:

```bash
export PATH="/TopsailAI/src/topsailai/bin:$PATH"
```

Then run any registered command by name, for example:

```bash
topsailai --help
ai_agent "task content"
llm_chat "hello"
```

## Layout

```text
bin/
├── topsailai.cli              # Generic dispatcher for ../cli/<name>.py
├── <custom-wrapper>           # Special-purpose shell scripts (e.g. ai_agent, llm_chat)
├── <cli-name> -> topsailai.cli           # Symlink to the generic CLI dispatcher
├── <topsailai_xxx> -> <custom-wrapper>   # Symlink to a custom wrapper
└── <alias> -> <existing-command>         # Alias symlink for shorter invocation
```

### Alias Symlinks

Some commands are exposed under an additional, shorter alias by symlinking one name to another existing command in `bin/`. These aliases are purely for convenience and do **not** introduce new dispatch logic.

Example alias symlinks:

- `topsailai_agent_chats` → `agent_chats` (shorter invocation for `agent_chats`)
- `topsailai_agent_chat` → `agent_chat` (shorter invocation for `agent_chat`)
- `topsailai_llm_chat` → `llm_chat` (shorter invocation for `llm_chat`)
- `topsailai_llm_chats` → `llm_chats` (shorter invocation for `llm_chats`)

When adding an alias, create a symlink that points to the canonical command name already present in `bin/`, not to a dispatcher script directly. This keeps alias behavior identical to the canonical command and avoids duplicating dispatch logic.

> **Note:** When modifying a command, edit the **canonical script** (the real file) rather than its alias symlinks. Alias symlinks only forward invocations and should not contain logic.

## How Commands Are Resolved

### 1. Generic Python CLI Dispatcher

`topsailai.cli` is the default dispatcher for Python-based CLI scripts.

When a symlink named `<cli-name>` points to `topsailai.cli`, the dispatcher:

1. resolves `WORK_DIR` to the project root (`bin/../`),
2. determines the runner (`uv run` by default, or `python` when `UV_NO_DEV=1`),
3. executes `cli/<cli-name>.py` with all original arguments.

Example symlinks using this mechanism:

- `topsailai` → `topsailai.cli` → runs `cli/topsailai.py`
- `ai_team` → `topsailai.cli` → runs `cli/ai_team.py`
- `topsailai_session_status` → `topsailai.cli` → runs `cli/topsailai_session_status.py`

### 2. Custom Wrapper Scripts

Some commands require special argument handling or environment setup. These are implemented as standalone shell scripts in `bin/` and may also be exposed through symlinks.

Examples:

- `ai_agent` — wraps `cli/AgentReAct.py` and handles `SYSTEM_PROMPT`, `ENABLED_TOOLS`, `DISABLED_TOOLS`.
- `agent_chat` — wraps `cli/agent_chat.py` and handles `SESSION_ID` / `SYSTEM_PROMPT`.
- `llm_chat` — wraps `cli/llm_chat.py` and handles `SESSION_ID` / `SYSTEM_PROMPT`.
- `ai_team` — wraps `cli/ai_team.py`.

## Conventions

### Prefer the `topsailai` Prefix

Command names in `bin/` should generally start with `topsailai` (or `topsailai_`). This makes it obvious that the command belongs to the TopsailAI project and reduces the chance of colliding with other tools on the user's `PATH`.

Preferred forms:

- `topsailai` for the main entry point.
- `topsailai_<subcommand>` for project-branded commands (e.g. `topsailai_query_msg`, `topsailai_session_status`).

Short aliases without the prefix are acceptable for frequently used commands (e.g. `ai_agent`, `llm_chat`, `agent_chat`), but the canonical `bin/` entry should still have a `topsailai_` prefixed form when practical.

When using the generic dispatcher, keep the `topsailai_` command name consistent with the underlying `cli/<name>.py` script whenever possible.

### Adding a New Command

1. If the command maps directly to `cli/<name>.py` with no extra logic, create a symlink:

   ```bash
   ln -s topsailai.cli <cli-name>
   ```

2. If the command needs special environment handling, write a dedicated shell script in `bin/` and optionally expose it through symlinks.

3. Update this `README.md` to document the new command and its mechanism.

## Environment Variables Used by Dispatchers

| Variable | Used by | Description |
|----------|---------|-------------|
| `UV_NO_DEV` | Generic dispatcher, custom wrappers | When set to `1`, run Python scripts with `python` instead of `uv run`. |
| `TOPSAILAI_AGENT_TYPE` | Generic dispatcher, custom wrappers | Default agent type passed to the CLI (defaults to `react`). |
| `TOPSAILAI_PWD` | Custom wrappers | Preserves the original working directory before `cd` into `WORK_DIR`. |
| `SYSTEM_PROMPT` | `ai_agent`, `agent_chat`, `llm_chat` | File path or content used as the system prompt. |
| `SESSION_ID` | `agent_chat`, `llm_chat` | Session identifier for persistent memory. |
| `TOPSAILAI_SESSION_ID` | `agent_chat`, `llm_chat` | Fallback session identifier used when `SESSION_ID` is not set. |
| `TOPSAILAI_ENABLED_TOOLS` | `ai_agent` | Comma-separated list of enabled tool patterns (default `*`). |
| `TOPSAILAI_DISABLED_TOOLS` | `ai_agent` | Comma-separated list of disabled tools (default `sandbox_tool,hook_tool,subagent_tool`). |

## Notes

- Do **not** edit compiled binaries directly; rebuild them from their source packages.
- When renaming or removing a command, update all symlinks that point to it.
- Keep wrapper scripts small and focused on dispatch logic; business logic belongs in `cli/` or `src/`.
