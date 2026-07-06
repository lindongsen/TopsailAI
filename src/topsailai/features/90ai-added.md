---
maintainer: AI
workspace: /TopsailAI/src/topsailai
ProjectFolder: /TopsailAI/src/topsailai
ProjectRootFolder: /TopsailAI
ProjectCode: TOPSAILAI
programming_language: python
---

# AI-Added Features

## Context User Messages

Added an agent-dimension `context_user_messages` list to `PromptBase` that is seeded from `TOPSAILAI_CONTEXT_USER_MESSAGE` (file path or raw text). When non-empty, the items are combined into a single user message using the `---\n<content>\n---` separator format and injected at the start of each session via `new_session()`. The `_build_context_message()` helper is role-agnostic so future `context_xxx_messages` (e.g. `context_assistant_messages`) can reuse the same formatting logic. `reset_messages()` preserves `context_user_messages` because it is agent-dimension state.

## Duplicate Tool-Call Detection

Implemented infrastructure to detect consecutive duplicate tool calls in the agent ReAct loop. The purpose is to catch accidental or model-induced repeated invocations of the same tool with the same arguments, which can waste tokens, trigger rate limits, or loop forever.

Key logic:
- `ToolStat._normalize()` serializes tool arguments deterministically (sorted dict keys, sorted sets, stable list/tuple handling) so semantically identical calls produce identical signatures.
- `ToolStat.is_last_call_duplicate()` compares the most recent recorded call with the previous one using the normalized signature.
- `get_agent_tool_stat()` retrieves the `ToolStat` instance bound to the current agent via thread-local storage, ensuring per-agent isolation instead of sharing a global counter.
- `record_tool_call()` now routes through the agent-bound `ToolStat` so duplicate detection is scoped to the active agent.
- `detect_duplicate_tool_call()` decorator is defined and ready to wrap `exec_tool_func()` in `ai_base/agent_types/tool.py`, but is intentionally not applied yet pending human approval.

System impact: Existing behavior is unchanged because the decorator is not wired in. Once applied, duplicate calls will be detectable at execution time, enabling future mitigation such as returning a cached result, emitting a warning, or aborting the loop.

## Input History Rotation

Added size-based rotation for the JSONL input history file (`input_history.jsonl`) so it no longer grows without bound.

Key logic:
- Two new environment variables control rotation: `TOPSAILAI_INPUT_HISTORY_MAX_SIZE` (default 1048576 bytes, i.e. 1 MiB) and `TOPSAILAI_INPUT_HISTORY_MAX_BACKUP` (default 1 backup).
- `append_input_history_jsonl()` checks the current history file size before appending. If the size exceeds the configured maximum, it rotates existing backups and renames the current file to the first backup slot.
- Values below 0 for either variable disable rotation or backup retention respectively.
- Rotation is performed before writing the new entry, so the active history file always stays near or below the configured size.

System impact: Prevents long-running sessions from producing an unbounded `input_history.jsonl`. Existing history is preserved as `.1.jsonl` (and higher indexes up to the backup limit) before truncation.

## Project Workspace Lock

Added a startup lock for the project workspace to prevent multiple agent processes from operating on the same project directory concurrently.

Key logic:
- When `TOPSAILAI_PROJECT_WORKSPACE` is set and `TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED=1` (default), `agent_shell.get_agent_chat()` attempts to acquire a lock at `{TOPSAILAI_PROJECT_WORKSPACE}/.topsailai/project_workspace.lock` during startup.
- `ctxm_project_workspace_lock()` in `workspace/lock_tool.py` creates the `.topsailai` directory if needed, acquires an exclusive lock via `lockf`, and releases it on context exit.
- If the lock is already held, the user is prompted via `input_from_pipe_session` with three choices: `exit`, `continue`, or `wait`.
  - `exit`: terminates the process with status code 1.
  - `continue`: proceeds without holding the lock.
  - `wait`: blocks and retries until the lock becomes available.
- If the prompt times out, the default action is `wait`. The timeout is controlled by `TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT` (default 300 seconds).

System impact: Two new environment variables are introduced: `TOPSAILAI_PROJECT_WORKSPACE_LOCK_ENABLED` and `TOPSAILAI_PROJECT_WORKSPACE_LOCK_TIMEOUT`. Existing behavior is preserved when the project workspace is unset or locking is disabled. Concurrent agent sessions targeting the same project workspace are now serialized unless the user explicitly chooses to continue without the lock.

## SSH Agent Tool

Added a new agent tool `ssh_tool` for remote command execution and file transfer over SSH.

Key logic:
- Single entry point `operate_ssh(action, host, **kwargs)` uses a factory pattern with `_OPERATORS = {"exec": SSHExecOperator, "scp": SSHScpOperator, "rsync": SSHRsyncOperator}` so new SSH operations can be added without changing the public API.
- `SSHContext` normalizes connection parameters: host, port, username (default `"root"`), private key, SSH options, and timeout.
- Default SSH options are safe for automation: `StrictHostKeyChecking=no`, `UserKnownHostsFile=/dev/null`, `ConnectTimeout=10`, `ConnectionAttempts=3`, `LogLevel=ERROR`.
- `SSHExecOperator` executes commands on remote hosts; localhost is detected and runs the command locally without SSH.
- `SSHScpOperator` and `SSHRsyncOperator` copy files or folders to/from remote hosts and support Dockerfile-style trailing-slash semantics:
  - target ends with `/`: copy the source directory itself into the target directory.
  - target does not end with `/`: copy source contents to the target path, preventing nested same-name folders.
- `rsync` supports an opt-in `delete=True` flag instead of enabling `--delete` by default.
- Remote commands are built as argument lists and passed to `exec_cmd` with `shell=False` to avoid shell injection; remote paths are quoted with `shlex.quote`.
- The tool is auto-registered via module discovery in `tools/base/init.py` as `ssh_tool-operate_ssh`.

System impact: Agents can now run commands and transfer files over SSH using a unified, extensible interface.
