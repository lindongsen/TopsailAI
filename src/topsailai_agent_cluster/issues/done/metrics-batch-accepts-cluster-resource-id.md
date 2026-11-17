---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI/src
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# A cluster resource ID in a metrics batch request is silently dropped

## Trigger

Found on 2026-11-18 while fixing the sibling defect in
`issues/done/messages-cluster-id-reported-as-provider-error.md`. That fix covered
every surface that carries a session identity in a request **target**. The batch
read carries its members in the request **payload**, so it took a different
validation path and was not covered.

## Observed behaviour

The single-session read and the batch read disagree about the same value. Probed
directly against the contract decoder:

```text
batch with Cluster ID  -> err=<nil>
single with Cluster ID -> err=provider_resource_key must be a provider-private key,
                          not a Cluster resource ID "res_0123456789abcdef0123456789abcdef"
```

The batch request is therefore accepted, forwarded to the provider, and the
provider cannot resolve the identity. `providers/topsailai/query.go:462-469`
looks the member up in the workspace document, fails, and `continue`s:

```go
counts, err := runtimeMessageCounts(document.Items, sessionID)
if err != nil {
    // The reason is dropped here on purpose. The provider result carries no
    // per-member error field, so the only honest way to report an unmeasurable
    // member is to leave it out; the single-session read is the surface that
    // names the reason.
    continue
}
```

The member is omitted from the result, and the caller renders an omitted member as
**unmeasured**. A caller error is therefore presented as a provider observation:
the operator is told the session could not be measured, which is the same thing
they would see for a session whose process is genuinely gone.

## Root cause

`internal/providercli/query_types.go:228` validated each member with
`validateIdentifier`, which checks only that the value is a non-empty, trimmed,
bounded UTF-8 string. The single-session read puts its identifier in
`Target.ProviderResourceKey`, which is validated by `validateProviderResourceKey`
(`validation.go:406`), and that function additionally rejects a Cluster resource
ID.

The two paths therefore applied two different rules to the same fact. The
rejection existed and was correct; it simply was not reachable from the payload
shape.

## Why the existing guard did not catch it

`internal/providercli/cluster_resource_id_guard_test.go` enumerates the sites that
accept a provider-private key, and its doc comment states the intent: "fails when
any place that accepts a provider-private key also accepts a Cluster resource ID".
The enumeration listed the request target, the provider observation, the typed
query key and the model select payload. The batch payload member was not listed,
so the guard was complete with respect to its list and incomplete with respect to
its stated intent.

## Fix

| File | Change |
|---|---|
| `internal/providercli/query_types.go:228` | `validateIdentifier` → `validateProviderResourceKey` |
| `internal/server/metrics_batch.go` | added a `protocol.InvalidTarget` case mapping to `400 invalid_target` |
| `internal/providercli/cluster_resource_id_guard_test.go` | added the batch payload member to the enumerated sites |

The Endpoint needed no change: `readFailureCode` (`internal/endpoint/executor.go:657`)
already classifies a rejected request identity through `requestIdentityCode`, which
recognises the `ErrorCode()` method rather than importing the producing package.
That is the same primitive the sibling fix introduced, reused rather than repeated.

The Server case is required because the batch route's failure switch had no
`InvalidTarget` case, so the code fell through to the provider default and the
operator was told a provider failed. The single-session route already mapped the
same fact to `400`; one fact must not have two answers depending on which route
carried it.

## Tests

| Test | Asserts |
|---|---|
| `TestMetricsBatchRejectsAClusterResourceIDWithACallerErrorCode` | the real `Adapter.MetricsBatch` returns a coded `invalid_target` error |
| `TestMetricsBatchRejectsOneClusterResourceIDAmongValidMembers` | one bad member refuses the whole request rather than being dropped |
| `TestMetricsBatchAcceptsProviderSessionIDs` | a legitimate member still reads, with its counts intact |
| `TestMetricsBatchReportsAClusterResourceIDAsACallerError` | the HTTP route answers `400 invalid_target`, not `502 provider_error` |
| `TestMetricsBatchStillReportsAProviderFailureAsAProviderFailure` | the new case did not swallow the provider default |
| `TestClusterResourceIDsAreRejectedAtEveryProviderKeySite` | the enumerated guard now covers the batch payload member |

The adapter-level tests drive the real method rather than the validator, because
the adapter wraps the rejection with `validate provider query request: %w`. A test
of the validator alone would pass while the composed path still reported a
provider failure — the exact defect the sibling issue recorded.

## Deliberate breakages

| Breakage | Failure |
|---|---|
| Revert the member validation to `validateIdentifier` | `metrics batch payload member accepts the Cluster resource ID ...` and both adapter rejection tests fail |
| Remove the Server `InvalidTarget` case | `status = 502, want 400, body = {"code":"provider_error",...}` |
| Reject every member | `a legitimate provider session ID was rejected: validate provider query request: over-broad guard` |
| Map every unknown code to the caller-error status | `status = 400, want 502` on the provider-fault case |

The third breakage was first written as `err != nil || true`, which returns
`nil, nil` and produced no error at all. That proved nothing, so it was rewritten
to return an explicit error. A breakage that does not change behaviour is not
evidence.

## Verification

```text
go test ./internal/providercli/ ./internal/adapter/genericcli/ ./internal/server/ ./internal/endpoint/
ok  internal/providercli        0.029s
ok  internal/adapter/genericcli 0.545s
ok  internal/server             1.299s
ok  internal/endpoint           6.522s
go vet   clean
gofmt -l (own files) clean
```

`internal/channel/endpoint.go` is unformatted in the working tree, but that is a
concurrent agent's uncommitted 4-line edit; the HEAD version is formatted, and the
file was not touched by this change.

## Scope note

Four other `provider_session_id` sites in `query_types.go` still use
`validateIdentifier` (`:366`, `:405`, `:423`, `:476`). They are **result**
direction — the provider reporting what it observed — so a Cluster ID there is a
provider contract violation rather than a caller error, and rejecting it as
`invalid_target` would misattribute the fault. Only `:228` is request direction.
