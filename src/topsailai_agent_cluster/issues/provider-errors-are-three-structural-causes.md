---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# Provider errors are frequent and three of them are structural

## Trigger

Reported by the human on 2026-11-16, quoted verbatim:

> 经常出现 provider error

## Symptom

Provider errors appear often enough that the operator reads them as a broken deployment. They are
not one error. Three distinct errors account for every provider failure in the logs, and each has a
different cause and a different correct response.

## Measured distribution

Counted from the JSON logs on the live cluster, `"level":"ERROR"` entries grouped by the `error`
field. The window is 2026-11-12T16:54 to 2026-11-16T06:23 for `ac.topsail`, and the full retained log
for the two containers.

| Error | `ac.topsail` | `ac.ai-dev` | `ac.topsailai-dev` |
|---|---|---|---|
| `provider stream record limit exceeded: 128` | 72 | 19 | 0 |
| `provider adapter capacity exhausted: discovery` | 8 | 0 | 0 |
| `provider session row was not found` | 6 | 0 | 0 |
| `provider adapter capacity exhausted: follow` | 1 | 0 | 0 |
| `provider stream ended: context deadline exceeded` | 2 | 0 | 0 |

The remaining ERROR entries are channel transport noise, not provider errors: `broken pipe` (695 on
`ac.topsail`, 239 on `ac.ai-dev`, 281 on `ac.topsailai-dev`), `connection reset by peer` (100),
`channel connection was superseded by a newer link` (49, 68, 72) and `failed to WebSocket dial` (23).
Those belong to the reconnect path and are a separate concern.

The 726 ERROR entries in the `2026-11-15T21` hour on `ac.topsail` are almost entirely transport
noise: 562 `broken pipe` and 100 `connection reset by peer`, emitted from `resend recorded receipt`
(625 entries) and `publish inventory` (47 entries). Only 25 of them are a provider error. A raw ERROR
count therefore overstates the provider problem by roughly an order of magnitude.

## Error one: provider stream record limit exceeded: 128

Source: `internal/providerconformance/runner.go:101`, with `genericCLIMaxRecords = 128`
(`src/main/agent-cluster-endpoint/adapter_factory.go:37`).

The bound is enforced by the conformance runner, which reads the same `MaxRecords` budget the
Endpoint passes to every Provider CLI invocation (`internal/adapter/genericcli/adapter.go:721`).

A follow stream that produces more than 128 records is terminated. This is a deliberate fail-closed
bound, not a defect, but the threshold is low enough that a long-running session hits it routinely.
The operator sees the stream end without a clean terminal frame, which reads as a provider fault.

The bound exists because an unbounded stream would let one session consume the channel. The correct
response is to raise the bound to a value that matches real session output, or to make it
configurable per adapter, not to remove it.

## Error two: provider adapter capacity exhausted: discovery

Source: `internal/adapter/genericcli/scheduler.go:20` (`ErrCapacity`), raised by `acquire` when a slot is
unavailable. Admission is deliberately non-blocking, so a request is rejected immediately instead of
waiting.

Limits: `genericCLIConcurrency = providercli.ConcurrencyLimits{Total: 9, Discovery: 2, Mutation: 1,
Follow: 2}` (`src/main/agent-cluster-endpoint/adapter_factory.go:60`).

`Total` was 4 when this issue was written and is now 9. A separate
`genericCLIReadConcurrency = 4` (`adapter_factory.go:67`) bounds concurrent operator reads for one
Adapter instance. It is deliberately not part of `genericCLIConcurrency`, because it is a local
Endpoint limit rather than a provider-advertised capability, so it never appears on the wire.

With two discovery slots and a periodic collection cycle, a concurrent history query or a forced
refresh is rejected instead of queued. `Discovery` is still 2, and the limit was chosen to match what
the provider advertises, so raising it requires the provider to advertise a larger bound.

## Error three: provider session row was not found

Source: `providers/topsailai/mutation_authority.go:102`, raised by `workspaceAuthority` when no row
matches the requested key.

`workspaceAuthority` reads `workspace list --json --local` (`mutation_authority.go:60`). A session
recorded on another host, or a session whose row was cleaned, therefore matches nothing and the
operation is rejected.

This error is correct behaviour for a genuinely absent row. The case where the row exists but is
invisible to a `--local` read is a deliberate policy boundary, not a defect; see the next section.

## The `--local` disagreement is resolved

This section previously recorded a disagreement between `docs/agent-cluster-adapters.md` and the
code: the document said revalidation must not pass `--local`, while `workspaceAuthority` passed it
anyway. That disagreement is closed.

The human decided on 2026-11-16 that mutation authority stays host-scoped, and the document was
corrected rather than the code. `docs/agent-cluster-adapters.md:258-278` now states the rule per read
instead of per phase, with a table naming which of the five production reads pass `--local` and why.
`workspaceAuthority` keeps `--local` on purpose (`providers/topsailai/mutation_authority.go:60`), and
its own doc comment records the same reason at the site that implements it.

The consequence is explicit and safe: a row-scoped target whose workspace row is recorded on another
host is reported as not found, and its liveness as unverified. Both are refusals rather than
admissions. Cross-host work has one supported path, `agent.resume` with a session-scoped key, which
reads the session registry through `sessionAuthority` and never passes `--local`.

The measured row counts that were recorded here are no longer needed to decide anything, so they are
removed rather than kept as stale evidence.

## Not caused by the 3248 upgrade

The three source files that define these bounds and this authority check are unchanged in the upgrade
range:

```text
git log --oneline 7dae9d69..7b57076a -- providers/topsailai/mutation_argv.go \
  providers/topsailai/mutation_authority.go src/main/agent-cluster-endpoint/adapter_factory.go
```

returns no commits. `git log -S 'genericCLIMaxRecords     = 128'` attributes the value to
`4c6a87be`, which predates the upgrade.

## Candidate fixes

| Error | Fix | Risk |
|---|---|---|
| record limit 128 | Raise the bound or make it per-adapter configurable | A larger bound lets one session consume more channel capacity |
| capacity exhausted | Raise `Discovery` above 2, or make admission wait with a bounded timeout | Waiting can turn a fast rejection into a slow one under sustained load |
| session row not found | None. The `--local` question was decided on 2026-11-16 and code and documentation now agree | Not applicable; the behaviour is a deliberate policy boundary |

## Files

- `internal/providerconformance/runner.go`
- `internal/adapter/genericcli/scheduler.go`
- `src/main/agent-cluster-endpoint/adapter_factory.go`
- `providers/topsailai/mutation_authority.go`
- `docs/agent-cluster-adapters.md`
