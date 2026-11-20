---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A model catalog read returns 502 for an agent process older than the provider change

## Trigger

Reported by the human on 2026-11-20, wording normalized, meaning preserved:

> 我在 list 的第一个 session 里面执行 model 出错了，502 错误。请分析原因。

## Symptom

`agent-cluster-cli model ac.ai-dev res_151effd65dc81d66e9024e2052860653` fails with:

```text
server request failed (502): provider_error: provider model catalog read failed
```

The same command against a newer session on the same Endpoint succeeds and renders the full profile
table. The failure is therefore not an Endpoint outage, not a credential problem and not a policy
refusal.

## Root cause

The cluster sends a named `json` parameter that the running agent process does not accept, because
that process was started before the provider gained the parameter.

| Fact | Evidence |
|---|---|
| The cluster sends `kwargs={"json":"1"}` | `providers/topsailai/src/query.go:337` via `modelInstructionKwargsWithPID` (`providers/topsailai/src/model_current.go:101`), introduced by `ecd9d4d9` |
| The provider accepts `kwargs` only since `6a2c1a27` (2026-11-19 16:45:27) | `git show 6a2c1a27^:src/topsailai/workspace/plugin_instruction/agent.py` shows `def select_model(*args)`; the commit changed it to `def select_model(*args, **kwargs)` |
| The failing session's agent process started before that commit | `ps -o lstart -p 114567` reports `Thu Nov 19 12:53:51 2026` |
| A newer process accepts the same call | `wa-515396a947f3` (pid 588593, started 07:21:24) and `wa-60fd4b9a4fde` (pid 584089, started 07:06:56) both return `ok:true` with the JSON catalog |
| The same old process accepts the call without `kwargs` | returns `ok:true` with the plain-text model list |

The provider's instruction dispatcher resolves `select_model` from the module already loaded in the
agent process, so the signature in force is the one that existed when that process started. A named
parameter that the in-memory function does not declare raises `TypeError`, which the control channel
reports as `control_rejected` with exit code 6.

The failure therefore depends on the age of the agent process, not on the session. Verified across
four sessions on two Endpoints:

| Cluster session | Provider session | Process start | Result |
|---|---|---|---|
| `res_151effd65dc81d66e9024e2052860653` | `wa-74a99df8715a` | 2026-11-19 12:53:51 | 502 |
| `res_89664d749d3a639b6bf23d255944363e` | `wa-0bc8eb1babac` | before `6a2c1a27` | 502 |
| `res_e510398ab4e110c4164ab0b0edc2c8e9` | `wa-fdc9eda10fbf` | before `6a2c1a27` | 502 |
| `res_97735ac096ef805d827477dd6ae1e534` | `wa-60fd4b9a4fde` | 2026-11-20 07:06:56 | full table |

## Why the 502 message names nothing useful

The provider CLI exits 6 and writes the reason into the control envelope's `response.error`, not into
stderr. `runJSON` (`providers/topsailai/src/provider.go:142`) returns on the non-zero exit before it
decodes stdout, so the envelope is discarded and only the empty stderr is formatted:

```text
"error":"provider provider_error: TopsailAI CLI failed: run TopsailAI CLI: exit status 6: "
```

The Endpoint log therefore records an exit code with no cause, and the Server's default branch
(`internal/server/model.go:104`) maps it to the generic `provider_error` message. The operator sees a
502 that names neither the provider call nor the reason, and the only way to learn the cause is to
reproduce the provider argv by hand.

## Secondary defect: a positional `json=1` is silently misread

`{"instruction":"agent.models","args":["json=1"]}` returns `ok:true` with
`result: "Model not found: json=1"`. The positional form is parsed as a model name, so a caller that
tries to request JSON positionally receives a successful-looking response that is actually a failed
selection attempt. The `kwargs` form the cluster uses is the only correct one, so the cluster's choice
is right; the positional form is a provider-side trap that should be rejected rather than
misinterpreted.

## Secondary defect: `model` does not accept a provider session identifier

`agent-cluster-cli model ac.ai-dev wa-74a99df8715a` fails with
`resource mapping not found: "wa-74a99df8715a"`, because the Endpoint resolves the opaque cluster
resource ID and never the provider session identifier. Only `res_*` identifiers work. This is a
usability gap rather than the 502, but it makes the failing session harder to address from the
operator's own `list` output, which prints the provider identifier.

## Impact

Every `model` read against an agent process started before 2026-11-19 16:45 returns 502 on this
deployment. The affected processes are long-lived, so the failure persists until each one is
restarted. Restarting an agent terminates a live session, so it is a lifecycle action that requires
human authorization and cannot be performed as routine maintenance.

## Proposed fix

1. Surface the control envelope's `response.error` when the provider CLI exits non-zero, so the
   Endpoint log and the resulting 502 name the real cause. This is the defect that made the
   investigation expensive, and it is independent of the skew.
2. Reject a positional `json=1` in the provider's argument normalization instead of treating it as a
   model name, so a caller cannot receive a successful response for a request that was not honoured.
3. Decide explicitly how the cluster should behave against a provider that predates `kwargs`. A
   silent fallback to the positional form would hide the skew and would also be wrong, because the
   positional form cannot request JSON. The honest options are to report the capability gap with the
   real reason, or to require a minimum provider version before advertising the online catalog read.
4. Accept a provider session identifier in `model` by resolving it through the same handle path
   `resume` already uses, so an operator can address a row from `list` without translating it.

## Verification evidence

Reproduced with the exact argv the adapter builds:

```text
topsailai runtime control call_instruction -s wa-74a99df8715a -p 114567 \
  -a '{"instruction":"agent.models","kwargs":{"json":"1"}}' --json
→ exit_code 6, error_code control_rejected,
  response.error: "instruction failed: select_model() got an unexpected keyword argument 'json'"

topsailai runtime control call_instruction -s wa-74a99df8715a -p 114567 \
  -a '{"instruction":"agent.models"}' --json
→ exit_code 0, delivery_state control_acknowledged, plain-text model list

topsailai runtime control call_instruction -s wa-515396a947f3 -p 588593 \
  -a '{"instruction":"agent.models","kwargs":{"json":"1"}}' --json
→ exit_code 0, JSON catalog with current_model DeepSeek-V4-Flash-Preview
```

Endpoint log evidence, `/opt/agent-cluster/logs/endpoint/ac.ai-dev.log`:

```text
"msg":"query adapter model catalog",
"error":"provider provider_error: TopsailAI CLI failed: run TopsailAI CLI: exit status 6: "
```

## Status

Partially fixed. Item 1 of the proposed fix is implemented and verified; items 2, 3 and 4 remain open.

### Item 1 implemented: a failed invocation now names the provider's own reason

Directed by the human on 2026-11-20, wording normalized, meaning preserved:

> 只修第一条

`runJSON` (`providers/topsailai/src/provider.go:137`) now reports the provider's own failure text
instead of an empty stderr. The reason is read from the provider's JSON document first, because that
is where the provider states it, and stderr is only the fallback. This reuses the principle already
recorded in `providerDocumentFailure` (`providers/topsailai/src/query.go:777`), whose comment states
that the document is inspected before the exit status for exactly this reason, rather than inventing a
second mechanism.

Two document shapes carry the reason, and both are read because the helper serves control calls and
business reads alike: a control envelope reports `response.error`, while a business read reports
`error_code` with `message`. Both are bounded at 4096 bytes, so a large document cannot turn one log
line into megabytes.

The classification is deliberately unchanged. The error is still a plain error, so `errorCode` still
returns `provider_error` and the Server still answers 502. Only the message is enriched, so a failure
never becomes a success and no caller's mapping changes.

Verified on the real failing session with the rebuilt provider binary:

```text
before: "TopsailAI CLI failed: run TopsailAI CLI: exit status 6: "
after:  "TopsailAI CLI failed: run TopsailAI CLI: exit status 6: instruction failed: select_model() got an unexpected keyword argument 'json'"
```

A working session still returns `ok:true` with the full profile list, so the change does not affect a
successful read.

Tests: `providers/topsailai/src/provider_failure_detail_test.go` covers the rejected control call, the
business-read code-and-message form, and three fallback cases (no reason in the document, empty
document, non-JSON document). The rejected-control-call test was proven to have teeth by reverting the
fix: it failed with the exact production symptom `exit status 6: ` and passed again after restoring.
`make check` passes.

### Items 2, 3 and 4 remain open

- Item 2: a positional `json=1` is still misread as a model name.
- Item 3: the behaviour against a provider that predates `kwargs` is still undecided.
- Item 4: `model` still refuses a provider session identifier.

The environment remedy is unchanged: a `model` read against an agent process started before
2026-11-19 16:45 still fails, and restarting that process requires human authorization because it
terminates a live session.
