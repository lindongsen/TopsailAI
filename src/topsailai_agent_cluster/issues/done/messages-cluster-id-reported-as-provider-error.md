---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A cluster resource ID passed to `messages` is reported as a provider failure

## Trigger

Found during the live mock-provider command sweep on 2026-11-15. The sweep invoked
every standalone CLI command once through CLI -> Server -> Endpoint -> mock
Provider, and `messages` was the only read command that failed.

## Observed behaviour

```text
$ agent-cluster-cli messages live-tmux-endpoint res_fd925f856cda9ff17bc8a0a995fbf2d9 --json
server request failed (502): provider_error: provider messages read failed
```

The Endpoint log records the real reason:

```text
query adapter messages
error: validate provider query request: provider_resource_key must be a
provider-private key, not a Cluster resource ID "res_fd925f856cda9ff17bc8a0a995fbf2d9"
```

## Expected behaviour

The caller passed a cluster resource ID where a provider session ID belongs. That
is a caller error, and it must be reported as one. The operator must be told which
identity the command needs, not sent to investigate a provider that was never
invoked.

## Root cause

Two defects compound.

1. `internal/endpoint/messages.go:34` and `:67` collapse every adapter error into
   `protocol.MessagesProviderError`:

   ```go
   if err != nil {
       if result.ErrorCode == "" {
           result.ErrorCode = protocol.MessagesProviderError
       }
       return result, err
   }
   ```

   A request-validation failure is not a provider failure. The same collapse
   already exists for the history path and was recorded separately in
   `issues/history-disconnect-reported-as-provider-error.md`, so this is the same
   defect class in a second command.

2. `internal/server/messages.go:102` maps the resulting code to a fixed message,
   `"provider messages read failed"`, so the Endpoint's own explanation never
   reaches the operator. The Server has the error text and discards it.

## Impact

- The operator is told to investigate a provider that was never called.
- The CLI help at `internal/tui/help.go:351` states `<session-id>` without saying
  which identity it means. The parameter list does say "provider session ID; a
  cluster resource ID is not accepted", but that text is only visible through
  `help messages`, not through the failure.
- A script that reads the exit status sees a generic 502 and cannot distinguish a
  wrong identity from a provider outage.

## Reproduction

```bash
agent-cluster-cli messages <endpoint> <cluster-resource-id> --json
```

The same command with the provider session ID succeeds:

```bash
agent-cluster-cli messages <endpoint> session:stable --json
```

## Proposed fix

Classify the request-validation failure before the provider default, and forward
the Endpoint's own message instead of replacing it.

- Add a distinct code for a rejected request identity, so a caller error is never
  reported as `provider_error`.
- Keep the Endpoint's error text in the Server's response message, because the
  Server is the only component that can tell the operator what to change.
- Consider rejecting a cluster resource ID in the CLI before submission, since the
  CLI already knows the two identities are different.

## Verification

The live sweep must show `messages` passing with a provider session ID and failing
with a caller-error code, not `provider_error`, when a cluster resource ID is
supplied.

## Resolution

Fixed on 2026-11-17 in commit `193e78b5`.

### The issue's quoted code was stale, and the real cause was one layer deeper

The issue quotes `internal/endpoint/messages.go:34` and `:67` as collapsing every
adapter error into `protocol.MessagesProviderError` unconditionally. That is no
longer the code: both sites already call
`readFailureCode(err, result.ErrorCode, protocol.MessagesProviderError)`
(`internal/endpoint/messages.go:33`, `:64`).

The collapse still produced `provider_error`, but for a different reason. The
rejection was raised by `validateProviderResourceKey`
(`internal/providercli/validation.go:666`) as a plain `fmt.Errorf`, which carries
no code. `readFailureCode` (`internal/endpoint/executor.go:651`) checks the
capacity condition, then the adapter's reported code, then falls through to the
provider default. With no reported code and no capacity refusal, the result was
`provider_error`. Fixing only the two call sites the issue names would have
changed nothing.

### What changed

| File | Change |
|---|---|
| `internal/protocol/capabilities.go` | Added `const InvalidTarget = "invalid_target"` beside `PolicyDenied`, so the Server and the Endpoint share one spelling |
| `internal/providercli/validation.go` | `validateProviderResourceKey` returns `&requestIdentityError{Name, Value}`; the type implements `Error()` with the historical wording and `ErrorCode()` returning `protocol.InvalidTarget` |
| `internal/endpoint/executor.go` | `readFailureCode` gained a `requestIdentityCode` check between capacity and the adapter's reported code; the helper uses `errors.As` against `interface{ ErrorCode() string }` |
| `internal/server/messages.go` | `case protocol.InvalidTarget:` → `400 invalid_target` |
| `internal/server/detail.go` | Same case, same status |
| `internal/server/metrics.go` | Same case, same status |

`invalid_target` already existed as a literal in 16 places across the Server
handlers and `executor.go:296`. It was promoted to a protocol constant rather than
re-spelled, following the existing `PolicyDenied` convention.

The code is recognised through the `ErrorCode` method rather than by importing
`internal/providercli`, matching how the adapter already reads a provider's own
error code (`internal/adapter/genericcli/adapter.go:466`, `:495`, `:576`). The
Endpoint therefore does not depend on a concrete provider package to classify a
caller error.

### Reachability was verified per surface, not assumed

The issue claims the same collapse exists for the history path. That is wrong.

| Surface | Passes a caller-supplied provider key to `validateProviderResourceKey` | Reachable |
|---|---|---|
| `messages` | yes | yes |
| `detail` | yes | yes |
| `metrics` | yes | yes |
| `history` | no — `validateQueryTarget` returns early because `QueryRequiresSessionTarget(QueryHistoryMessages)` is false | no |
| `launch` | no target | no |
| `model catalog` | resolves a cluster ID through the mapper by design | no |

`metrics batch` validates with `validateIdentifier` only
(`internal/providercli/query_types.go:224`), not `validateProviderResourceKey`, so
a cluster resource ID in a batch request is still not rejected at the contract
boundary. That is the same defect class in a fourth surface and is **not** fixed
here; it needs its own issue.

### The Server message names the identity instead of forwarding the Endpoint's text

The issue asks for the Endpoint's own explanation to reach the operator. That is
not possible as written: `MessagesResult`, `HistoryResult`, `SessionDetail` and
`SessionMetrics` carry only `ErrorCode`, with no message field. The Server
therefore cannot forward text it never receives.

The Server composes its own message naming the required identity:
`session_id must be the provider session ID, not a cluster resource ID`. That
answers the operator's actual question — which identity to supply — without adding
a protocol field for a diagnostic string.

### Tests

| File | Tests |
|---|---|
| `internal/endpoint/read_failure_code_test.go` | `TestReadFailureCodeClassifiesARejectedIdentityAsACallerError`, `TestReadFailureCodeKeepsTheOriginalPrecedence` (5 subtests), `TestReadFailureCodeRecognisesAWrappedRejection` |
| `internal/providercli/request_identity_code_test.go` | `TestRejectedProviderKeyCarriesTheCallerErrorCode`, `TestRejectedProviderKeyKeepsItsMessage`, `TestLegitimateProviderKeyCarriesNoCode` |
| `internal/server/request_identity_test.go` | `TestMessagesRejectedIdentityIsACallerError`, `TestMessagesRejectedIdentityNamesTheRequiredIdentity`, `TestDetailRejectedIdentityIsACallerError`, `TestMetricsRejectedIdentityIsACallerError` |
| `internal/adapter/genericcli/messages_identity_test.go` | `TestMessagesRejectsAClusterResourceIDWithACallerErrorCode`, `TestMessagesAcceptsAProviderSessionID` |

The adapter test drives the real `Adapter.Messages` method, so the production
wrapping shape (`validate provider query request: %w`) is exercised rather than a
stand-in. Without it, the producer and consumer halves could each be correct while
the composed path still reported `provider_error`.

The accepting test is mandatory: a rejection applied to every value would pass the
rejecting test while breaking the command.

### Deliberate breakage

| Break | Result |
|---|---|
| Remove `requestIdentityCode` from `readFailureCode` | 2 tests FAIL: `readFailureCode="provider_error" want="invalid_target"` |
| Remove `ErrorCode()` from `requestIdentityError` | adapter test FAIL: `the adapter returned an error no caller can classify: validate provider query request: provider_resource_key must be a provider-private key, not a Cluster resource ID "res_0123..."` |
| Remove the `messages.go` case | 2 tests FAIL: `status=502 want=400 body={"code":"provider_error",...,"message":"provider messages read failed"}` — the reported symptom exactly |
| Remove the `detail.go` and `metrics.go` cases | 2 tests FAIL: `status=502 want=400` with `provider detail read failed` / `provider metrics read failed` |

All restored and re-verified green.

### Verification

- `go build ./...` exit 0; `go vet` clean; `gofmt -l` clean on all changed files.
- `internal/protocol` ok, `internal/providercli` ok, `internal/endpoint` ok 8.3s,
  `internal/server` ok 2.1s, `internal/adapter/genericcli` ok 0.6s.
- The committed tree was extracted with
  `git archive HEAD src/topsailai_agent_cluster | tar -x --strip-components=2` and
  tested in isolation: all five packages pass, so the commit does not depend on
  another agent's uncommitted work.

### Not done

- The CLI does not reject a cluster resource ID before submission. The issue lists
  this as a consideration, not a requirement, and the Server now reports the
  correct code, so the operator gets the right answer one hop later.
- `metrics batch` still validates with `validateIdentifier` only.
