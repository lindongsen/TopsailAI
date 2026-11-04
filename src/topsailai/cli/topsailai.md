---
references:
  - topsailai_cli.py
  - cli_topsailai/
  - topsailai.yaml
  - topsailai_models.py
---

# CLI: topsailai

## Scope: workspace

- task list

## Scope: runtime

- steam log of one session
- `/ctx.btw [message]` queues an agent2llm message for the watched PID.
- `/ctx.btw-all [message]` queues the message for all discoverable live PIDs in the current session; temporary session id `topsailai` is rejected, partial success is allowed, failures are not automatically retried, and success means queued rather than consumed.

## Scope: project

- project workspace
- shows recent records, default limit 30, use `r [limit]` to adjust

## Scope: session

- enter one session

## Scope: doc

- usage documentation list
- read usage documentation

## Commands Available in All Scopes

- `!<command>` executes a command line in the CLI process working directory using the `/git` parsing and execution mechanism, then remains in the current scope; for example, `!git status`.

## Workspace commands

- `/env.search <term> [term...]` fuzzy-searches configurable environment variables with case-insensitive OR matching, checking `.env.local`, `.env`, then `env_template`; it displays matching `NAME=VALUE` assignments from every source, suppresses names already found in a higher-priority source, and retains displayed names for TAB completion.
- `/driver log <number>` reads the bounded active driver log in workspace scope.
- `/driver meta <number>` reads validated active driver metadata in workspace scope and differs from `/meta`.
- `r all` or `/refresh all` includes rows whose exact session metadata records `status: completed`; they render `DONE`. A plain `r` or `/refresh` restores the default hidden view.

## Non-interactive subcommands

- `workspace [-f|--format json] [list [--json]]` — displays the task list. Scope-level `-f/--format` sets the output format; `list --json` overrides it. The default is the table.
- `runtime [-s SESSION] [-p PID] -i INSTRUCTION`
- `runtime send|btw [-s SESSION] [-p PID] -m MESSAGE|--stdin`
- `runtime control ACTION [-s SESSION] [-p PID] [-a JSON]`
- `runtime logs [-s SESSION] [-p PID] [-n N] [--json]` — finite recent session log query
- `workspace agent [<folder>] [-m MODE] [-b|--background] [--non-interactive] [--json]`
- `workspace kill SESSION -g GENERATION [--json]` — requires the verified `process_generation` from `workspace list --json` or `workspace -f json` and fails closed when process-instance evidence changes or is unavailable
- `workspace driver start|status|stop -s SESSION [-p PID] [--json]`
- `project add|del|list|launch|resume`
- `models list|add|get|update|delete`

## Command Design Convention

- Interactive parameters use option flags and may provide a short alias for frequently used options.
- Main interactive aliases are `-t` / `--tui`, `-n` / `--tail-lines`, and `-m` / `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.

## Non-interactive workspace agent

Canonical usage: `topsailai workspace agent [<folder>] [-m raw|dtach|tmux] [-b|--background] [--non-interactive] [--json]`. See [the canonical workspace-agent usage contract](docs/usage/topsailai.md#workspace-agent). It launches in the foreground; the folder is optional and defaults to the caller's working directory, and an explicit folder is resolved against the caller's original working directory. `--non-interactive` suppresses launcher prompts for this launch only and does not change the agent's own interactive mode. Exit codes are 2 for usage/background rejection, 3 for invalid folder, 4 for preparation, 5 for spawn/wait, 6 for unresolved custody, and 130 for cancellation; observed child statuses are preserved and signals map to `128 + signal`. A wrapper exit is not agent completion. Background `submitted` means not-ready. With `--json`, stdout contains one receipt and ordinary output is redirected to stderr.

## Resume commands

- `/resume <number> [-d DRIVER]` and `project resume SESSION [-d DRIVER]` default to `topsailai_agent_chats`. The override accepts `topsailai_agent_chats`, `topsailai_agent_plan_tasks`, or `ai-team-flow-dev`; settings and environment driver values do not select a resume executable.

## Workspace resume

- `workspace resume -s SESSION [-d DRIVER] [-m raw|dtach|tmux] [-b|--background] [--json]` resumes an exact persisted idle session.
- Resume defaults to `topsailai_agent_chats`; `-d/--driver` accepts `topsailai_agent_chats`, `topsailai_agent_plan_tasks`, or `ai-team-flow-dev`.
- Foreground defaults to dtach; background defaults to raw and reports submission, not readiness.
- See [the resume contract](docs/usage/topsailai.md#workspace-resume) for validation, logs, exit codes and concurrency limitations.
