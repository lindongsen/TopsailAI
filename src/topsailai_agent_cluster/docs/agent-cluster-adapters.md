---
maintainer: AI
author: DawsonLin
status: discussion-draft
created: 2026-10-27
---

# Adapter Mapping, Delivery Plan and Discussion

## This document is the only place provider detail belongs

Every section below describes how one adapter reaches one provider. That is the correct place for it,
and it is the only place it belongs.

The cluster contract is defined elsewhere and independently: `docs/agent-cluster-protocol.md` names
the abstract resources, operations, payloads, result documents, safety classes and error codes, and
`docs/agent-cluster-architecture.md` states the rule that the cluster defines the abstraction first.
Nothing in this document may change that contract. If a provider cannot satisfy a standard operation,
the answer is an explicit capability gap reported by the adapter, never a reshaped cluster operation
that happens to fit the provider.

Two habits follow, and both are mandatory when adding an adapter:

- Read the cluster contract first and ask what the adapter must supply to satisfy it. Do not read the
  provider first and ask what operation the cluster could offer instead.
- Keep provider vocabulary out of every other document. A provider flag, registry file, index or
  record format named in `internal/protocol`, in a Server route, in a stored document or in a CLI
  help body is a defect, even when it is only a comment.

## Verified TopsailAI integration surface

This table describes help/documentation inspected on 2026-10-27, not successful live operations. Installed behavior and compatibility must be verified before implementing an adapter release.

| Abstract need | Documented CLI entry | Constraint |
|---|---|---|
| Discover session/task rows | topsailai workspace list --json --local | One document with host, pwd, home, task_dir, items and total; no verified pagination/checkpoint. `--local` keeps only rows recorded on this host, which is the scope one Endpoint owns; the flag is accepted only on the `list` subcommand, and the parent `workspace --format json` form parses unknown flags silently and would ignore it |
| Session locator | item session_id and pid | Row no is presentation only; PID alone is not stable identity |
| Provider relationships | is_task, session_name, project_workspace | Parent relations and stable task IDs need live fixtures; do not infer solely from display names |
| Submit input | topsailai runtime send -s SESSION -p PID --message=TEXT --json | pipe_written is delivery, not consumption; 1 MiB UTF-8 body bound and standalone EOF-line restriction |
| Queue side context | topsailai runtime btw -s SESSION -p PID --message=TEXT --json | injection_queued is not LLM consumption; append is not fully covered by transport timeout |
| Invoke approved control | topsailai runtime control ACTION -s SESSION -p PID -a JSON --json | Correlated control acknowledgement is not completion of asynchronous business work |
| Inspect channel health | runtime control heartbeat with exact selectors | Alive control channel is not Agent/LLM progress |
| Read recent session stdout | topsailai runtime logs -s SESSION -p PID -n N --json | One bounded snapshot; not follow, not task stdout or stderr |
| Follow session stdout | topsailai runtime logs -s SESSION -p PID -n N --follow | Live tail of plain text lines; `--json` is rejected together with `--follow` |
| Read session context | runtime control get_session_messages with exact selectors | Sensitive data; separate permission, bounded output and schema validation required |

Host scope differs between discovery and revalidation, deliberately. Discovery
passes `--local`, because the inventory lists only what this Endpoint can control.
Revalidation does not, because resume authorizes on the absence of a live target:
a session recorded on another host is absent from a `--local` read, so a local
revalidation would report it as not found and admit the resume while claiming the
target does not exist. A task directory shared between hosts is exactly the case
where resuming another host's session is intended, and the provider applies no
hostname filter to resume. Such a row reports `process_generation` as `null`,
because this host cannot verify a process it cannot see, so it is found but not
live and remains a valid resume candidate.

Workspace JSON items are documented with no, filename, session_name, session_id, is_task, pid, status, created_at and project_workspace. Provider metadata paths must not be exposed by default in cluster summaries. Status values and reliability require fixture validation; do not map a generic status directly to task success.

Runtime JSON fields are documented as ok, exit_code, action, session_id, pid, delivery_state, error_code, message, bytes_written, request_id, response and delivery_unknown. Normalize by parsing the document and checking its semantics as well as process exit. Preserve precise provider error codes in a bounded namespaced detail.

`runtime logs` accepts 1–10000 lines, defaults to 20, and scans with an 8 MiB budget. Its response has lines, requested_lines, returned_lines, total_lines nullable, truncated, scan_limited, bytes_read and snapshot_size_bytes, plus selected filename. An empty scan-limited result is not proof of an empty file. Reflect truncation/limits to the user.

Both session and PID selectors mean a strict intersection. Ambiguous, stale or mismatched targets fail; do not retry using a looser selector or select the newest session. CLI local checks do not prove authenticated process generation. Endpoint maintains its own generation mapping and revalidates available evidence, but cannot manufacture provider guarantees.

Prefer the unified `topsailai runtime` wrapper rather than the legacy `topsailai_send_control`: the latter documentation allows multiple targets/broadcast and success if at least one target responds. Cluster commands must not inherit that ambiguity. Do not expose all dynamically registered control actions merely because a CLI can invoke them; map only reviewed standard semantics into the public Endpoint API; provider-only actions remain local.

Platform distinction: network protocol and management services should be portable; the documented TopsailAI FIFO/Unix-domain control transports have platform constraints. Capabilities must reflect the actual host support. Do not advertise Windows delivery support on the strength of generic HTTP portability.

## Adapter execution policy

- Configure the executable and provider roots locally by binding, never from a remote command payload. Check supported CLI version/schema at adapter initialization and report degraded health on incompatible output.
- Invoke a fixed executable with an argv array and no shell. Messages beginning with a dash use the literal assignment form; no concatenated shell strings. Preserve Unicode and whitespace; validate encoded byte length and provider framing rules.
- Run discovery once per binding per cycle for periodic full Session reporting. Server-initiated fresh pulls use the same serialized/coalesced collector; never return stale cached data as a fresh pull result. Collect each binding independently from its Adapter CLI returned results, retain failed-source last-known data with explicit unknown/stale status, and assemble one structurally complete standard inventory with descriptive adapter metadata; Server then atomically replaces the SQLite sessions_json field only after validation. Bound historical provider inventory processing. The current full-output discovery may require a provider CLI enhancement for large histories.
- Query logs only on explicit requests; opening a panel must not start periodic snapshot polling. MVP does not require periodic stdout snapshot refresh. No fake stdout cursor, heuristic line-deduplication or promise of complete historical output.
- Follow is a separate capability from snapshot, and the adapter implements it with `runtime logs --follow`. The provider rejects `--json` together with `--follow` (`runtime_cli.py`), so the follow path consumes plain text lines and never passes `--json`; the snapshot path keeps its JSON envelope. The two paths therefore never share a decoder, and a follow record carries no provider envelope fields.
- The provider buffers stdout when it is not a terminal, so a follow child is started with `PYTHONUNBUFFERED=1` and any inherited value is stripped first. Without it every record would arrive at process exit instead of as it is written, which would make a live tail look like a hang. Measured on this host: a plain piped child delivers all lines at exit (0.93s), while the unbuffered child delivers them at 0.02/0.32/0.62s.
- A follow child is a bounded child process like any other: it is started with an argv array and no shell, its lifetime is bounded by the caller context, and it is terminated as a process group on cancellation. Stopping the follow child stops the tail, not the agent.
- Task stdout, stderr, cursor-based follow, stable task detail/progress and transactionally consistent discovery are not established by the inspected runtime interface; keep these capability gaps explicit. Noninteractive launch/resume/stop is also not established, but is now a mandatory MVP integration requirement: verify a safe existing public provider lifecycle entry point or propose a separately authorized provider enhancement before declaring MVP complete. Do not emulate resume by starting a fresh conversation or stop by merely interrupting a turn.
- Enforce outer process budgets and capture bounded stdout/stderr. If a killed or timed-out process might have acted, report unknown effects; stopping the CLI is not cancellation of provider work. Clean up only exact controller-owned CLI invocation helpers and descriptors; never treat reachable Agents as owned children or terminate their process trees. Provider CLI start/resume must support an independent Agent lifecycle rather than relying on Endpoint supervision.
- Normalize pipe_written, injection_queued and control_acknowledged without upgrading them to agent consumption or task completion. Honor delivery_unknown; never automatically resend mutating operations after uncertain results.
- Keep error context sufficient for diagnosis without logging prompts, secrets, raw environment or full output. Correlate cluster command ID with provider request ID where available; do not assume generic provider idempotency.

## TUI interaction design

The operator runs a cluster CLI/TUI connected only to Server. Confirmed independent executable commands: `agent-cluster-server`, `agent-cluster-endpoint` and `agent-cluster-cli`; no role subcommands under a unified executable. Service names are `agent-cluster-server` and `agent-cluster-endpoint`; the product is Agent Cluster and the project is `topsailai_agent_cluster`. The third command is `agent-cluster-cli` rather than `agent-cluster-tui` because it serves both the interactive REPL/TUI and the noninteractive subcommands.

Fleet view: Endpoint, connectivity/freshness, standard resource labels, active session count, waiting-input count if supported, error/degraded summary. Cached data renders immediately with freshness, not an implied live guarantee.

Detail view: selected Endpoint -> Agent/Session -> optional Tasks. A lower panel can show explicitly requested bounded output snapshots; it must not periodically refresh them. Continuous follow is implemented as an explicit operator action (`logs -f`), not as a background refresh: the panel streams only while the operator asked for it, shows each record's observation time, and stops on the first keypress. Selection uses immutable IDs, not row positions.

Action panel: show only supported and permitted semantic operations. Confirm target identity and generation before submit; destructive controls need an explicit confirmation. Prompt input and side-context injection are distinct actions. Render only standard API forms with semantic descriptions and risk labels; provider-specific controls remain Endpoint-local.

Command panel: show admitted, dispatched, endpoint accepted, execution evidence and uncertain effects. A transport-acknowledged message must be displayed as delivered/queued, not task succeeded. Offline controls are disabled under the default policy; submitting during a disconnect race returns a durable status to inspect.

MVP provides start/resume/stop actions in both TUI and noninteractive CLI, with target authorization and destructive-action confirmation where applicable. It can also provide noninteractive list/show/message/command-status/explicit-output-snapshot operations alongside TUI so automation does not scrape terminal output. These operations share Server APIs and auth, not alternate provider paths.

## Post-start collection for immediate visibility

A successful `agent.start` forces one fresh collection for the Endpoint that
accepted it, in both the interactive REPL and the noninteractive CLI, so the
operator's next list already contains the launched session instead of waiting for
the periodic collection. The collection is scoped to that single Endpoint: a
workspace-wide collection would multiply provider discovery cost by the fleet size
for one launch. The client waits within the existing forced-collection budget, so
no new timeout is introduced.

The refresh is a convenience, not a readiness claim. Three outcomes are distinct:

- The collection returns the launched session, and the table shows it.
- The collection succeeds but omits the session. This is reported as
  `session submitted but not yet visible`, because a background launch is reported
  as submitted rather than started, and a session only becomes routable once its
  process is observed holding the output file. An immediate collection can
  therefore legitimately miss it. This is never reported as a launch failure and
  never triggers polling; the next periodic collection picks it up.
- The collection fails. The failure is a diagnostic on stderr and does not change
  the exit status, because the admission already succeeded.

A request the provider did not apply is not collected, since no session was
created. A client without the forced-collection seam keeps its read-only
behaviour. A `--json` caller receives the receipt alone, so the machine-readable
document is never corrupted by an appended table. The pending-visibility decision
compares standard session IDs before and after the collection, so it needs no
provider-specific parsing and no additional protocol field.

The interactive REPL goes one step further and arms the same live tail as
`logs -f` for the session that appeared, so the operator watches the new session
without typing `logf`. The tail is armed after the collection, because the
launched session's cluster identity and generation are minted by that collection;
arming earlier would bind an empty generation, which the Endpoint rejects with
`generation_required`. The launched session is identified by the same
before-and-after comparison, never by parsing the receipt, because the receipt's
provider document is opaque to the Server and must stay opaque to the TUI. No
session appeared, more than one appeared, or the generation is unverified: no tail
is armed and the reason is reported. The noninteractive CLI keeps its existing
behaviour and receives no extra output.

## Questions for the next discussion

### Scope and topology

- Confirmed: Endpoint is machine-scoped; one OS Endpoint process hosts multiple adapters for different agents. Local multi-account execution policy still needs specification.
- Server active pull is required and can use the existing outbound-established connection. Whether direct remote Endpoint HTTP access is also needed remains open; it is not a prerequisite for active pull.
- Confirmed: start/resume/stop agents is required in the first release. Automatic task scheduling/placement is a separate, unapproved feature.
- Which real second agent provider should prove the abstraction? A provider with materially different semantics is more useful than a second copy of TopsailAI.

### Interaction and safety

- Which instruction types are essential: user input, context injection, soft interrupt, request-level retry, stop process, or others? These are not interchangeable operations.
- Confirmed: no periodic stdout snapshot refresh is required. Confirmed: continuous follow is required in both the interactive REPL and the standalone command, and it is implemented as an explicit `logs -f` action. Task stdout, stderr and a cursor-based historical replay remain unverified capability gaps.
- Is a single-user deployment sufficient initially, or are multiple operators/tenants required? Recommended: single administrative domain with authenticated operator scopes; retain tenant scoping seams but do not claim multi-tenant isolation yet.
- Should commands ever queue while an Endpoint is offline? Recommended: no for MVP; avoid stale intent surprises.

### Engineering choices

- SQLite support and latest-only Session JSON persistence are confirmed requirements. Confirm or replace the remaining Go + HTTP/OpenAPI + WebSocket + SSE proposals.
- Confirm fleet/history/concurrency assumptions, retention and latency budgets before treating them as acceptance commitments.
- Confirm MVP single active Server; HA, task scheduling, automatic failover/reassignment and cross-endpoint resource placement are separate projects/features, not implied by centralized visibility.

## Current conclusion

The recommended abstraction is a capability-based management protocol plus Endpoint adapter contract, not a universal wrapper around CLI strings. Preserve provider truth, target identity and uncertain execution boundaries. MVP includes observation, exact instruction routing and agent start/resume/stop through one machine-scoped Endpoint with multiple adapters. Periodic stdout snapshot refresh is not required. Prove portability with another provider before claiming heterogeneous compatibility; automatic scheduling remains separate.

## Planning reference

Implementation phases, verification plans and execution evidence are maintained separately in `.task/plan_20261027T153140_agent-cluster-delivery.md` (project-relative path), not in the design documents.

## Confirmed Session synchronization

Endpoint periodically reports the full standard Session list (internally collected from sources such as TopsailAI workspace inventory); Server validates and commits the latest list to one SQLite JSON TEXT field per Endpoint. Server can actively request a fresh list. Both paths share revision checks and atomic replacement; no Session history or per-Session SQL rows. TUI refreshes current inventory after post-commit notifications, independently of stdout. Independent entry points are `agent-cluster-server`, `agent-cluster-endpoint` and `agent-cluster-cli`.

## Adapter privacy and resource routing

Server has no adapter table, adapter execution selector or provider-specific operation. Adapter identifiers and standard summaries may be reported inside sessions_json for display and generic filtering. Endpoint owns the private registry and maps public resource IDs/generations or launch_profile_id/profile_revision to the appropriate local adapter. TopsailAI command names, PID/provider mappings, capability translation and configuration in this document describe Endpoint internals only. Standard inventory normalizes local observations and includes adapter summaries plus Session adapter_id associations, rather than unvalidated raw CLI documents. Adding a second adapter requires no Server code, table or public schema change. Endpoint exposes aggregate collection failure and may report bounded per-adapter health summaries; Server does not independently probe or interpret adapter internals.

## Controller-only collection contract

Endpoint invokes the configured Adapter CLI and formats its returned data. It does not decide which provider records exist, scan processes/files independently, adopt Agent processes or implement automatic restarts. Adapter commands determine collection scope and facts, including running/exited/resumable entries; preserve evidence and unknown fields under the agreed formatting contract without inventing readiness or progress. Standard resource mapping is a controller reference, not Agent ownership. Agent lifecycle is independent of Endpoint in the control sense: explicit start/resume/stop are requests sent through the corresponding CLI only, and the Endpoint never supervises or adopts an Agent. That independence does not extend to process survival when both share one lifecycle boundary, such as a container that hosts the Endpoint and its Agents together; see `docs/agent-cluster-architecture.md`. Collection failures have isolated budgets and never block other Adapter publication.

## TopsailAI drive mapping

The provider exposes a resident session driver that submits input on the
operator's behalf. The adapter maps it onto the standard drive operations and the
standard Session `drive` summary; Server never parses a provider driver field.

| Standard need | Provider entry | Constraint |
|---|---|---|
| Start a controller | `workspace driver start -s SESSION --json` | The provider selects the unique live row and rejects an ambiguous target itself; the adapter passes no PID because a cluster generation is not a provider PID |
| Stop a controller | `workspace driver stop -s SESSION --json` | Addresses the recorded controller, including a residual record whose process is gone, so it does not require a live target |
| Observe controller state | the `driver` object in `workspace list --json --local` | `null` means no observation, not a confirmed absence |

Provider state mapping: `ON` becomes `running`, `STALE` becomes `stale`, `EXIT`
becomes `exited`, `FAIL` becomes `failed`, `-` becomes `none`, and `?` or any
unrecognized value becomes `unknown`. A state other than `running` is never
reported as verified, so an unverified record can never be presented as an active
controller.

Provider outcome mapping: `launched`, `already_running` and `status_read` are an
acknowledged submission; `stopped` and `already_stopped` are an acknowledged
signal with a confirmed exit; `rejected` and `failed` are not applied;
`unconfirmed` keeps unknown effect certainty and is never retried automatically.
The provider prints its outcome document on stdout even when it exits non-zero, so
the adapter preserves that document instead of flattening every failure to a
generic error.

Explicit gaps: `drive log` and `drive meta` exist only in the provider's
interactive loop, so a cluster command cannot reach them without a provider
non-interactive surface; the adapter must not read provider record files instead.
The driver task goal is provider-environment-only with no `--task-goal` flag, so
MVP accepts no goal and the provider default applies; smuggling an
operator-supplied goal through a process environment variable would let a remote
payload control provider execution through an implicit channel.
