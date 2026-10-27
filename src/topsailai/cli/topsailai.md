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

- `/driver log <number>` reads the bounded active driver log in workspace scope.
- `/driver meta <number>` reads validated active driver metadata in workspace scope and differs from `/meta`.

## Non-interactive subcommands

- `runtime [-s SESSION] [-p PID] -i INSTRUCTION`
- `runtime send|btw [-s SESSION] [-p PID] -m MESSAGE|--stdin`
- `runtime control ACTION [-s SESSION] [-p PID] [-a JSON]`
- `runtime logs [-s SESSION] [-p PID] [-n N] [--json]` — finite recent session log query
- `workspace agent <folder> [-m MODE] [-b|--background]`
- `workspace driver start|status|stop -s SESSION [-p PID] [--json]`
- `project add|del|list|launch|resume`
- `models list|add|get|update|delete`

## Command Design Convention

- Interactive parameters use option flags and may provide a short alias for frequently used options.
- Main interactive aliases are `-t` / `--tui`, `-n` / `--tail-lines`, and `-m` / `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.

## Non-interactive workspace agent

Canonical usage: `topsailai workspace agent <folder> [-m raw|dtach|tmux] [-b|--background]`. See [the canonical workspace-agent usage contract](docs/usage/topsailai.md#workspace-agent). It launches in the foreground and resolves relative folders against the caller's original working directory. Exit codes are 2 for usage/background rejection, 3 for invalid folder, 4 for preparation, 5 for spawn/wait, 6 for unresolved custody, and 130 for cancellation; observed child statuses are preserved and signals map to `128 + signal`. A wrapper exit is not agent completion. UNIT 1A has no background submission; future `submitted` means not-ready. There is no `--json` output.
