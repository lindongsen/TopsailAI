---
maintainer: AI
author: DawsonLin
status: specification
---

# Live acceptance test suite

## Purpose

This suite verifies Agent Cluster against real deployed Server, Endpoint, CLI, network, storage, and provider boundaries. It follows BDD wording, but it is a live operator procedure rather than an automated BDD suite. Automated coverage under `features/`, `tests/bdd/`, and `tests/integration/` does not replace this evidence.

The suite covers two concerns:

- Endpoint-owned authorization: Server authentication, Endpoint-token selection, access-policy parsing and reload, positive and negative permissions, token isolation, and proof that denied work never reaches the provider.
- Basic operation: inventory, refresh, detailed reads, output, commands, lifecycle, drive control, failure handling, recovery, and cleanup.

## Run order

1. [Environment and safety](environment.feature.md)
2. [Endpoint access policy](access-policy.feature.md)
3. [Inventory and refresh](inventory.feature.md)
4. [Observation and detailed reads](observation.feature.md)
5. [Commands and controls](commands.feature.md)
6. [Lifecycle and drive control](lifecycle.feature.md)
7. [Resilience and cleanup](resilience.feature.md)

Do not skip a failed prerequisite. A later scenario may run only when every scenario it depends on is PASS.

## Result states

| State | Meaning |
|---|---|
| `PASS` | Fresh evidence proves every expected result and effect. |
| `FAIL` | The observed result or side effect differs from the expected contract. Stop dependent scenarios. |
| `BLOCKED` | The environment cannot exercise the case. Record the exact missing dependency; this is not PASS. |
| `UNSUPPORTED` | The Endpoint accurately does not advertise the capability. Advertised-but-broken behavior is FAIL. |
| `NOT RUN` | No attempt was made. |

A command accepted by the Server is not proof that the Endpoint allowed it. A provider invocation that exited is not proof that the Agent consumed input or completed work. Record each boundary separately.

## Required topology

Use a dedicated live-test deployment with:

- one real Server;
- at least two real Endpoints when cross-Endpoint isolation is tested;
- one real provider binding per tested Endpoint;
- at least one test-owned running session and one stopped or resumable session;
- a Server credential dedicated to the run;
- separate Endpoint tokens for administrator, read-only, single-operation, denied, wrong-Endpoint, and rotation scenarios;
- a test-owned access-policy directory and command allowlist;
- an operator workstation that can reach the Server API.

If only one Endpoint is available, mark cross-Endpoint scenarios BLOCKED rather than simulating a second Endpoint in the same policy identity.

## Dynamic values

Resolve these values from the current run and never copy them from an older report:

```text
<server-url>
<endpoint-a>
<endpoint-b>
<session-running>
<session-stopped>
<generation>
<command-id>
<admin-token-name>
<read-token-name>
<single-operation-token-name>
<denied-token-name>
<time>
```

Token names may appear in evidence. Token secret values must not.

## Evidence record

Create one record for every scenario:

```text
Case ID:
Started at:
Finished at:
Elapsed:
Operator:
Build versions:
Endpoint IDs:
Preconditions:
Input or keystrokes:
Expected result:
Actual result:
Provider side effect:
Result: PASS | FAIL | BLOCKED | UNSUPPORTED | NOT RUN
Evidence paths:
Notes:
```

Store fresh transcripts under the workspace temporary directory, for example `.tmp/live-acceptance/<time>/`. Capture stdout and stderr separately when practical. Redact credentials before saving evidence.

## Security and safety rules

- Never record Server tokens, Endpoint-token secrets, private keys, complete prompts, or complete sensitive conversation/output data.
- Never place an Endpoint token in a URL or command history. Use the CLI mapping configuration or a protected request header.
- Run start, resume, stop, interrupt, drive, control, and exec scenarios only against test-owned resources.
- Confirm destructive operations interactively where the product requires confirmation.
- Never use broad process termination. Stop only the exact process or service instance created by the live run.
- Do not change a production policy directory. Use a dedicated test Endpoint or an approved maintenance window with rollback material prepared.
- A policy reload failure must not be “fixed” by restarting into an unverified policy. First prove the previous policy remains active.
- Cleanup removes only resources created by this suite and verifies unrelated sessions remain intact.

## Authorization model under test

```text
CLI with server-token and endpoint-token
  -> Server authenticates server-token and routes to the selected live Endpoint
  -> Endpoint authenticates endpoint-token against its local policy
  -> provider is invoked only when the Endpoint policy and local execution controls allow it
```

Expected separation:

- Wrong or missing Server credentials fail at the Server with `unauthorized`.
- Wrong, missing, unlisted, denied, wrong-Endpoint, or underprivileged Endpoint credentials fail with `policy_denied`.
- Inventory lists remain visible after Server authentication because Endpoint policy does not gate fleet and session-list projections.
- Detailed reads and management operations are gated at the Endpoint.
- The Server must not widen or narrow an Endpoint decision.

## Coverage matrix

| Area | Main scenarios |
|---|---|
| Deployment and ownership | `ENV-LIVE-001` to `ENV-LIVE-007` |
| Server authentication | `AUTH-LIVE-001` to `AUTH-LIVE-003` |
| Endpoint-token defaults and isolation | `AUTH-LIVE-004` to `AUTH-LIVE-010` |
| Scope and permission grants | `AUTH-LIVE-011` to `AUTH-LIVE-018` |
| Policy validation, reload, and rotation | `AUTH-LIVE-019` to `AUTH-LIVE-027` |
| Inventory and refresh | `INV-LIVE-001` to `INV-LIVE-010` |
| Messages, history, models, and output | `OBS-LIVE-001` to `OBS-LIVE-014` |
| Send, inject, interrupt, ctl, and exec | `CMD-LIVE-001` to `CMD-LIVE-017` |
| Start, resume, stop, and drive | `LIFE-LIVE-001` to `LIFE-LIVE-013` |
| Offline, reconnect, uncertain effects, cleanup | `RES-LIVE-001` to `RES-LIVE-012` |

## Final acceptance

The live suite is accepted only when:

- every required scenario is PASS;
- every BLOCKED or UNSUPPORTED case has an explicit human disposition;
- no denied operation invoked the provider;
- no token crossed into logs or saved evidence;
- all test-created sessions, controllers, files, and processes are cleaned up;
- unrelated sessions and Endpoint policy files are unchanged;
- the final report names the exact builds, topology, policy revision, and evidence directory.
