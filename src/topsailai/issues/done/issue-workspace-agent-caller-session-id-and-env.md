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

# Issue: `topsailai workspace agent` cannot accept a caller-fixed session id or caller-supplied launch environment

## Status

Resolved by commit `c6bda273` (`feat: add caller-fixed session identity and env overrides
to workspace agent`). This record was written as analysis only; the implementation landed
separately and is verified below. No file outside this project was modified.

## Boundary decision that produced this issue

An external consumer (the WeChat bridge) is allowed to use only the unified `topsailai`
CLI. It must not read internal modules, FIFOs, PID files, or the process tree. That
boundary is correct and is not being questioned here. The consequence is that every
capability the bridge needs must be reachable through a documented public CLI contract,
and two of those capabilities are currently missing.

## Symptom

A background launch is started with the caller's identity already exported:

```text
topsailai workspace agent -b --json --non-interactive \
  --driver topsailai_agent_chats /work/topsailai-weixin/workspace
```

with `TOPSAILAI_SESSION_ID=bot-weixin`, `SESSION_ID=bot-weixin`,
`TOPSAILAI_INTERACTIVE_MODE=0`, `TOPSAILAI_PRINT_ENABLED=1`,
`TOPSAILAI_INPUT_PIPE_ENABLED=1`, `TOPSAILAI_CHAT_MULTI_LINE=1` in the environment.

The launch succeeds and `topsailai runtime send` works, but the agent runs under a
CLI-minted identity `wa-0e7642c1ef8c` instead of the requested `bot-weixin`. The caller
therefore cannot address the agent by a stable name, and every restart produces a new
identity.

Observed artifacts for that launch:

```text
/root/.topsailai/workspace/task/wa-0e7642c1ef8c.3650037.session.meta
/root/.topsailai/workspace/task/wa-0e7642c1ef8c.3650037.session.stdout
/root/.topsailai/workspace/task/wa-0e7642c1ef8c.3650037.session.events
/root/.topsailai/workspace/task/wa-0e7642c1ef8c.3650037.session.stats.jsonl
/root/.topsailai/workspace/task/wa-0e7642c1ef8c.agent-launch.log
```

The metadata records `session_name: WECHAT_CLI_OK`, `status: completed`,
`project_workspace: /opt/git/ai/lindongsen/work/topsailai-weixin/workspace`,
`hostname: topsail`. The workspace path is correct, so the folder argument is not the
problem; only the identity is.

## Root cause

### The public parser exposes no identity option

`cli/cli_topsailai/workspace_agent_cli.py:37` builds the parser, and its options are
`folder`, `-m/--agent-mode`, `-b/--background`, `--json`, `--task`,
`--non-interactive`, `--driver`. There is no `--session-id` and no environment option.

Measured:

```text
RESULT --session-id REJECTED exit 2
RESULT --env REJECTED exit 2
```

Both call sites of `launch_configured_agent` in `run_workspace_agent_cli`
(`workspace_agent_cli.py:157` and `:171`) pass `mode`, `background`,
`entrypoint_base`, `non_interactive`, and optionally `task`/`launcher_driver`. Neither
passes `session_id`, so the identity is always minted.

### The identity is minted because nothing supplies one

`cli/cli_topsailai/agent_launch.py:211` reads:

```text
session_id = resumed_session or _session_id()
```

`_session_id()` (`agent_launch.py:27-35`) returns `f"wa-{uuid.uuid4().hex[:12]}"`.
Measured: `minted: wa-3a1d01a4d85f`, `has dot: False`.

`_prepare_environment()` (`agent_launch.py:38-54`) then writes
`TOPSAILAI_SESSION_ID` and `SESSION_ID` from that argument. This function is **not** the
defect: a probe that called it with `bot-weixin` left both variables at `bot-weixin`.
It faithfully applies whatever identity it is handed, and it is handed a minted one.

### The capability already exists one layer down

`launch_configured_agent` already accepts `session_id` (`agent_launch.py:93-103`), and
`launcher_command` (`agent_launch_command.py:33-35`) forwards it to the launcher:

```text
fresh : ['topsailai_launch_agent', '--subprocess', '--session-id', 'bot-weixin', '--driver', 'topsailai_agent_chats']
resume: ['topsailai_agent_chats']
```

The launcher declares `--session-id` (`topsailai_launch_agent.py:2332-2335`), validates
it at `:2459-2460` against `[A-Za-z0-9_.-]{1,128}`, and applies it at `:2723-2729` to
both `merged_env` and `os.environ`.

So the gap is confined to the public CLI layer, plus one contract ambiguity described
below. This is a missing public contract, not a missing mechanism.

### The internal parameter conflates "resume" with "fixed identity"

`launch_configured_agent`'s docstring (`agent_launch.py:106-107`) states that a supplied
`session_id` "resumes that persisted identity". The implementation does not actually
require a persisted session: with `driver=None` it builds a **fresh** launcher argv that
carries `--session-id`, which is exactly the capability the bridge needs. The name and
documented meaning therefore describe only the resume use, and a future reader could
reasonably reject a fresh launch with a caller-fixed id as unsupported. The contract must
separate "resume an existing session" from "start a fresh session under a caller-chosen
identity".

### Caller environment is overridden by settings.yaml

`topsailai_launch_agent.py:2715-2717` merges in this order:

```text
merged_env = os.environ.copy()
merged_env.update(base_env)
merged_env.update(item_env)
```

`_get_base_env` (`:283-293`) applies `_default` then `_`, and `env_map` is
`settings["environment"]` (`:2510`). Measured with the caller exporting `0` and the
settings base section holding `1`:

```text
caller=0, settings _=1 -> child: 1
```

The current `/work/topsailai-weixin/.topsailai/settings.yaml` sets
`environment._.TOPSAILAI_INTERACTIVE_MODE: "0"`, so today the values happen to agree.
That is a coincidence of the current file, not a guarantee: any settings value silently
wins over the caller's export, and the caller has no CLI-level way to state a value that
must take precedence. The bridge needs `TOPSAILAI_INTERACTIVE_MODE`,
`TOPSAILAI_PRINT_ENABLED`, `TOPSAILAI_INPUT_PIPE_ENABLED`, and
`TOPSAILAI_CHAT_MULTI_LINE` to be deterministic regardless of the target project's
settings file.

## Why `workspace resume` is not a workaround

`workspace resume` requires an already-persisted session and maps a missing one to
`session_not_found` through `RESUME_ERROR_CODES` (`workspace_resume_cli.py:129`). It
cannot bootstrap a fixed identity for a first launch, so it does not satisfy the
requirement.

## Documented contract today

`cli/docs/usage/topsailai.md:804`, `:838`, and `:845`, plus
`cli/cli_topsailai/help_text.py:273-275`, describe `workspace agent` with no identity
option and no environment option. The gap is therefore a genuine public contract gap,
not a documentation omission.

## Required contract

### Fixed session identity

`topsailai workspace agent` must accept a caller-chosen session id, for example
`--session-id <ID>`, and the launched agent must run under exactly that id, with
`TOPSAILAI_SESSION_ID` and `SESSION_ID` both set to it and all session artifacts named
after it.

The value must be validated more strictly than the launcher does. The launcher accepts
dots, but stdout filenames are parsed by splitting on dots
(`agent_launch.py:30-33`, `session_info_format.py:79`, `log_files.py:121/138/159`), so a
dot-containing id would be misparsed by every reader. The CLI must reject a dot and
report a usage error instead of forwarding a value that breaks later parsing.

### Explicit launch environment

The CLI must accept caller-supplied environment variables for the launched agent, for
example a repeatable `--env KEY=VALUE`, and those values must take precedence over
`settings.yaml`. The precedence order must be documented, and the caller must be able to
rely on it without editing the target project's settings file.

### JSON receipt

The existing receipt field set (`workspace_receipt.py:68-83`) must report the identity
that was actually used, so a caller can verify the request was honored rather than
inferred. `session_id` already exists in the receipt; it must carry the caller's value on
success and must not silently report a minted one.

### Parameter validation

Invalid identity and malformed environment entries must fail closed with exit code `2`
(`usage_error` in `AGENT_ERROR_CODES`, `workspace_receipt.py:28-35`) and a receipt that
names the offending parameter. Validation must happen before any process is spawned, so a
rejected request leaves no partial launch behind.

### Conflict handling

The contract must define what happens when a caller-fixed identity already exists: an
active session, a completed session, or leftover artifacts. The behavior must be explicit
and observable rather than an implicit overwrite or an implicit resume, and it must not
destroy another live session's evidence.

### Tests

Coverage must include: a fixed id reaching the child environment and the artifact names;
rejection of an invalid or dot-containing id before spawn; `--env` precedence over
`settings.yaml`; the receipt reporting the honored identity; and each conflict case.

## Out of scope

- No change to the WeChat bridge, and no file under `/work/topsailai-weixin` may be
  modified.
- No weakening of the CLI-only boundary; the fix must not require the bridge to read
  internal modules, FIFOs, PIDs, or the process tree.
- No implementation in this record.

## Evidence provenance

Every claim above was verified in this session by reading the cited source or by running
the quoted probe. Two earlier assumptions were falsified by those probes and are recorded
here so they are not repeated: `_prepare_environment` does not overwrite a supplied
identity, and the current settings file sets `TOPSAILAI_INTERACTIVE_MODE` to `"0"`, not
`"1"`. The precedence defect is real but is demonstrated by the merge order and the
`caller=0, settings _=1 -> child: 1` probe, not by the current settings content.

## Resolution

Resolved by commit `c6bda273` (`feat: add caller-fixed session identity and env overrides
to workspace agent`), which changed 18 files under `cli/`. The capabilities this issue
asked for are implemented as follows, each verified by reading the cited source in this
session.

### Caller-fixed identity

`cli/cli_topsailai/launch_parameters.py::validate_session_id()` rejects a non-string, an
empty value, a value longer than 128 characters, a value outside `[A-Za-z0-9_-]`, and any
value containing a dot. The dot rule is stricter than the launcher's own rule and is
deliberate: every stdout filename reader splits the name on dots, so a dot-containing
identity would be misparsed by the whole workspace layer.

`cli/topsailai_launch_agent.py:2755-2760` applies the caller's identity to both
`TOPSAILAI_SESSION_ID` and `SESSION_ID` in the child environment and in the launcher's own
environment, so the two spellings cannot disagree.

### Caller-supplied environment

`parse_env_overrides()` accepts repeatable `KEY=VALUE` entries, preserves a deliberately
empty value, rejects an entry without `=`, rejects a malformed name, rejects a repeated
name with a conflicting value, and rejects the two identity aliases with the message
`--env must not set <name>; use --session-id instead`.

Precedence is explicit at `cli/topsailai_launch_agent.py:2738-2740`:

```python
merged_env = os.environ.copy()
merged_env.update(base_env)
merged_env.update(item_env)
merged_env.update(env_overrides)
```

The caller's value is applied last, so it outranks the target project's `settings.yaml`
regardless of that file's content. One documented exception exists: the resolved agent
driver wins over a caller-supplied `TOPSAILAI_AGENT_DRIVER`, because the child must
advertise the driver that is really running.

### Conflict handling

`cli/cli_topsailai/workspace_agent_cli.py::_identity_conflict()` refuses a `live` identity
(`Session <id> is already running`) and an `unknown` one (`liveness cannot be verified`),
returning exit code 4. An idle identity is allowed, because its artifacts are per-PID, so a
fresh launch under the same name never overwrites the previous run's evidence. The check
runs twice: once before preparation and again at the launch boundary through
`prelaunch_check`, so a session that started in between is still protected.

### Receipt

`_receipt_response()` publishes `env_overrides` as a sorted list of variable **names**
only, never their values, so a caller can confirm which variables it set without the
receipt disclosing them. The honored identity is published as `session_id`.

### Validation before spawn

Both parameters are validated inside the `try` block that precedes
`launch_configured_agent()`, so a rejected request returns exit code 2 with
`usage_error` and leaves no partial launch behind.

### Verification

`cli/tests/unit/topsailai/test_workspace_agent_cli.py`,
`cli/tests/unit/topsailai/test_launch_parameters.py`, and
`cli/tests/unit/topsailai_launch_agent/test_launch_env.py` were run in this session:

```text
115 passed in 2.88s
```

These cover a fixed id reaching the child environment and the artifact names, rejection of
an invalid or dot-containing id before spawn, `--env` precedence over `settings.yaml`, the
receipt reporting the honored identity and env names, and each conflict case.
