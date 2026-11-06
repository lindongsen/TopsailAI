---
maintainer: AI
author: DawsonLin
---

# Endpoint PATH could not resolve the provider launcher

## Trigger

Human report (verbatim):

> 这个执行失败了，分析原因：
> command submitted: cli-1793973751709310440; use status cli-1793973751709310440 to query
> CommandID: cli-1793973751709310440
> Status: executing
> DeliveryBoundary: not_started
> EffectCertainty: unknown
> ErrorCode: provider_failed

The command was an `agent.start` submitted to endpoint `ai-dev` with
`launch_profile_id=topsailai-ai-dev`, `folder=/TopsailAI/src/topsailai_agent_cluster` and a literal task.

## Observed behavior

The Server row recorded `status=executing`, `phase=receipt_recorded`, `delivery_boundary=not_started`,
`effect_certainty=unknown` and the receipt
`{"outcome":"failed","error_code":"provider_failed","error_message":"run TopsailAI command: exit status 5","exit_confirmed":false}`.
The endpoint log recorded the same message twice, at 22:01:31 and 22:02:33. Both launch logs
(`wa-38199450d613`, `wa-586681ceaf45`) were zero bytes, so no agent was ever started.

## Root cause

The provider CLI was invoked correctly and failed while spawning its own launcher, because the endpoint
process environment could not resolve the launcher executable by name.

1. The adapter invokes the configured absolute executable
   `/TopsailAI/src/topsailai/bin/topsailai`, which is a bash wrapper that `exec`s
   `uv run cli/topsailai_cli.py`. The wrapper does not extend `PATH`.
2. `cli_topsailai/agent_launch_command.py` builds the launcher argv as the bare name
   `topsailai_launch_agent`, and `agent_launch_background.py` spawns it with `Popen(command, cwd=folder,
   env=os.environ)`, so the name is resolved through the inherited `PATH`.
3. The `ai-dev` endpoint process inherited
   `PATH=/root/.cargo/bin:/ai/bin:/usr/local/bin:/usr/local/sbin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/gopath/bin`,
   which does not contain `/TopsailAI/src/topsailai/bin`, and the project virtualenv
   (`/TopsailAI/.venv/bin`) does not provide a `topsailai_launch_agent` console script.
4. `Popen` therefore raised `FileNotFoundError: [Errno 2] No such file or directory:
   'topsailai_launch_agent'`, which `agent_launch.py` maps to exit code 5, and
   `workspace_receipt.AGENT_ERROR_CODES[5]` names `spawn_failed`.

Differential evidence: the `local-endpoint` process has
`PATH=...:/TopsailAI/src/topsailai/bin:...` and every `agent.start` it received reached
`status=finished` with `delivery_boundary=submitted`; the `ai-dev` endpoint lacks that directory and both
of its `agent.start` commands failed with exit 5.

Reproduction inside the endpoint mount namespace, same argv, only `PATH` varied:

| PATH | Result |
|---|---|
| endpoint `PATH` (no provider bin dir) | `exit_code=5`, `error_code=spawn_failed`, `delivery_state=not_delivered` |
| endpoint `PATH` prefixed with `/TopsailAI/src/topsailai/bin` | `exit_code=0`, `delivery_state=submitted`, launcher pid assigned |

The argv, the folder, the task payload and the provider executable were therefore all correct; only the
child-process `PATH` differed.

## Contributing defect: the real provider error was discarded

`internal/adapter/topsailai/runner.go` uses `cmd.Output()`, which discards the provider's stderr, and
`internal/adapter/topsailai/adapter.go` replaces the provider receipt with a generic
`failedReceipt(intent, "provider_failed")` whenever the exit status is non-zero. The provider had already
emitted a machine-readable receipt containing `error_code=spawn_failed`,
`delivery_state=not_delivered` and the exact `OSError` message, and all of it was thrown away. The
operator therefore saw `provider_failed` with no cause, and the diagnosis required manual reproduction.

## Contributing defect: wrong terminal status

Because the adapter reports `effect_certainty=unknown` for every provider failure, the Server mapped the
command to `status=executing` (`internal/storage/server/command_queries.go`) and later converged it to the
terminal `unconfirmed` state. Nothing was delivered, so the honest state is `not_applied` and the command
should have been reported as rejected/failed. The provider's own `delivery_state=not_delivered` was
available and discarded, so the operator is told that effects are uncertain when they are provably absent.

## Resolution

Implemented in `internal/adapter/topsailai/runner.go`. Every provider invocation passes through
`execRunner.Run`, which now sets an explicit child environment:

```go
cmd.Env = providerEnvironment(executable, os.Environ())
```

`providerEnvironment` derives the directory from the configured executable
(`filepath.Dir(executable)`) and puts it first on `PATH`, preserving every other inherited variable.
`prependPath` is idempotent, so a directory already present is not duplicated, and a relative
executable leaves the environment untouched. Deriving the directory from the configured executable
rather than hardcoding `/TopsailAI/src/topsailai/bin` keeps the fix portable across sites while
guaranteeing that directory is present for the current deployment.

Verification evidence:

| Check | Result |
|---|---|
| `gofmt -l` on both changed files | no output |
| `go vet ./internal/adapter/topsailai/` | exit 0 |
| `go test ./internal/adapter/...` | `ok` for both packages |
| `go build ./...` | exit 0 |
| Negative control (env injection removed) | `TestExecRunnerResolvesSiblingProviderExecutable` fails with `exit status 1` |
| Shell probe with the `ai-dev` daemon `PATH` | `topsailai_launch_agent` unresolved before the fix, resolved after prepending the provider directory |

Regression tests added in `runner_test.go`: four unit tests for `providerEnvironment`/`prependPath`,
one test pinning the filesystem-root executable case, and one end-to-end test that copies the test
binary into a temporary directory as `provider-main` and a sibling, then spawns the sibling by bare
name under a `PATH` that lacks the directory. The test binary plays both roles, so the test needs no
shell or platform-specific script interpreter.

Remaining open items, tracked separately and not part of this fix:

1. Observability: capture provider stderr in `runner.go` and parse the provider JSON receipt even on a
   non-zero exit, so `error_code`, `message` and `delivery_state` reach the Server instead of
   `provider_failed`.
2. Status semantics: derive `effect_certainty` from the reported delivery state rather than defaulting
   to `unknown`, so a not-delivered failure is reported as `not_applied` instead of
   `executing`/`unconfirmed`.

## Prevention

- A regression test must assert the provider child environment, not only the argv, because a correct argv
  with an unresolvable child name still fails.
- Deployment documentation must state that the endpoint daemon's environment, not the operator's shell, is
  what the provider CLI inherits.
- Any non-zero provider exit must preserve the provider's structured error fields; a generic
  `provider_failed` is not acceptable diagnostic evidence.
