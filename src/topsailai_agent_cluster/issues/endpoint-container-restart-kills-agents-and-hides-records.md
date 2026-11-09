---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Restarting the ai-dev endpoint container kills its agents, and the surviving records are then hidden from `list`

## Trigger

The human reported that endpoint `ai-dev` restarted unexpectedly, that a task inside it never
finished, and that the record still exists but `agent-cluster-cli list` does not show it.

## Symptom

Two sessions launched by the `ai-dev` endpoint are absent from every endpoint's `list` output,
although their files are still on disk:

| Session | Name | Provider PID | stdout size | Last write |
|---|---|---|---|---|
| `wa-7bb879625589` | 数据库IO阻塞或退出策略 | 2105728 | 3,330,373 B | 09:20:52 |
| `wa-6922e9283de2` | CLI session subcommand check | 2265146 | 1,148,820 B | 09:22:13 |

Both `.session.meta` files still record `"status": "running"` and `"end_ts": null`, so the record
claims the session is running while its process no longer exists.

## Verified facts

- `docker inspect ai-dev` reports `StartedAt 2026-11-09T01:22:39Z` (09:22:39 +0800) and
  `RestartCount 0`. The container was recreated, not restarted in place.
- Both `.session.meta` files carry `"hostname": "ai-dev"`, and `docker exec ai-dev hostname`
  returns `ai-dev`, so both sessions were launched inside that container.
- The endpoint process and the agents it launches share one container: `docker exec ai-dev ps`
  shows the endpoint as container PID 89 and the live agents as container PIDs 9009, 9473, 11496
  and 11768.
- PIDs 2105728 and 2265146 are gone in both the host namespace and the container namespace.
- `topsailai workspace --format json` inside `ai-dev` returns 11 items, including both sessions
  with `"process_generation": null`.
- The Server row for `ai-dev` holds 4 sessions; neither session is among them.
- `/root/.topsailai` is a symlink to `/work/hosts/.topsailai`, which resolves to
  `/opt/git/ai/lindongsen/work/hosts/.topsailai`, and `/opt/git/ai` is bind-mounted into the
  container. Both sides therefore read one task directory, so the record is genuinely shared and
  not a second copy.

## Root cause A: the endpoint container is also the agent's parent container

`docs/agent-cluster-architecture.md` states that Endpoint startup, shutdown and restart do not
start, stop, adopt or restart Agents, and that the provider runtime owns Agent lifetime. That
holds only when the Endpoint process and the Agents it launches live in different containers or
in the host namespace.

For `ai-dev` they do not. The endpoint runs as container PID 89 and launches agents as container
children, so recreating the container destroys every agent process in it. The agents were killed
by the container lifecycle, not by any cluster command, and no cluster component recorded that
termination because the provider never wrote an `end_ts`.

## Root cause B: a generation-less session is dropped instead of reported as unknown

`internal/adapter/topsailai/adapter.go:270-274`:

```go
// Workspace history can contain idle records without a provider generation;
// they cannot be addressed safely, so exclude them from routable sessions.
if item.SessionID == "" || generation == "" {
    continue
}
```

The generation comes from `cli/cli_topsailai/core.py:1284-1287`, which sets it only when
`is_process_holding_file(evidence_pid, evidence_path)` is true. A dead process therefore yields
`process_generation: null`, and the adapter drops the whole session.

The drop is silent: no log line, no counter, no `collection_status` degradation. The Server row
simply contains fewer sessions, so the operator sees a shorter list rather than an unknown state.

## Why the drop is wrong for these two sessions

The comment says such records "cannot be addressed safely". That is true for `agent.stop`, which
requires a generation (`internal/adapter/topsailai/adapter.go:421`), but it is false for the
operations that actually matter here:

- `agent.resume` builds `workspace resume -s <providerKey> --background --json`
  (`internal/adapter/topsailai/adapter.go:417-418`) and never reads a generation.
- `message.send` builds `runtime send -s <providerKey> -m=... --json`
  (`internal/adapter/topsailai/adapter.go:384`) and never reads a generation.

So a session whose process is gone is still resumable and still addressable for input, yet it is
removed from the only surface that would let the operator select it. The safety argument protects
`agent.stop` and is applied to every operation.

This also contradicts the design rule that an unavailable observation must be reported as
`unknown/stale` rather than as an empty inventory.

## Impact

- A finished or interrupted task becomes invisible, so the operator cannot resume it or read its
  output through the cluster surface.
- The operator reads the shorter list as "the task is gone", which is the opposite of the truth:
  the record and its 3.3 MB of output are intact.
- The same session is visible through `topsailai workspace list` on the host and invisible through
  `agent-cluster-cli list`, so the two surfaces disagree.

## Human decision

The human decided the direction on 2026-11-09, quoted verbatim:

> 改上报方式，同意你说的，但是 send 也要拒绝，只放开 resume。部署方式，deb 部署的话，安装就好了，不要去重启容器就行了。

So the reporting change is approved, but only `agent.resume` is opened. `message.send` is rejected
exactly like `agent.stop`, because a session whose liveness is unverified must not receive input.
On the deployment side, a deb install is an install only: the container must not be restarted,
because recreating it kills the agents it hosts.

## Implemented fix

The reporting change and the admission change are implemented.

| File | Change |
|---|---|
| `internal/protocol/resources.go` | Added `SessionStateUnknown` and `StateReasonLivenessUnverified` |
| `internal/adapter/adapter.go` | `InspectResult` gained `Live`, separating "the record exists" from "liveness was verified" |
| `internal/adapter/topsailai/adapter.go` | `Discover` reports a generation-less session as `state=unknown` with `state_reason=liveness_unverified` instead of dropping it; `Inspect` returns `Live: generation != ""` |
| `internal/adapter/command.go` | `Inspect` returns `Live: session.Generation != ""` |
| `internal/endpoint/executor.go` | Resume decides on `Live`; every other operation is rejected with `generation_required` before revalidation when the generation is empty |
| `internal/tui/history.go` | `Live` now means "liveness verified"; new `Unverified` marks a visible but unaddressable row; the LIVE cell renders `unverified` |
| `internal/tui/interactive_history.go` | `validateResumeAbsence` refuses only a session with a verified generation, so an unverified row stays resumable; `cd` names the real reason |
| `internal/tui/interactive.go` | A generation-less pinned session reports unverified liveness instead of a generation change |
| `internal/tui/row_selection.go`, `session_target.go`, `navigation.go` | A generation-less row names the unverified reason and the resume recovery step |

Two pre-existing defects had to be fixed for the decision to hold:

- `Inspect` returned `Found: true` for a dead session, and resume used `Found` to mean "still
  active", so resuming a dead session was refused with `target_still_active`.
- `revalidateGeneration` compared `session.Generation != target.Generation`, which is false when
  both are empty, so a generation-less `message.send` passed validation and reached the provider.
  That is why `send` had to be rejected explicitly.

## Verification

- `go build ./...` passes; `gofmt -l internal/` is empty.
- `go test ./...` passes for all 19 packages.
- Coverage: `internal/tui` 89.4%, `internal/adapter` 79.4%, `internal/adapter/topsailai` 87.9%,
  `internal/endpoint` 82.4%, all above the 73% floor.
- New tests: `TestJoinHistoryMarksUnverifiedRowVisibleButNotEnterable`,
  `TestJoinHistoryKeepsVerifiedRowLive`, `TestInteractiveResumeAcceptsUnverifiedRow`,
  `TestInteractiveHistoryCDRejectsUnverifiedRow`,
  `TestDiscoverReportsUnverifiedRowsAsUnknown`, and the endpoint executor case
  `listed but unverified executes`.

### The admission guard is proven load-bearing, not merely present

`TestUnverifiedTargetRejectsEveryOperationExceptResume` asserts the exact rule the human asked for:
`message.send` and `agent.stop` are rejected with `generation_required`, and `agent.resume` executes.

The test was checked against a deliberately broken build rather than trusted because it was green.
Disabling the guard (`else if false && intent.Target.Generation == ""`) made both the send and the
stop case fail with `calls=1` and `outcome=submitted`, which means the command reached the provider as
if the session were live. Restoring the guard made the test pass again.

That contrast is the evidence for the defect claim. `revalidateGeneration`
(`internal/endpoint/executor.go:301`) compares `session.Generation != target.Generation`, and two
empty strings compare equal, so revalidation alone cannot reject an unverified target. The guard is
the only site that does, and removing it silently reopens the hole.

## Remaining work

- The deployment rule is a decision, not code: a deb install must not restart the container, and
  the architecture statement that endpoint restart does not affect agent lifetime still needs to be
  narrowed for a container that hosts its own agents.
- A bounded count of unverified sessions is not yet reported in the collection result, so the
  operator still cannot see how many sessions lost their liveness in one cycle.

## Status

Fixed for the reporting and admission change. Deployment guidance recorded, not enforced by code.
