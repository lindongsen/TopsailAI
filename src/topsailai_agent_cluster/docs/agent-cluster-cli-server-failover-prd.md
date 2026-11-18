---
maintainer: AI
author: DawsonLin
status: draft
created: 2026-11-18
---

# CLI Server failover - product requirements

## Overview

### Background

An Endpoint already tolerates an unreachable Server. It configures an ordered address list
(`AGENT_CLUSTER_ENDPOINT_CHANNEL_ADDRESSES`) and walks it until one Server accepts the handshake
(`internal/channel/endpoint.go`, `DialAll`). The operator CLI does not. It resolves exactly one
Server URL and one bearer token from one profile (`src/main/agent-cluster-cli/cli_server_profile.go`,
`resolveServerProfile`), and every request goes to that address. When that Server is down, the CLI
fails even though a second Server is configured and reachable.

The dual-Server deployment makes this gap concrete. `docs/agent-cluster-architecture.md` and
`.task/plan_20261117T121553_dual-server-deployment.md` describe a container Server as primary and the
gd-dev Server as secondary. Every reachable Endpoint already carries both addresses in preference
order. The CLI carries one profile name, so an operator whose primary is down must edit configuration
or pass a flag before they can look at the fleet.

### Goal

When the selected Server cannot be reached, the CLI uses the next configured Server automatically,
and tells the operator which Server it used.

### Success metrics

| Metric | Target |
|---|---|
| A CLI invocation with a reachable secondary and an unreachable primary succeeds | 100% of read commands |
| A CLI invocation with every configured Server unreachable | Fails, and the error names every address attempted |
| Additional latency when the first Server is reachable | One readiness probe, bounded by a configured timeout |
| Behaviour change for a deployment that configures one Server | None |

### Scope

In scope: Server selection for the operator CLI, covering both the interactive REPL and the
non-interactive commands, including the long-lived event stream.

Out of scope: high availability, command-history continuity across Servers, any Server or Endpoint
code change, and any change to how an Endpoint chooses its Server.

### The requirement in one sentence

The CLI must behave like the Endpoint does when its first Server is unreachable: try the next one,
and say so.

## Personas

**Fleet operator**

- Identity: an engineer who runs `agent-cluster-cli` interactively to watch and control agents across
  machines.
- Core goal: see the current fleet state and act on it without first diagnosing infrastructure.
- Main pain: when the primary Server is down, the REPL reports a connection failure and the operator
  must remember which profile to switch to, then restart the session.

**Automation author**

- Identity: an engineer who writes scripts and cron jobs that call the non-interactive CLI.
- Core goal: a script that keeps working through a planned Server restart.
- Main pain: every script hardcodes one profile, so a Server restart turns a routine job into a
  failed job, and the failure looks like a cluster fault rather than a Server choice.

**On-call responder**

- Identity: the person paged when agents stop reporting.
- Core goal: determine quickly whether the fleet is broken or only one Server is.
- Main pain: a CLI failure does not distinguish "this Server is down" from "the fleet is down", so the
  first minutes of an incident are spent on the wrong question.

## User stories

### Fleet operator

- US-01: As a fleet operator, I want the CLI to use the next configured Server when the first one is
  unreachable, so that I can inspect the fleet without editing configuration first.
- US-02: As a fleet operator, I want the CLI to tell me which Server it used, so that I know which
  world I am looking at.
- US-03: As a fleet operator, I want the CLI to keep using the Server that worked last time, so that a
  recovered primary does not move me to a different world mid-incident.
- US-04: As a fleet operator, I want an interactive session to recover from a lost connection by
  reselecting a Server, so that a Server restart does not end my session.

### Automation author

- US-05: As an automation author, I want a read command to succeed through a fallback Server, so that
  a planned Server restart does not fail a routine job.
- US-06: As an automation author, I want a write command never to be retried against a second Server
  after it was sent, so that a fallback cannot duplicate a destructive operation.
- US-07: As an automation author, I want the selected Server in machine-readable output, so that a
  script can log and assert which Server answered.

### On-call responder

- US-08: As an on-call responder, I want the failure message to name every Server attempted, so that I
  can tell a single-Server outage from a fleet-wide one.
- US-09: As an on-call responder, I want an authentication failure to stop the walk instead of trying
  the next Server, so that a credential problem is not disguised as a reachability problem.
- US-10: As an on-call responder, I want a business error from a healthy Server to be reported as that
  error, so that I do not chase a Server that is working correctly.

## Functional requirements

| ID | Name | Story | Priority | Description |
|---|---|---|---|---|
| F-001 | Ordered profile group | US-01 | Must | One selection key accepts an ordered list of profile names, and the order expresses preference. |
| F-002 | Credential-free readiness probe | US-01 | Must | Reachability is decided by an unauthenticated readiness request, so no token is sent to a Server that has not been selected. |
| F-003 | Ordered fallback selection | US-01 | Must | The CLI probes candidates in order and uses the first one that reports ready. |
| F-004 | Sticky last-known-good selection | US-03 | Must | The Server that last answered is tried first on the next invocation. |
| F-005 | Switch only on unreachability | US-09, US-10 | Must | Only a transport failure or an explicit not-ready answer causes a switch; any other HTTP response stops the walk. |
| F-006 | No retry of a sent write | US-06 | Must | A write that was sent is never re-sent to another Server. |
| F-007 | Selection visibility | US-02, US-07 | Must | Every skipped candidate and the final selection are reported, in human output and in machine-readable output. |
| F-008 | Single-name group is unchanged | US-01 | Must | A selection naming one profile behaves exactly as today: no probe, no sticky state, no new failure mode. |
| F-009 | Interactive reselection | US-04 | Should | A REPL session that loses its connection reselects a Server and reports the change. |
| F-010 | Sticky state only for group selection | US-03 | Should | An explicit single-profile selection does not overwrite the sticky state. |
| F-011 | Probe timeout configuration | US-01 | Could | The per-candidate probe budget is configurable, with a bounded default. |
| F-012 | Diagnostic Server identity | US-08 | Could | The CLI can report the durable identity of the Server it reached, so an operator can confirm which Server answered. |
| F-013 | Failover opt-out | US-06 | Could | One invocation can require exactly one Server and refuse to fall back. |
| F-014 | Fleet-aware selection | US-08 | Won't | The CLI asks a Server which Endpoints are attached to it and prefers that Server. |
| F-015 | Cross-Server command history | US-02 | Won't | A command admitted on one Server is visible from another. |

## Non-functional requirements

| Dimension | Requirement |
|---|---|
| Performance | When the first candidate is reachable, selection costs one readiness probe. The probe budget is bounded, so an address that accepts a connection and never answers cannot consume the whole invocation. |
| Performance | A fallback walk is bounded by the number of configured candidates times the probe budget, and the bound is stated in the failure message. |
| Security | The readiness probe carries no `Authorization` header and no Endpoint token. A token is presented only to the Server that was selected. |
| Security | The sticky state file records a profile name only. It never records a URL, a token or an Endpoint token. |
| Security | An authentication or authorization failure never causes a switch, because switching would present a second Server's credential to a Server that already rejected the first. |
| Availability | A single unreachable Server degrades the CLI to the next configured Server rather than to a failure. |
| Availability | A CLI configured with one Server keeps today's behaviour exactly, including its failure mode. |
| Compatibility | The change is additive: an existing configuration that names one profile continues to work with no edit. |
| Compatibility | No Server, Endpoint, protocol, database or API change is required. |
| Usability | The operator learns which Server answered without reading a log file. |
| Usability | The reason a candidate was skipped is stated in one line, so a silent successful walk cannot hide a degraded primary. |
| Observability | Selection, skipping and reselection are reported on the diagnostic stream, so a script's stdout contract is unchanged. |

## Dependencies

- F-002 depends on the Server exposing an unauthenticated readiness route. `GET /readyz` already
  exists and already bypasses authentication (`internal/server/http.go`), so no Server change is
  needed.
- F-003 depends on F-001, because there is nothing to walk without an ordered group.
- F-004 depends on F-003, because stickiness only has meaning when there is more than one candidate.
- F-005 depends on F-002, because the classification of a probe answer is what decides whether the
  walk continues.
- F-009 depends on F-003 and F-007, because a reselection must be both possible and visible.
- F-012 depends on a Server-side read of the durable Server identity. That identity already exists in
  storage (`internal/storage/server/identity.go`) but is not exposed over HTTP, so this item carries a
  small Server change and is therefore not a Must.

## Priority

### MoSCoW matrix

| ID | Name | Priority | Reason |
|---|---|---|---|
| F-001 | Ordered profile group | Must | Without it there is no second candidate to use. |
| F-002 | Credential-free readiness probe | Must | Without it the CLI cannot decide reachability without sending a credential, which is a security regression. |
| F-003 | Ordered fallback selection | Must | This is the requirement itself. |
| F-004 | Sticky last-known-good selection | Must | Without it a recovered primary moves the operator to a different world than the fleet is in, which reads as a total outage. |
| F-005 | Switch only on unreachability | Must | Without it a credential or business error is disguised as a reachability problem. |
| F-006 | No retry of a sent write | Must | Without it a fallback can duplicate a destructive operation. |
| F-007 | Selection visibility | Must | A silent switch is indistinguishable from talking to the intended Server. |
| F-008 | Single-name group is unchanged | Must | Without it an existing deployment gains a new failure mode it never asked for. |
| F-009 | Interactive reselection | Should | The REPL is the main surface, but a restart of the session is a workable substitute. |
| F-010 | Sticky state only for group selection | Should | Protects an operator's explicit choice from being overwritten by a script. |
| F-011 | Probe timeout configuration | Could | A bounded default is sufficient; tuning is a refinement. |
| F-012 | Diagnostic Server identity | Could | Useful for confirming which Server answered, but the profile name already answers it. |
| F-013 | Failover opt-out | Could | A caller that needs exactly one Server can name one profile. |
| F-014 | Fleet-aware selection | Won't | The CLI cannot know which Server the fleet is attached to without asking a Server, and asking one Server about another is outside the architecture. |
| F-015 | Cross-Server command history | Won't | Two Servers are two independent worlds by design; this is a property of the architecture, not a gap in the CLI. |

Must Have is 8 of 15 items (53%), which leaves room for the Should and Could items without inflating
the first release.

### Release plan

- v1.0: F-001 through F-008. The CLI falls back, stays put, and says what it did.
- v1.1: F-009 and F-010. The interactive session recovers in place, and an explicit choice is durable.
- v2.0: evaluate F-011, F-012 and F-013 against real operator feedback.

## Acceptance criteria

### F-001 Ordered profile group

AC-F001-01: A single name is a group of one
Given `AGENT_CLUSTER_CLI_SERVER_PROFILE` names one profile
When the CLI starts
Then it uses that profile and performs no readiness probe

AC-F001-02: An ordered list is accepted
Given the profile map defines `primary` and `secondary`
When `AGENT_CLUSTER_CLI_SERVER_PROFILE` is `primary,secondary`
Then the CLI treats the two names as an ordered group with `primary` first

AC-F001-03: An unknown member is refused before any request
Given the profile map defines `primary` only
When the selection names `primary,secondary`
Then the CLI fails before sending any request, and the error names `secondary` as undefined

AC-F001-04: An empty member is refused
Given the selection contains an empty member, such as `primary,,secondary`
When the CLI parses it
Then the CLI fails and names the empty member rather than silently skipping it

### F-002 Credential-free readiness probe

AC-F002-01: The probe carries no credential
Given a group of two profiles, each with a token
When the CLI probes the first candidate
Then the probe request carries no `Authorization` header and no Endpoint token

AC-F002-02: A ready answer selects the candidate
Given a candidate whose readiness route answers 200
When the CLI probes it
Then that candidate is selected and its token is used for the real request

AC-F002-03: A not-ready answer skips the candidate
Given a candidate whose readiness route answers 503
When the CLI probes it
Then the candidate is skipped, the reason is reported, and the walk continues

### F-003 Ordered fallback selection

AC-F003-01: The first reachable candidate wins
Given `primary` is unreachable and `secondary` is ready
When the CLI runs a read command
Then the command succeeds against `secondary`

AC-F003-02: Order is the contract
Given both candidates are ready
When the CLI runs a read command
Then it uses the first candidate in the configured order

AC-F003-03: Every candidate unreachable
Given every candidate is unreachable
When the CLI runs any command
Then it fails, and the error names every address attempted

AC-F003-04: A slow candidate does not consume the walk
Given the first candidate accepts a connection and never answers
When the CLI probes it
Then the probe ends at its budget, the candidate is skipped, and the next candidate is tried

### F-004 Sticky last-known-good selection

AC-F004-01: The last good Server is tried first
Given the sticky state records `secondary`
When the CLI starts with the group `primary,secondary`
Then `secondary` is probed first

AC-F004-02: A recovered primary does not steal the selection
Given the sticky state records `secondary` and `primary` is now reachable
When the CLI runs a read command
Then it still uses `secondary`

AC-F004-03: A stale sticky entry is harmless
Given the sticky state records a profile that is no longer defined
When the CLI starts
Then it ignores the entry, walks the configured order, and reports that the entry was ignored

AC-F004-04: The sticky state holds no secret
Given the CLI has written sticky state
When the file is read
Then it contains a profile name only, and no URL, token or Endpoint token

### F-005 Switch only on unreachability

AC-F005-01: An authentication failure stops the walk
Given `primary` answers 401 and `secondary` is ready
When the CLI runs a read command
Then it reports the authentication failure and sends no request to `secondary`

AC-F005-02: A business error stops the walk
Given `primary` answers a business error such as `endpoint_offline`
When the CLI runs a read command
Then it reports that error and does not try `secondary`

AC-F005-03: A transport failure continues the walk
Given `primary` refuses the connection
When the CLI runs a read command
Then it reports the skip and tries `secondary`

### F-006 No retry of a sent write

AC-F006-01: A write is not re-sent after it was sent
Given `primary` accepts the connection and the write request is sent, then the connection drops
When the CLI reports the outcome
Then it reports an uncertain outcome and sends nothing to `secondary`

AC-F006-02: A write is not re-sent after a transport failure before sending
Given `primary` refuses the connection before the write is sent
When the CLI runs the write command
Then it selects `secondary` and sends the write exactly once

AC-F006-03: A read may be retried once
Given a read request fails in transport after a Server was selected
When the CLI retries
Then it reselects at most once and reports the reselection

### F-007 Selection visibility

AC-F007-01: The selection is reported
Given the CLI selected `secondary` after skipping `primary`
When the command completes
Then the diagnostic stream names both the skip and the selection

AC-F007-02: Machine-readable output names the Server
Given `--json` is used
When the CLI selected a Server
Then the selected profile is available to the caller without parsing human text

AC-F007-03: A single-profile invocation stays quiet
Given the selection names one profile
When the command completes
Then no selection line is printed, because nothing was chosen

### F-008 Single-name group is unchanged

AC-F008-01: No probe for one profile
Given the selection names one profile
When the CLI runs any command
Then no readiness probe is sent

AC-F008-02: The existing failure mode is preserved
Given the selection names one unreachable profile
When the CLI runs a command
Then it fails with the same error it reports today

AC-F008-03: No sticky state is written
Given the selection names one profile
When the command completes
Then no sticky state file is created or modified

### F-009 Interactive reselection

AC-F009-01: A lost connection reselects
Given an interactive session is using `primary` and the connection is lost
When the CLI reselects
Then it reports the reselection and continues the session against the new Server

AC-F009-02: Cached state is discarded on reselection
Given a reselection happened
When the next table is rendered
Then no row from the previous Server is shown

AC-F009-03: A reselection is never silent
Given a reselection happened
When the session continues
Then the operator sees which Server is now in use

### F-010 Sticky state only for group selection

AC-F010-01: An explicit single selection does not overwrite sticky state
Given the sticky state records `secondary`
When the CLI runs with an explicit single profile `primary`
Then the sticky state still records `secondary`

AC-F010-02: A group selection does update sticky state
Given the sticky state records `primary`
When a group selection succeeds against `secondary`
Then the sticky state records `secondary`

### F-011 Probe timeout configuration

AC-F011-01: A configured budget is honoured
Given a probe budget is configured
When a candidate never answers
Then the probe ends at that budget

AC-F011-02: An invalid budget is refused
Given a probe budget of zero or a negative value
When the CLI starts
Then it fails and names the invalid value

### F-012 Diagnostic Server identity

AC-F012-01: The identity is reported
Given the CLI reached a Server
When the operator asks for the Server identity
Then the CLI prints the durable identity of that Server

### F-013 Failover opt-out

AC-F013-01: Opt-out refuses to fall back
Given failover is disabled for one invocation
When the first candidate is unreachable
Then the CLI fails instead of trying the next candidate

## Assumptions

- The operator configures the same Server set for the CLI and for the Endpoints. The two lists are
  independent configuration, and neither component reads the other's list. Consistency is a
  deployment responsibility, not a code coupling.
- The configured Servers are independent deployments, not replicas. This is the existing architecture
  decision: two Servers have two databases, two tokens and two command histories.
- A readiness answer is a sufficient reachability signal. It proves the Server process is up and its
  storage is available, which is the condition that makes a request worth sending.
- The operator prefers a working Server over a specific Server. If they preferred a specific Server,
  they would name one profile.
- The CLI may write one small file under the operator's home directory. It already does so for input
  history, so this introduces no new class of state.

## Constraints

- No Server, Endpoint, protocol, database or API change is required for the Must items. `GET /readyz`
  already exists and already bypasses authentication.
- The selection key is reused rather than duplicated. A second key for "which Server" would be a
  second spelling of one decision, and the two would drift.
- A profile remains one URL and one token. A profile must never carry two URLs, because that would
  pair one Server's address with another Server's credential.
- The change is additive. A configuration that names one profile must not gain a probe, a state file
  or a new failure mode.
- The CLI must not become a second authority. It decides where to send a request, never whether an
  operation is permitted; authorization stays with the Endpoint.

## Risks

| Risk | Impact | Probability | Mitigation |
|---|---|---|---|
| The CLI and the Endpoints disagree about which Server is primary, so the CLI reads a Server with no attached Endpoints and reports an empty fleet | High | Medium | Sticky selection keeps the CLI on the Server that last answered; the selection line names the Server so the disagreement is visible; the failure message distinguishes an empty inventory from an unreachable Server |
| A write is duplicated because a fallback re-sends it | High | Low | F-006 forbids re-sending a write that was sent, and the acceptance criteria assert the second Server receives nothing |
| A token is presented to a Server that was not selected | High | Low | F-002 requires the probe to carry no credential, and the acceptance criteria assert the absence of both headers |
| A credential failure is mistaken for a reachability failure, so the operator chases the wrong problem | Medium | Medium | F-005 stops the walk on any non-readiness response, and the error names the real cause |
| A recovered primary silently moves the operator to a different world | Medium | Medium | F-004 keeps the last good Server, and F-007 reports the selection |
| A slow candidate makes every invocation slow | Medium | Medium | The probe budget is bounded, and a candidate that never answers is skipped rather than waited on |
| The sticky file becomes a hidden configuration source that surprises an operator | Low | Medium | The file holds a profile name only, is reported when used, and is ignored when it names an undefined profile |

## Design notes

These notes record the reasoning that shaped the requirements. They are not implementation
instructions.

### Why the CLI cannot copy the Endpoint's approach unchanged

The Endpoint walks its address list and reconnects on transport failure. That is safe for the Endpoint
because it holds one link and settles its receipts when the Server identity changes. The CLI has a
different problem: a fallback Server is a different world, not the same world reached another way.

The asymmetry has one consequence that decides F-004. An Endpoint only reconnects when its link fails,
so after a primary recovers the whole fleet stays on the secondary. A CLI that always probed from the
head of the list would return to the primary as soon as it recovered, while the fleet was still on the
secondary, and the operator would see an empty fleet that looks like a total outage. Sticky selection
is therefore not a convenience; it is what keeps the CLI in the same world as the fleet.

### Why reachability is decided by an unauthenticated probe

The CLI holds a token per profile. Probing a candidate with a token would present one Server's
credential to a Server that has not been selected, which is exactly the mistake the profile design
exists to prevent. `GET /readyz` answers the only question the walk needs, and it already bypasses
authentication, so the probe can be credential-free without any Server change.

### Why only unreachability causes a switch

Three classes of answer must be distinguished, and only one of them means "try the next Server":

| Answer | Meaning | Action |
|---|---|---|
| Transport failure, timeout, or an explicit not-ready answer | This Server cannot serve the request | Try the next candidate |
| Authentication or authorization failure | This Server is healthy and rejected this credential | Stop and report |
| Any business error | This Server is healthy and answered the question | Stop and report |

Switching on the second class would present a second credential to a Server that already refused the
first, and would hide a configuration problem behind a successful-looking fallback. Switching on the
third class would replace a real answer with a second, equally real answer, and the operator would
never learn what the first Server said.

### Why a sent write is never retried

A write that reached a Server may have been admitted and dispatched. Re-sending it to a second Server
creates a second intent with a new command identifier, and the second Server has no channel to the
Endpoint, so the operator sees a failure while the operation actually ran. For `agent.stop` and
`workspace.clean` that is a destructive duplicate. A write may therefore be sent to a fallback only
when it was never sent to the first candidate.

### Why the selection must be visible

A successful walk is otherwise completely silent. The operator would see a working CLI and could not
tell "the primary is down" from "the primary was never configured". The Endpoint reports every failed
attempt for the same reason.

### What this feature does not provide

The CLI cannot know which Server the fleet is attached to. Two Servers are two independent worlds, and
"which one is correct" is decided by the Endpoints, not by the CLI. Failover therefore makes the CLI
able to connect; it does not make the cluster continuous. Command history does not cross Servers, so a
command admitted on the primary is not visible from the secondary. An operator who intends to switch
worlds must confirm that no command is in flight, which is the same requirement the architecture
document already states for re-homing an Endpoint.

## Open questions

- [x] **Decided 2026-11-18: the sticky state is per operator, not per project directory.** The file
      stays at `${HOME}/.topsailai/.topsailai_agent_cluster.server-profile`, overridable with
      `AGENT_CLUSTER_CLI_SERVER_PROFILE_STICKY_FILE`. It reuses the per-user state directory this CLI
      already uses for its configuration and input history, and it is advisory, so a wrong entry
      self-corrects: `preferSticky` ignores a name that is no longer configured, and the next
      successful invocation overwrites the file. Partitioning by project directory would add a state
      file per project and buy no behaviour difference. Recorded in `MEMORY.md`.
- [ ] Should a reselection inside an interactive session preserve the selected Endpoint and session, or
      reset the scope to workspace? Preserving it is friendlier, but the resource may not exist on the
      new Server.
- [ ] Should the CLI warn when its configured Server set differs from the set an Endpoint reports? The
      CLI cannot see an Endpoint's address list today, so this would need a new read surface.
- [ ] Is a diagnostic Server identity worth a Server change, or is the profile name sufficient? The
      profile name answers "which configured Server", while the identity answers "which database",
      which is the question that matters after a redeployment.
- [ ] Should the probe budget be one value for all candidates or one value per candidate? One value is
      simpler; per candidate would let a known-slow Server be given more room.

## Glossary

| Term | Meaning |
|---|---|
| Profile | One named Server URL and its bearer token, treated as a single credential pair. |
| Profile group | An ordered list of profile names, where position expresses preference. |
| Readiness probe | An unauthenticated request that asks whether a Server can serve requests. |
| Sticky selection | Remembering the Server that last answered, so the next invocation tries it first. |
| World | One independent Server and its database. Two Servers are two worlds with no shared history. |

## References

- `docs/agent-cluster-architecture.md`: the re-home section, the authority model and the rule that the
  cluster defines the abstraction first.
- `docs/agent-cluster-protocol.md`: connection generation, receipt settlement and inventory behaviour
  across a re-home.
- `docs/Environment_Variables.md`: the Client section, which defines the profile keys this feature
  extends.
- `.task/plan_20261117T121553_dual-server-deployment.md`: the deployment that makes the gap concrete.
- `internal/channel/endpoint.go`: the Endpoint's ordered dial, which is the behaviour being mirrored.
- `src/main/agent-cluster-cli/cli_server_profile.go`: the current single-profile resolution.
