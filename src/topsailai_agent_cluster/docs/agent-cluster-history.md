---
maintainer: AI
author: DawsonLin
status: active
created: 2026-11-08
---

# History Projection Abstraction

## Purpose and scope

This document describes the abstraction layer for the `history` command. It is written
from the cluster's point of view: what the cluster must model, what it must parse, and
how it correlates provider history with the live inventory it already holds.

This document describes the implemented abstraction layer. The `history` command, the
inventory join, the interactive row-number namespace and `resume` are all implemented;
the sections below state the contract the code enforces rather than a proposal.

Human requirements that define this layer:

> 可以用history作为指令，活查询的，topsailai那里的限制30行是有意为之，你不用理。
> 第一道判断应该在adapter去做。然后，provider也会有自己的判断，这里cluster就不用关心了。判断要做在adapter这里。
> resume 这个就是根据活表格，暂时不要给session_id吧，给数字序号就行，它的底层维度是endpoint里头的session. 注意，这个session_id可能存在重复。
> history {endpoint/hostname} 这个指令可以分别去看，workspace scope中参数是必传的，endpoint scope中 不用传参数。然后历史表里面可能会有一些sessions是在list的表里面的，这些运行中的sessions才能cd。cd进入后，行为就和现在完全一致了。
> 这个history指令你要做抽象层，cluster这里做好解析工作，能联系上list的内容。

## The problem this layer solves

The cluster already has one authoritative projection: the persisted inventory document
per Endpoint, decoded into routable `Session` resources that carry a cluster
`resource_id` and a provider `generation`. Every existing command depends on that pair.

Provider history is a different kind of data:

- It is **live**, not persisted. Nothing about it enters `endpoint_session_state`.
- It is **not routable**. A past session has no cluster `resource_id` and no
  `generation`, because it is not currently running.
- It **overlaps** the inventory. Some history rows describe sessions that are running
  right now and therefore already exist as routable resources.

The naive approach is to force history rows into the `Session` shape by inventing a
generation. That is rejected: a fabricated generation would flow into `Inspect`,
`revalidateGeneration` and `ReadOutput`, where it would be compared against real
provider evidence and silently mis-authorize or mis-reject. It would also break the
invariant that a generation is provider-issued evidence.

So the layer needs a second, explicitly non-routable projection, plus a defined join to
the routable one.

## Three concepts

### HistoryRow

A provider-neutral record of one past session, scoped to one Endpoint.

| Field | Meaning |
|---|---|
| `provider_session_id` | The provider's own session key. Not a cluster resource ID. |
| `display_name` | Provider session name, descriptive only. |
| `project_workspace` | The workspace the session worked on, descriptive only. |
| `task` | The provider's recorded task text, descriptive only. |
| `provider_status` | The provider's own status word, kept verbatim as evidence. |
| `created_at_ms` | Creation time, UTC epoch milliseconds. |
| `modified_at_ms` | Last modification time, UTC epoch milliseconds. |
| `provider_no` | The provider's own row number, kept for operator cross-reference. |
| `resumable` | The adapter's first-line verdict. |
| `resume_blocked_reason` | A bounded standard reason code when `resumable` is false. |

`HistoryRow` deliberately has **no** `resource_id`, **no** `generation`, **no**
`adapter_id` routing role and **no** cluster state. It is a report, not a resource.

### HistoryJoin

The cluster-side correlation between a `HistoryRow` and a live inventory `Session`.

- **Join key**: `(endpoint_id, provider_session_id)`.
- `session_id` alone is never a join key, because the human confirmed it may be
  duplicated. The cluster resource ID is never a join key either, because a history row
  does not have one.
- The join is always evaluated **within one Endpoint**, which is why `history` is
  endpoint-scoped. A cross-endpoint join would be meaningless and would reintroduce the
  duplicate-identifier hazard.
- The join produces, per row: `live` (bool), and when live, the matched cluster
  `resource_id` and `generation`.

The join is a pure function of two inputs the cluster already has: the history result
and the persisted inventory document for the same Endpoint. It performs no provider
call and no additional network round trip.

### HistoryView

The rendered table: one row per `HistoryRow`, enriched by its `HistoryJoin` result.

Row numbers bind to this view, replacing the live table's row numbers for the duration
of that render, as the human decided. The view is a presentation snapshot; it is not a
routing table.

## The invariant that keeps the safety model intact

> A history row is never a routing identity. Routing still requires
> `resource_id` + `generation`, and only the join can supply that pair.

Consequences, all of which follow from the invariant rather than from new special cases:

- `cd <n>` on a **live** history row enters session scope exactly as `cd` does today,
  using the joined `resource_id` + `generation`. Behaviour after entry is identical to
  the current session scope, because it is the same session scope.
- `cd <n>` on a **non-live** history row fails with an explicit diagnostic. There is no
  generation to validate, so entering session scope would create a scope that cannot
  serve any generation-dependent command.
- `logs`, `send`, `stop`, `drive`, `ctl`, `interrupt` therefore need no new code path.
  They work on live rows through the existing generation, and are unreachable on
  non-live rows because those rows cannot be entered.
- `resume <n>` is the one command that acts on a non-live row, and it acts by
  `provider_session_id` within the current Endpoint, never by a global identifier.

This is why the design needs no fake generation and no generation-free read path.

## Where each responsibility lives

| Layer | Responsibility | Must not do |
|---|---|---|
| Adapter | Invoke the provider history surface, normalize rows, apply the first-line resumability verdict | Decide cluster routing, invent generations, persist history |
| Endpoint | Route the query to the configured adapter, bound the call, return the result | Interpret provider status semantics, join with inventory |
| Channel | Carry one correlated request/response over the authenticated connection, fenced by connection generation | Cache history, retry with a different identity |
| Server | Authorize, forward, return the result verbatim | Persist history, join with inventory, interpret provider fields |
| Cluster client/TUI | Join with the persisted inventory, render the view, bind row numbers, enforce scope rules | Re-derive resumability, call the provider directly |

The split follows the existing boundary: the Server never learns what a provider status
word means, and the Endpoint never learns how the operator navigates.

## Adapter contract

History support is an **optional** interface, exactly like the existing
`ProjectHandler`. An adapter that cannot list history simply does not implement it, and
the Endpoint reports the capability as absent rather than returning an empty list.

```go
// HistoryHandler optionally lists provider session history without mutation.
type HistoryHandler interface {
    History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error)
}
```

The adapter owns the first-line resumability verdict, per the human's instruction. It
is the only layer that knows what a provider status word means, so it is the only layer
that can decide whether a row is a resume candidate. The verdict is expressed in
standard terms:

- `resumable = true` means the adapter found no provider-side obstacle.
- `resumable = false` carries a bounded standard reason code, for example
  `provider_running`, `workspace_missing`, `record_incomplete`.

The cluster does not re-derive this verdict and does not second-guess it. It may still
refuse a row for a reason of its own — a row that is live in the inventory is already
running, and resuming a running session is meaningless — but that is a distinct,
cluster-visible fact, not a reinterpretation of the adapter's verdict.

The provider performs its own final judgment when the resume is actually dispatched.
That judgment is authoritative and out of cluster scope, as the human stated. The
cluster neither duplicates it nor compensates for it.

## Query shape

`HistoryQuery` is endpoint-scoped and bounded:

| Field | Meaning |
|---|---|
| `limit` | Optional caller bound. The provider's own cap is intentional and is not overridden. |

The provider's 30-row cap is treated as a deliberate product decision, not a defect.
The cluster does not paginate around it, does not request more, and does not present the
result as a complete history. The result carries an explicit `truncated` flag so the
operator can see that the list is a bounded window rather than everything that exists.

The adapter sets `truncated` when the provider answer reaches the provider's own cap,
because the provider offers no way to ask for one more row and a full window therefore
cannot be proven complete. The cap is judged before the caller's `limit` is applied, so a
narrowed view never turns a capped provider answer into an apparently complete one. A
provider answer below the cap is not labelled truncated, so the warning keeps its meaning.

`HistoryResult` carries the rows, the observation time, the `truncated` flag and an
optional `error_code`. A failed provider call is an explicit error, never an empty
successful list, because an empty list would read as "this Endpoint has no history".

## Scope rules

The human defined the argument rule directly:

| Scope | Spelling | Endpoint argument |
|---|---|---|
| Workspace | `history <endpoint-or-hostname>` | Required |
| Endpoint | `history` | Not accepted; the current Endpoint is used |

A missing argument in workspace scope is a usage error, not a silent fan-out. Fanning
out across every Endpoint would multiply provider invocations by the fleet size and
would merge rows from different machines into one table, where the duplicate
`session_id` hazard becomes real. Requiring the argument keeps one query bound to one
Endpoint, which is also what makes the join well defined.

Hostname resolution reuses the existing endpoint resolver, including its ambiguity
prompt when several Endpoints share a hostname.

## Row-number namespace

The human decided that after `history` renders, row numbers point at the history table,
and that `cd` and `logs` must work.

- The history view becomes the current row-number namespace for that render.
- A subsequent `list` restores the live table as the namespace, exactly as it does
  today.
- Row numbers are bound to the render snapshot. A refresh that produces a different
  view invalidates the previous numbers rather than silently re-pointing them, matching
  the existing rule for the live table.
- Because only live rows can be entered, a stale number can never authorize a command
  against a session that has since stopped: the join is re-evaluated against the
  current inventory before the transition, and a row that is no longer live is rejected.

## Failure semantics

Following the project's command-surface rules, the non-interactive surface must fail
rather than degrade:

| Situation | Behaviour |
|---|---|
| Endpoint has no history-capable adapter | Explicit `history_unsupported` error |
| Endpoint is offline | Explicit `endpoint_unavailable` error |
| Provider call fails | Explicit error with the provider's bounded diagnostic |
| Provider returns no rows | Successful empty result, distinct from an error |
| Result is capped | Successful result with `truncated = true` |
| Inventory unavailable during join | History rows still render, marked as not joined, and `cd` is refused |
| Inventory reports several live sessions for one provider session ID | History rows still render, marked as ambiguous, and both `cd` and `resume` are refused |

The last two cases matter: history is a live provider read and the inventory is a
persisted document, so they can fail independently. A history row whose join could
not be evaluated is shown as unjoined rather than guessed to be live or dead.

An ambiguous row is a different unknown from an unjoined row, and the two are
reported separately because they need different remedies. An unavailable inventory
can be refreshed. Contradictory inventory data cannot: the inventory answered, and
its answer was that several live sessions share one provider session ID. The
operator must inspect the endpoint inventory instead. `resume` is refused for the
same reason, because the provider session is already running and resuming it would
start a second runtime.

## Implemented surfaces

These surfaces exist in the code. They follow the existing `launch-options` seam, which
is the established pattern for a bounded read-only query that must reach an adapter
through the Endpoint channel.

| Layer | Surface |
|---|---|
| Protocol | `HistoryQuery`, `HistoryRow`, `HistoryResult` |
| Adapter | `HistoryHandler.History` |
| Endpoint | `Executor.History`, plus a `historyFrame` handler |
| Channel | `FrameHistoryRequest` / `FrameHistoryResponse`, pending map fenced by connection generation |
| Server | `GET /api/v1/history?endpoint_id=ID` |
| Client | `APIClient.GetHistory` |
| CLI | `history <endpoint-or-hostname> [--json]` |
| TUI | `history` in endpoint scope; `history <endpoint>` in workspace scope |

The Server route requires `endpoint_id`, mirroring the workspace-scope argument rule.
It returns the adapter's result verbatim; it does not join, filter or interpret.

## What this layer deliberately does not do

- It does not persist history. The confirmed latest-only inventory design is unchanged.
- It does not add a history table, a history column or a history migration.
- It does not give the Server any knowledge of provider status words.
- It does not create a second routing path. Routing remains `resource_id` +
  `generation`.
- It does not paginate around the provider's intentional cap.
- It does not accept a bare `session_id` as a resume target, because the identifier may
  be duplicated.

## Open questions

- Should the history view show the provider's own row number as a separate column, so an
  operator can cross-reference the provider's own listing? Recommended: yes, as
  descriptive data only, never as a selection key.
- Should `history` accept a `--limit` bound below the provider cap? Recommended: yes,
  as a caller-side narrowing only; it never raises the cap.
- Which permission scope should `history` require? Not yet decided. The rows carry
  session names, task text and workspace paths, but no stdout and no conversation
  content.
