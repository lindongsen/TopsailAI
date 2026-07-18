---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# TopsailAI CLI Usage Documentation

This directory contains per-script usage documentation for every CLI entry point whose name starts with `topsailai` in the current workspace (`/TopsailAI/src/topsailai/cli/`).

## How commands are dispatched

Most CLI scripts are invoked through the dispatcher at `../bin/topsailai.cli`. The dispatcher resolves the script name from `basename "$0"` and runs `cli/<name>.py` inside this workspace. Therefore each script has a matching symlink in `../bin/`:

```bash
ls -l ../bin/topsailai*
```

You can run a script either directly from this directory or by its command name (if `../bin/` is on your `PATH`):

```bash
./topsailai.py --help
topsailai --help
```

## Documented scripts

| Script | Purpose |
|--------|---------|
| [topsailai](topsailai.md) | Main interactive CLI: watch sessions, send messages, manage workspace task list. |
| [topsailai_agent_call_instruction](topsailai_agent_call_instruction.md) | Send a one-off instruction to an agent session. |
| [topsailai_agent_plan_task](topsailai_agent_plan_task.md) | Create a single plan/task for an agent session. |
| [topsailai_agent_plan_tasks](topsailai_agent_plan_tasks.md) | Batch-create plans/tasks from a file or command-line list. |
| [topsailai_agent_story](topsailai_agent_story.md) | Manage story memory for an agent session. |
| [topsailai_count_tokens](topsailai_count_tokens.md) | Count tokens in text or files. |
| [topsailai_launch_agent](topsailai_launch_agent.md) | Launch an AI agent driver from `.topsailai/settings.yaml`. |
| [topsailai_logf](topsailai_logf.md) | Tail/follow session or task log files. |
| [topsailai_project_history](topsailai_project_history.md) | Display recent project/workspace navigation history. |
| [topsailai_session_add_agent2llm_message](topsailai_session_add_agent2llm_message.md) | Inject a by-the-way message into a running agent's LLM context. |
| [topsailai_session_add_message](topsailai_session_add_message.md) | Append a persistent user-to-agent message for the next agent run. |
| [topsailai_session_info](topsailai_session_info.md) | Show detailed information about a session. |
| [topsailai_session_status](topsailai_session_status.md) | Check whether a session is running and report basic status. |
| [topsailai_stream_sessions](topsailai_stream_sessions.md) | Stream session output to stdout or another consumer. |
| [topsailai_team](topsailai_team.md) | Launch or manage a multi-agent team workflow. |
| [topsailai_test_tool_approval_rules](topsailai_test_tool_approval_rules.md) | Validate `tool_approval.json` rules. |

## Common options

Many scripts share the following options:

| Option | Description |
|--------|-------------|
| `--home <path>` | Override the `TOPSAILAI_HOME` directory. |
| `--session-id <id>` | Target a specific agent/session ID. |
| `--db-conn <string>` | Provide a database connection string. |
| `--json` | Output structured JSON instead of human-readable text. |

## Workspace conventions

- All scripts are implemented as Python files in `/TopsailAI/src/topsailai/cli/`.
- Shared helpers live in the `cli_topsailai/` package.
- Unit tests are organized under `tests/unit/<cli-name>/`.
- For the full workspace guide, see `../README.md` in this directory.

## Historical documents

Some scripts had pre-existing design notes in the workspace root. Those files are preserved in place and their content has been merged into the usage docs above:

- `../../topsailai.md` — original high-level scope outline for the main `topsailai` CLI.
- `../../topsailai_session_add_agent2llm_message.md` — original design document for Agent2LLM runtime message injection.

The merged usage documents reference these originals where relevant.
