---
references:
  - topsailai_cli.py
  - cli_topsailai/
  - topsailai.yaml
  - topsailai_models.py
---

# CLI: topsailai

Design notes, rules, caveats and references for the main `topsailai` CLI. Usage (commands, options, syntax, examples, exit codes) is documented in [docs/usage/topsailai.md](docs/usage/topsailai.md).

## Scope Index

The CLI is organized as five scopes. Each scope is a navigation and action context, not a separate process.

| Scope | Design intent |
|---|---|
| `workspace` | Default scope. Discovers session and task logs and acts as the entry point to every other scope. |
| `runtime` | Streams one session log and carries the live process-level messaging and control channel. |
| `project` | Navigates recent sessions by recorded project workspace and hosts the managed project registry. |
| `session` | Focuses on one session and its configured commands. |
| `doc` | Browses the Markdown documentation grouped under `docs/`. |

## Design Rules

- Interactive parameters use option flags and may provide a short alias for frequently used options. Main interactive aliases are `-t` / `--tui`, `-n` / `--tail-lines`, and `-m` / `--agent-mode`.
- Non-interactive parameters use subcommands, for example `project list`.
- `!<command>` executes a command line in the CLI process working directory using the `/git` parsing and execution mechanism, then remains in the current scope. `/git` instead resolves the active session's project workspace.
- Completion evidence requires the row PID to equal the session PID, so task rows are never marked `DONE`.
- Session-info display caching must not bypass the completion check, so cached names and project workspaces cannot make completed sessions reappear after a refresh.
- Metadata admission is absent-only, while successful session-info queries retain their existing updates.
- A session selector is applied immediately after log discovery, before any session-metadata read or session-info lookup, so an unselected row costs no I/O. The selector never splits one session's rows: task rows share their parent's `session_id` and stay with it, which also keeps the task parent-PID ambiguity check seeing the whole session. An empty selector is rejected rather than treated as "select everything", because the two meanings are opposite.
- A hostname filter is applied after hostname resolution, never during discovery, so it reads exactly the value the table and the JSON `hostname` field report. A row is local when its resolved hostname equals the local hostname or is empty; an empty value means the origin is unknown, so such a row is kept rather than hidden, and a non-string value is treated the same way. The comparison is exact and case-sensitive because a hostname is an operating-system identifier, not a display label. An unusable local hostname disables the filter instead of dropping every row.
- Session-info enrichment resolves every unresolved identifier with one batched `topsailai_sessions_info` invocation, never one lookup per session. That command bounds both costs independently of the number of identifiers: one storage query for all of them, and one scan of the session stdout directory for all running statuses, where the single-session command scans once per session. A non-zero exit code from that command is not a failure by itself because it reports unknown identifiers; the JSON array on stdout is authoritative, an absent identifier stays unresolved and is retried rather than cached as a failure, and only an unusable response is treated as transient. Diagnostics go to stderr, so a failed lookup leaves stdout empty instead of an unparseable `[ERROR]` line.
- Workspace field resolution is primary-then-metadata: the session-info lookup and the recorded project-workspace index stay authoritative, and the row's exact session metadata record is consulted only for a field the primary source left empty. The fallback binds to the row's own `(session_id, pid)` pair and never substitutes another session's or another PID's record.
- Metadata-derived values are display evidence only. `workspace_pid` stays liveness-gated and remains the sole PID `/kill` may signal, while the metadata PID is carried in a separate display field, so no signal authority and no `process_generation` is ever derived from metadata.
- Driver commands are restricted to the ordinary workspace task list; project, session, runtime, doc and managed-project views reject them.
- `start` reuses the managed project list and the shared launch boundary instead of introducing a second project source or a second launch path: without a folder it displays exactly the list `p` displays and resolves the row through the same resolver `p agent <number>` uses, and with `-f/--folder` it skips the list and the prompt entirely. The row number is validated before resolution, because the resolver treats a non-numeric argument as a literal folder path. An explicit folder must be an existing directory, so a typo is reported instead of launching an agent in a folder that does not exist. The command is workspace-only, and the restricted managed-project view keeps its own accepted set.
- The external driver alone owns duplicate-start exclusion, its lock, metadata and log cleanup. The CLI never writes, acquires or deletes these records.
- The CLI retains live child handles in memory and reaps exits on later interactions without terminating resident drivers when leaving the CLI.
- Resume driver selection does not use `ai_agent_driver` or `TOPSAILAI_AGENT_DRIVER`; only the built-in driver choices apply.
- The selected model configuration is resolved immediately before an agent launch or resume and applies only to the launched child process, never to the parent shell.
- The CLI validates driver entry files once at its configuration boundary. An invalid explicit override is rejected rather than silently replaced with a default, and configuration changes require restarting the CLI.
- In `workspace`, `session`, `project` and `runtime` scope the leading `/` of a command is optional, so a command and its `/`-prefixed spelling are the same command. Only the first token is normalized, so the remainder of the line (a message body, a JSON payload or a path) is passed through unchanged. The `!<command>` shell escape is never normalized. In `runtime` scope the optional slash is implemented as a match against the runtime command set rather than a blind normalization: input whose first token names a runtime command is treated as that command, input that already starts with `/` is never reinterpreted so an unknown slash command is still reported as unknown, and input that matches no command keeps the send-as-message prompt.
- Command aliases are declared once in `cli_topsailai/constants.py` and consumed by parsing, help and completion, so a spelling cannot be accepted in one surface and missing from another. `/session` accepts `messages`, and `/refresh` accepts `list` and `l`; each alias is accepted with and without the leading `/`, and `r`/`/r` remain the pre-existing short form of `/refresh`. An alias is the same command, not a new one, so it shares the same behavior, arguments and errors: `list` and `l` take no limit, while project-scope `r [limit]` keeps its limit. The restricted managed-project view keeps its own accepted set, so the aliases are rejected there.
- Runtime aliases are declared once in `cli_topsailai/constants.py` as `RUNTIME_COMMAND_ALIASES` and expanded by the shared runtime recognizer `_runtime_command_line`, so every dispatch site (curses, raw and legacy streaming) receives exactly one canonical spelling and no handler duplicates alias handling. `btw` expands to `ctx.btw` and `model` expands to `agent.models`, each accepted with and without the leading `/`. Only the first token is replaced, so a message body, a JSON payload or a path is never rewritten. These aliases cannot be declared in `topsailai.yaml`: `/ctx.btw` extracts its free-form message only from the `cmd` template, so a YAML alias would silently drop the message body, and `agent.models` is not a YAML command at all but the `/agent.<instruction>` shortcut. The completer and the help text read the same declaration, so an alias cannot be accepted without being discoverable, and every unknown-command and startup guidance string names the aliases.
- The interactive `/clean` command and the non-interactive `workspace clean` command share one expiry constant and one inventory helper, so eligibility cannot drift between them. The non-interactive form previews by default and deletes only with `--yes`, because an implicit default must never authorize an irreversible action. Every deletion is revalidated immediately before removal, and a run in which every candidate was skipped reports `nothing_to_delete` instead of claiming a deletion that never happened.
- A cleanup selector must name the identity that owns the deletion unit. `workspace clean` groups files by the `{session_id}.{pid}` owner prefix, so `-p/--pid` matches the owning session PID reported in `session_pid`, never the child PID of a task file that the session produced; matching the child PID would select a file whose deletion unit belongs to a different PID. A session ID alone selects every instance of that session, so the PID is the only way to target one run, and the two selectors combine as an intersection. Any active selector excludes launch logs, because they carry no session owner and no owner PID and would otherwise widen the inventory beyond what the operator named.

## Caveats

- Delivery states are boundary facts, not business completion: `pipe_written` means FIFO bytes were written, `injection_queued` means the writer queued the message, and `control_acknowledged` means a correlated response reported `status=ok`.
- Failed or uncertain delivery may carry partial evidence or `delivery_unknown=true`. Never blindly retry, because a duplicate operation can have real effects; the CLI never automatically retries a whole operation.
- The task directory is assumed to be trusted local per-user storage. Endpoint, type and path checks plus PID liveness are not authenticated receiver identity, so PID reuse and filesystem replacement races remain possible. This interface is not a security boundary against a hostile task directory or other local users.
- Process identity checks are conservative and cannot prove complete PID-reuse protection without an authoritative stored birth baseline. Target checks occur before launch, and the external driver selects by session ID rather than a strictly bound target PID, so a preflight/spawn race is possible.
- Interactive `/kill` does not verify process-instance identity, so stale lists must be refreshed before use. Non-interactive termination requires the verified process generation instead.
- Publication proves driver liveness, not model readiness or analysis completion. An unconfirmed child may still run.
- Clean driver finalization normally removes metadata and logs, so `EXIT` and `FAIL` are residual observations rather than durable exit history.
- Log and metadata reads are bounded snapshots, not transactions; incomplete concurrent writes report an error without automatic retries. `logs -f/--follow` is the only unbounded-duration read: it holds one descriptor, prints only complete records, keeps at most a 1 MiB unterminated remainder, and ends on host interrupt with exit `0`.
- Log content may contain secrets or terminal escape sequences, and `/env.search` intentionally displays values that may contain secrets.
- FIFO messaging requires platform FIFO support and control uses Unix-domain sockets; no cross-platform fallback transport is silently selected.
- The dual-pane UI relies on the Python `curses` module and falls back to a single-pane mode when it is unavailable or stdout is not a TTY.

## References

- [docs/usage/topsailai.md](docs/usage/topsailai.md) — usage contract for this CLI.
- [docs/usage/README.md](docs/usage/README.md) — usage index and `TOPSAILAI_HOME` layout.
- [docs/usage/topsailai_models.md](docs/usage/topsailai_models.md) — model registry usage.
- [docs/usage/topsailai_launch_agent.md](docs/usage/topsailai_launch_agent.md) — launcher usage.
- [docs/usage/topsailai_session_add_message.md](docs/usage/topsailai_session_add_message.md) — persistent user-to-agent messages.
- [docs/usage/topsailai_session_add_agent2llm_message.md](docs/usage/topsailai_session_add_agent2llm_message.md) — runtime agent2llm injection.
- [docs/usage/topsailai_project_history.md](docs/usage/topsailai_project_history.md) — project history listing.
