# Issue: Manager violates role constraints and loops on invalid tool calls

## Status

**undo / open**

## Summary

The manager (`AIManager.DawsonLin`) violated its "Router and Coordinator" role by directly invoking tools instead of delegating tasks to member agents. This produced a loop of 14 consecutive invalid calls to `skill_tool-call_skill`, all failing with the same root cause.

The manager did **not** lack delegation capability: `ai_team_tool-call_agent` was available and had already been used successfully earlier in the session. The problem is that the manager launcher also granted the manager `skill_tool`, and nothing prevented the manager from using it.

## Location

- Session events file: `/root/.topsailai/workspace/task/20260726T143201.1959415.session.events`
- Role: `AIManager.DawsonLin`
- Manager launcher: `/work/ai_team/ai-team`
- `ai_team_tool` plugin: `/work/ai_team/__plugins/ai-team-4-topsailai/ai_team_tool.py`

## Observed Behavior

The manager attempted to execute a shell command by calling `skill_tool-call_skill` with these parameters:

- `skill_folder`: `/root/.topsailai/skill/topsailai_data`
- `script_path`: `/bin/sh`
- `script_parameters`: `["-c", "cat /TopsailAI/src/topsailai/ai_base/llm_base.py | head -n 120"]`

This call was repeated 14 times between `08:40:18` and `08:40:59`.

### Errors

- 12 times: `[Errno 2] No such file or directory: '/root/.topsailai/skill/topsailai_data/bin/sh'`
- 2 times: `error parameter 'environ': it should be JSON and MAP format`

## Tool Configuration Context

`ai_team_tool` is implemented as an external plugin, not as part of the core `topsailai` package:

- Plugin directory: `/work/ai_team/__plugins/ai-team-4-topsailai/`
- Main module: `/work/ai_team/__plugins/ai-team-4-topsailai/ai_team_tool.py`
- It is loaded via `TOPSAILAI_PLUGIN_TOOLS`.

The manager launcher `/work/ai_team/ai-team` sets:

```bash
TOPSAILAI_PLUGIN_TOOLS='${CWD}/__plugins/ai-team-4-topsailai' \
TOPSAILAI_ENABLED_TOOLS='story_memory_tool;ai_team;skill_tool;${TOPSAILAI_ENABLED_TOOLS};${ENABLED_TOOLS}' \
  ai_team ...
```

This means the manager process explicitly enables:

- `story_memory_tool`
- `ai_team` (including `ai_team_tool-call_agent`)
- `skill_tool`
- Any additional tools the caller passed via environment variables

In contrast, when the manager delegates to a member via `call_agent`, the member process is configured with `TOPSAILAI_ENABLED_TOOLS=""` and `TOPSAILAI_DISABLED_TOOLS="ai_team;..."`, giving the member access to all core tools except `ai_team` tools.

So the manager is granted `skill_tool` by launcher configuration, while the role documentation says the manager must only route and delegate.

## Root Cause

Three failures occurred simultaneously:

1. **Launcher configuration contradicts role docs**: The manager launcher enables `skill_tool` for the manager, but `ai_team/ai_team_manager.md` and `ai_team/ai_team_manager_only_agent.md` state that the manager must only invoke `call_agent`. The tool set should match the role constraint.
2. **Role violation**: The manager tried to perform work itself instead of using `call_agent` to delegate to a member. Managers should only route and coordinate.
3. **Wrong tool choice**: The manager used `skill_tool-call_skill` to run a shell command. This tool resolves `script_path` relative to `skill_folder`, so it attempted to execute `/root/.topsailai/skill/topsailai_data/bin/sh`, which does not exist. The correct tool for arbitrary shell commands is `cmd_tool-exec_cmd`.

After the first failure, the manager repeated the same malformed call instead of switching tools or delegating.

## Impact

- Wasted 14 tool calls and corresponding LLM turns.
- Delayed task progress.
- Polluted the session events file with repeated identical errors.
- Demonstrated that current safeguards do not prevent a manager from executing tools or looping on failures.

## Recommended Fixes

### Launcher configuration

- **Rejected**: Remove `skill_tool` from the manager's `TOPSAILAI_ENABLED_TOOLS` in `/work/ai_team/ai-team`. The manager needs `skill_tool` to load skill overviews and context as a routing aid; removing it would leave the manager without necessary context.
- **Rejected**: Explicitly disable execution tools for the manager via `TOPSAILAI_DISABLED_TOOLS`. Same reason as above; the manager legitimately uses informational tools such as `skill_tool-overview_skill` and `skill_tool-read_skill_file`.
- Keep `ai_team` enabled so the manager can delegate via `call_agent`.

### Tool-level enforcement

- **Accepted**: Add a runtime guard in `ai_team_tool-call_agent` or a manager-specific wrapper that intercepts execution-oriented tool calls from the manager role and returns an error reminding the manager to delegate. The guard should allow read-only/informational calls (for example `skill_tool-overview_skill`, `skill_tool-read_skill_file`, `file_tool-read_file`) while blocking calls that execute commands or mutate state (for example `skill_tool-call_skill` with an executable script path, `cmd_tool-exec_cmd`, `file_tool-write_file`, `sandbox_tool`).
- **Accepted**: Improve `skill_tool-call_skill` validation: when `script_path` is an absolute path like `/bin/sh`, return a guiding message that explains the path must be relative to the skill folder and reminds the manager to use `call_agent` for arbitrary command execution.
- **Accepted**: Validate the `environ` parameter format before execution and return a clear, actionable error message instead of a raw format failure.

### Prompt-level

- **Accepted**: Strengthen the manager system prompt to clarify that `skill_tool` is read-only/informational for the manager. Any action that reads files, runs commands, writes code, or runs tests must be delegated to a member via `call_agent`.
- **Accepted**: Add a failure-handling rule: "If a tool call fails, do not repeat the same call. Switch tools, delegate to a different member, or report the blocker to the user."

### Process-level

- **Rejected**: Introduce a fail-fast or reflection step after two consecutive identical tool failures. The user considers fail-fast uncertain and prefers guidance over termination.
- **Accepted**: Add an event-based alert: if the manager emits the same tool error more than twice in a row, flag the session for review.
- **Accepted**: Record this incident in `LEARN.md` under a manager-constraint lesson once the safeguards are implemented.

## Refined Plan

After discussion, the following approach is agreed upon. The goal is to keep `skill_tool` available to the manager for context and routing information, while preventing execution-oriented misuse and guiding the manager back to delegation.

### Rejected Approaches

- **Removing `skill_tool` from the manager tool set**: Rejected because the manager needs skill overviews and related context to route tasks effectively. `skill_tool` is legitimate for read-only/informational use.
- **Fail-fast termination after repeated failures**: Rejected because termination is considered uncertain and may interrupt legitimate recovery paths. Guidance is preferred over hard stops.

### Accepted Approaches

#### Strengthen the manager system prompt

Clarify the manager's relationship with tools:

- The manager is a router and coordinator.
- `skill_tool` may be used only for reading skill information (for example `skill_tool-overview_skill`, `skill_tool-read_skill_file`).
- Any action that reads project files, runs commands, writes or modifies files, runs tests, or performs other execution work must be delegated to a member agent via `call_agent`.
- If a tool call fails, the manager must not repeat the same call. It should switch tools, delegate to a different member, or report the blocker to the user.

#### Implement a manager tool guard

Add a runtime guard that inspects manager tool calls before execution:

- Allow read-only/informational calls such as `skill_tool-overview_skill`, `skill_tool-read_skill_file`, and `file_tool-read_file`.
- Block execution-oriented or state-mutating calls such as:
  - `skill_tool-call_skill` when `script_path` points to an executable script or absolute system path
  - `cmd_tool-exec_cmd`
  - `file_tool-write_file` and related write/replace operations
  - `sandbox_tool`
  - any other tool whose primary purpose is execution or mutation
- When a call is blocked, return a clear message: "Managers may not execute commands or mutate state directly. Please delegate this action to a member agent via `call_agent`."

#### Improve `skill_tool-call_skill` parameter error responses

When the manager (or any caller) provides invalid parameters to `skill_tool-call_skill`, the error response should be actionable and, for the manager role, redirect toward delegation:

- If `script_path` is an absolute path, respond with a message explaining that `script_path` must be relative to `skill_folder` and that arbitrary command execution should be delegated via `call_agent`.
- If `environ` is not valid JSON or not a map, respond with a concise format explanation.
- The error message itself should serve as a reminder of the correct workflow.

### Implementation Order

1. Draft the updated manager system prompt and review it against existing manager role documents in `/work/ai_team`.
2. Design the manager tool guard. Decide whether it lives in the `ai_team_tool` plugin, in a manager-specific wrapper, or in the core tool dispatch layer.
3. Update `skill_tool-call_skill` validation and error messages in `/TopsailAI/src/topsailai/tools/skill_tool.py`.
4. Add or update unit tests for the guard and the improved error messages.
5. After implementation, record the lesson in `LEARN.md`.

## Notes

- No code fix implemented yet.
- The issue is recorded for future process and safeguard improvements.

---

**Author:** DawsonLin
