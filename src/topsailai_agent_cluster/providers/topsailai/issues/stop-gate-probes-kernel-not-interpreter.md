---
maintainer: AI
author: DawsonLin
status: fixed
created: 2026-11-18
---

# The stop capability gate probes the kernel, but the signal is sent by the interpreter

## Symptom

`agent.stop` is advertised by this Provider, admitted by the Endpoint, confirmed by the operator, and
then always fails with:

```text
error_code: safe_signal_unsupported
exit_code: 3
message: No exact verified session target
```

The failure is fail-closed, so nothing unsafe happens, but the capability is unusable on a host where
the descriptor claims it works.

## Root cause

The gate and the work disagree about which layer decides whether a safe signal is possible.

The gate probes the **kernel**:

- `platform_linux.go:15` declares `sysPidfdOpen = 434`.
- `platform_linux.go:39` `pidfdAvailable` calls that syscall for the Provider's own PID and reports
  `PidfdAvailable` from the result.
- `platform_linux.go:51` `probePlatformCapabilities` stores it once at startup.
- `mutation.go:45` `operationNeedsStopSupport` drops `agent.stop` only when
  `platform.stopSupported()` is false.

The signal is delivered by the **Python business CLI**, which needs the Python-level bindings rather
than the raw syscall:

- `cli/cli_topsailai/workspace_kill_cli.py:142` `_signal_bound` reads `os.pidfd_open` and
  `signal.pidfd_send_signal`.
- `cli/cli_topsailai/workspace_kill_cli.py:147` raises
  `WorkspaceKillError("safe_signal_unsupported")` when either is absent.

On the affected host the kernel supports the syscall and the interpreter does not expose it, so the
gate passes and the CLI fails.

## Evidence

Kernel probe succeeds, so the gate advertises the operation:

```text
syscall434 errno=errno 0 fd=3
close=<nil>
```

The deployed Provider advertises `agent.stop`:

```text
agent.stop advertised: True
total ops: 10
```

The interpreter the launcher selects does not expose the bindings:

```text
exe /TopsailAI/.venv/bin/python3
version 3.13.7 (main, Sep 18 2025, 19:47:49) [Clang 20.1.4 ]
os.pidfd_open MISSING
signal.pidfd_send_signal MISSING
```

`bin/topsailai` dispatches through `uv run`, which resolves to that venv
(`/home/topsail/.local/share/uv/python/cpython-3.13.7-linux-x86_64-gnu/bin/python3.13`). `UV_NO_DEV`
is not set in `conf/`, so the `python` fallback is never taken, and the host Endpoint's `PATH` puts
`/TopsailAI/.venv/bin` first.

Calling the real function under that interpreter reproduces the exact error:

```text
raised WorkspaceKillError: safe_signal_unsupported
```

The same host has an interpreter that works, so this is an interpreter choice rather than a platform
limitation:

```text
/usr/bin/python3.9 | 3.9.5 | pidfd=True True
```

## Why the gate cannot detect this

The gate is a Go process probing its own kernel. It has no visibility into which interpreter the
configured provider executable will use, and that executable is a shell launcher that selects an
interpreter at run time. A kernel-level probe is therefore structurally unable to answer the question
the gate is asking.

`platform_gate_test.go` cannot catch it either: every case injects a `platformCapabilities` value, so
the tests prove the gate is narrow and correctly wired, never that the probe agrees with the component
that performs the work.

## Impact

`agent.stop` is the only way to terminate an agent through the cluster. On the affected host it is
advertised, admitted and confirmed, then always fails, so the operator learns about the gap only after
the operation was authorised.

Scope is per host, not per fleet. The two container Endpoints expose the bindings
(`ai-dev` 3.13.9, `topsailai-dev` 3.13.10, both `pidfd True True`), so only the host Endpoint
`ac.topsail` is affected.

## Suggested direction

The gate must probe the same layer that performs the work. Options, in order of preference:

1. Report the stop capability from the component that sends the signal, and intersect it with the
   kernel probe. The performing component is the only one that can answer truthfully. This keeps the
   kernel probe as a necessary condition and adds the missing sufficient one.
2. Pin the provider executable to an interpreter that exposes the bindings, and assert that capability
   in the launcher before dispatch, so a wrong interpreter is a startup failure rather than a
   per-command failure.
3. If a documented residual race is acceptable for this operation, mirror the fallback that
   `cli/cli_topsailai/agent_launch_terminal.py:110-140` already implements for owned processes,
   instead of hard-failing.

Whichever option is chosen, the gate must be verified on the real deployment path: run the configured
executable the way the launcher runs it, and confirm the advertised set matches what the operation
actually does.

Resolved on 2026-11-18 by a fourth option that supersedes the three above: the gate now requires only
what makes the operation impossible, and the binding actually used is reported per invocation. The
performing component still answers truthfully, but through the receipt rather than through the
capability set, so a weaker binding no longer removes the capability. See "Gate relaxed" below.

## Related defect in another project

The failure message is wrong, and that defect belongs to the TopsailAI business CLI, not to this
module. `cli/cli_topsailai/workspace_kill_cli.py:203` passes one fixed message for every
`WorkspaceKillError`:

```python
emit_failure("kill", 3, str(error), "No exact verified session target", ...)
```

`safe_signal_unsupported` is raised at line 147, after `_resolve_target` already succeeded, so the
target was found, live and generation-matched. The message states the opposite of what happened and
sends the investigation to target selection and generation mapping instead of to the interpreter. It
should be derived from the error code rather than fixed for the branch.

## Status

Partially fixed by `ca449595` (business CLI, Python only). The Go gate in this project is unchanged.

### Fixed in the business CLI

`ca449595` removed the hard failure and the misleading message:

- `_signal_bound` now falls back to `os.kill` after re-verifying the process identity, and returns
  the binding it actually used (`pidfd` or `identity_recheck`).
- The receipt carries `binding`, so a weaker guarantee is never presented as the stronger one.
- `_KILL_ERROR_MESSAGES` derives the message from the error code, so a capability gap is no longer
  reported as a target-selection failure.
- `_kill_failure_exit_code` returns `5` for `safe_signal_unsupported`, separating an environment
  capability gap from a target rejection (`3`).

Verified on the real pidfd-less interpreter (`/TopsailAI/.venv/bin/python3`, 3.13.7):

| Case | Result |
|---|---|
| Real child, correct identity | `binding=identity_recheck`, child exit `-15` |
| Wrong generation | `generation_mismatch`, exit `3`, child survived |
| Dead target | `target_not_alive`, exit `3` |
| Real `topsailai` launcher | exit `0`, `binding=identity_recheck`, child exit `-15` |

### Gate relaxed: the decision and its evidence

The human chose direction 1 on 2026-11-18, wording normalized, meaning preserved:

> Relax the gate. A capability claim must reflect whether the operation can be done, not whether it can
> be done in the best way.

`stopSupported()` now requires only a readable process table. `PidfdAvailable` is still probed and
carried, but as evidence of the binding strength the host offers rather than as a precondition. The
binding actually used is reported per invocation in the receipt, so a consumer can distinguish
`pidfd` from `identity_recheck` without the capability set encoding every strength.

The rule is now a contract rule, not a local decision. It is stated in
`docs/agent-cluster-protocol.md` under "A capability claim describes reachability, not the strongest
available guarantee", and `docs/agent-cluster-adapters.md` points at it from the platform-distinction
paragraph with `agent.stop` as the worked example.

Verification of the relaxed gate:

| Check | Result |
|---|---|
| `make test-provider-topsailai` | `ok` |
| Gate broken back to `ProcAvailable && PidfdAvailable` | 3 tests fail, including `TestAgentStopRunsOnAHostWithoutPidfd` |
| Gate restored | `ok` again |

The deliberate break is the evidence that matters. A green suite proves the tests pass; only the broken
build proves they can distinguish the two gates. The three failures were
`TestAgentStopIsAdvertisedOnlyWhereTheHostCanStop`, `TestAgentStopRunsOnAHostWithoutPidfd` and
`TestStopSupportedRequiresOnlyTheProcessTable/process_table_only`.

`TestAgentStopRunsOnAHostWithoutPidfd` is the regression test for this issue. It asserts that a host
which can only re-verify the identity both advertises `agent.stop` and reaches the kill call, so a gate
that advertises without serving, or serves without advertising, fails.

### What remains outside this project

The misleading message was a defect in the TopsailAI business CLI, not here, and it is fixed there by
`ca449595`. This project never read the CLI exit code, so the new exit code `5` needed no change here.
