---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
author: DawsonLin
status: resolved
---

# Issue: Non-Interactive Mode Produced No Usable stdout Content

## Symptom

Session `wa-39bd6bd5e6d4` (PID `3743178`, project `topsailai-weixin`) ran for over an
hour with a session stdout file that contained no usable information. The file grew to
8728 bytes, but every line was a `\rGenerating... N chars, N tokens` spinner frame.
Removing spinner frames and blank lines left zero meaningful lines.

The agent was not idle. Its event log recorded 309+ events, 63+ `llm.request.start`,
61+ `tool_call.start`, Agent2LLM `message_count` grew from 5 to 138, and context
summarization triggered. The work was real; only its stdout record was missing.

## What Is Not the Defect

The two print predicates are intentionally different and must stay different:

- `utils/env_tool.py::is_print_enabled()` gates framework narrative: the timestamped
  thought/action/tool-step lines.
- `utils/env_tool.py::is_need_print()` gates whether the framework may display anything
  at all, including display-only liveness components such as `ContentProgress`.

`ContentProgress` writes to `sys.stdout` directly and bypasses `print_with_time()`. That
bypass is deliberate: it keeps a liveness signal visible when the narrative gate is
closed. Routing it through the narrative gate would leave a closed-gate run with no
visible output whatsoever, which is worse than the current state.

## Actual Defect

A non-interactive run produced no stdout content, and that outcome is not acceptable.
Non-interactive means only that the agent does not prompt for input. It does not mean
the run should leave no record.

The session inherited `TOPSAILAI_INTERACTIVE_MODE=0` together with
`TOPSAILAI_PRINT_ENABLED=0`, the latter coming from the default in
`{TOPSAILAI_HOME}/.env` line 245. With both closed, `is_print_enabled()` returned
`False`, so `print_with_time()` discarded every narrative line. The only surviving
output was the spinner, because `DEBUG=1` opened `is_need_print()`.

So the configuration combination, not the predicate split, is what made the session
unreadable. `TOPSAILAI_PRINT_ENABLED` exists exactly to decouple "do not prompt" from
"do not print", and a background deployment is expected to set it to `1`.

## Contributing Factor: Settings Resolved From Launcher cwd

`topsailai_launch_agent` resolves `.topsailai/settings.yaml` from its own working
directory. The launcher ran from the project root, so it read
`/opt/git/ai/lindongsen/work/topsailai-weixin/.topsailai/settings.yaml`, which set
`TOPSAILAI_INTERACTIVE_MODE: "0"`.

A second file, `/opt/git/ai/lindongsen/work/topsailai-weixin/workspace/.topsailai/settings.yaml`,
set the same key to `"1"`. The two files differed by exactly that one line, so the
observable behavior depended on which directory the launcher happened to start from.
Neither file set `TOPSAILAI_PRINT_ENABLED`, so both fell through to the `0` default.

## Impact

- A long-running background agent can appear silent while doing substantial work.
- The session stdout artifact, which exists specifically for post-hoc diagnosis, is
  unusable for that purpose.
- `TeeOutput` is not at fault: `session.stdout` and `agent-launch.log` were verified
  byte-identical with `cmp`, so the tee path works and the content never reached it.

## Suggested Direction

Make a non-interactive deployment produce a usable stdout record by default, rather
than requiring the operator to discover `TOPSAILAI_PRINT_ENABLED` after a session has
already run blind. Options worth evaluating:

- Set `TOPSAILAI_PRINT_ENABLED=1` in the launch path whenever the launcher starts a
  background agent, so the narrative gate stays open while input prompts stay off.
- Or change the default so that a non-interactive run still prints narrative, and let
  an explicit opt-out silence it.

Either way, keep the `is_need_print()` / `is_print_enabled()` split intact, and keep
`ContentProgress` independent of the narrative gate.

## Mitigation Applied

Both variables were set to `1` in the two `settings.yaml` files, and the running process
was overridden in memory through the control channel (`env.set`), verified with
`env.get`. The override is process-scoped and dies with the process; the configuration
change covers future launches. Neither changes the default that produced the silent run.

## Resolution

The second option was chosen: the default now permits printing, and an explicit `0`
silences it. A non-interactive run therefore produces a usable stdout record without
any operator action.

Changed together, because either one alone is insufficient:

- `utils/env_tool.py::is_print_enabled()` — the code default is now `"1"`.
- `env_template` — the tracked file that `/root/.topsailai/.env` symlinks to. It
  previously set `TOPSAILAI_PRINT_ENABLED=0`, and `topsailai/__init__.py::__load_env()`
  applies it through `load_dotenv` at import, so a code-only change would have been
  silently overridden.
- `docs/Environment_Variables.md` — the table row now documents `1` as the default.

The `is_need_print()` / `is_print_enabled()` split is unchanged, and `ContentProgress`
still bypasses the narrative gate.

Two tests encoded the old default and were updated:

- `test_output_permission_matrix` treated an unset variable as silenced; it now treats
  unset as permitted, and a new `test_unset_default_permits_output_in_noninteractive_mode`
  pins that contract.
- `test_print_debug_no_output` exercises the debug gate, not the output gate. It now sets
  `TOPSAILAI_PRINT_ENABLED=0` explicitly, because `print_debug` gates on
  `is_need_print()`, which is open by default.

Verification: the affected suites pass (116 tests), `tests/unit/workspace` passes (949),
and the mandated runner reports 389 failures that are byte-identical to pristine `HEAD`
in an isolated worktree — all in `test_topsailai_hooks` (missing `pytest-asyncio`) and
one mock-server timing file, none related to this change.

Deployments that relied on silence must now set `TOPSAILAI_PRINT_ENABLED=0` explicitly.
