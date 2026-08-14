---
maintainer: AI
workspace: /TopsailAI/src/topsailai/cli
ProjectFolder: /TopsailAI/src/topsailai/cli
ProjectRootFolder: /TopsailAI/src/topsailai
ProjectCode: TOPSAILAI
programming_language: python
---

# topsailai_team

AI Team Manager: route and coordinate team agents.

## Purpose

Starts a coordinated multi-agent team session. The team workflow dispatches tasks to sub-agents and aggregates their outputs. This script is the CLI entry point for the `ai-team-flow-dev` driver and related team orchestration logic.

## Design

`topsailai_team.py` starts a single **manager** agent. A human interacts with this manager agent, which delegates concrete tasks to `team_agent.py` / `team_chat.py` through its tools/skills.

The script also sets `TOPSAILAI_ENABLED_TOOLS` as an intentional exclusive allowlist (`story_memory_tool`, `ai_team`, `skill_tool`, `human_tool`) so that only the listed team tools are enabled; other default-enabled tools (e.g. `cmd_tool`, `file_tool`, `time_tool`, `ctx_tool`) are deliberately disabled for the manager process.

## Invocation

```bash
./topsailai_team.py
```

Because the script is registered in `../bin/` as `topsailai_team`, you can also run it as:

```bash
topsailai_team
```

## Options

| Option | Description |
|--------|-------------|
| `-h`, `--help` | Show the help message and exit. |

## Configuration

The script is configured through environment variables and the session store, not command-line arguments:

- `TOPSAILAI_AGENT_DRIVER` / `ai_agent_driver` — selects the team driver to launch.
- `TOPSAILAI_HOME` — workspace root for logs, locks, and task files.
- `TOPSAILAI_PROJECT_WORKSPACE` / `TOPSAILAI_PWD` — project workspace and working directory for the session.

## Examples

```bash
# Start the team manager
topsailai_team

# Show help
topsailai_team -h
```

## Notes

- The script does not accept positional arguments; team configuration is read from the environment and session context.
- Sub-agents write their stdout to `{TOPSAILAI_HOME}/workspace/task/`.
