---
maintainer: AI
author: DawsonLin
workspace: /TopsailAI/src/topsailai_agent_cluster
ProjectFolder: /TopsailAI/src/topsailai_agent_cluster
ProjectRootFolder: /TopsailAI
ProjectCode: topsailai_agent_cluster
programming_language: go
---

# The shared client decodes the body before checking the status, and discards the envelope code

## Trigger

Discovered while writing the integration test for the `messages` command. The test
asserted that a missing session reports `session_not_found` in stderr, and the
assertion failed: stderr carried the human message instead of the code.

## Defect 1: the decode runs before the status check

`internal/client/api.go:210-214`:

```go
if err := json.NewDecoder(resp.Body).Decode(&envelope); err != nil {
    return err
}
if resp.StatusCode < 200 || resp.StatusCode >= 300 {
    return fmt.Errorf("server request failed (%d): %s", resp.StatusCode, envelope.Message)
}
```

The decoder runs first, so a non-JSON error body never reaches the status branch.

### Measured behaviour

Reproduced against `httptest` servers, calling `ListEndpoints`:

| Response | Reported error |
|---|---|
| plain-text `404 page not found` | `json: cannot unmarshal number into Go value of type struct {...}` |
| plain-text `Service Unavailable` (503) | `invalid character 'S' looking for beginning of value` |
| HTML `502 Bad Gateway` | `invalid character '<' looking for beginning of value` |
| empty `200` body | `EOF` |
| JSON `404` with a code | `server request failed (404): Session not found: x` |

The first row is the worst: `404 page not found` begins with the digits `404`, so
the decoder tries to read it as a **number** and fails with a type error that
mentions the internal anonymous struct. The operator sees a Go type name and no
status code at all.

### Reachability

The plain-text paths are real, not hypothetical:

| Producer | Site | Body |
|---|---|---|
| A Server that predates a route | Go `ServeMux` default | `404 page not found` |
| `/api/v1/events` without a broker | `internal/server/events.go:125` | `event broker unavailable` |
| `/api/v1/events` wrong method | `internal/server/events.go:137` | `method not allowed` |
| `/api/v1/events` without a flusher | `internal/server/events.go:146` | `streaming unsupported` |
| Channel acceptor rejections | `internal/channel/acceptor.go:37-54` | mTLS and identity messages |

The first row is the one that matters operationally: a newer CLI against an older
Server cannot report "this route does not exist", which is the single most useful
diagnosis during a rolling upgrade. It reports a JSON type error instead.

### The same file already does it correctly

`FollowOutput` (`internal/client/api.go:109-116`) checks the status **first** and
ignores the decode error:

```go
if resp.StatusCode < 200 || resp.StatusCode >= 300 {
    defer resp.Body.Close()
    var envelope struct {
        Message string `json:"message"`
    }
    _ = json.NewDecoder(resp.Body).Decode(&envelope)
    return nil, fmt.Errorf("server follow failed (%d): %s", resp.StatusCode, envelope.Message)
}
```

`Syncer.FetchManifest` (`internal/client/sync.go:73-75`) also checks the status
first. So the correct order is already established twice in this package; only the
shared `request()` helper has it backwards.

## Defect 2: the envelope code is decoded and never used

`Code any` is decoded at line 206 and never read. Every Server failure carries a
stable machine code (`session_not_found`, `endpoint_not_found`,
`permission_denied`, `not_committed`), and the shared client drops all of them. A
caller can therefore only match on the human message text, which is not a stable
contract.

The `messages` integration test had to assert on message substrings
(`provider does not know session`) instead of the code, which is exactly the
fragility this defect creates.

## Why it was not caught

`internal/client/api_test.go:17` is the only test that exercises a non-2xx
response, and it writes the body with `http.Error`:

```go
http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
```

`http.Error` sets `Content-Type: text/plain` but the **body is still valid JSON**,
so the decoder succeeds and the status branch is reached in the intended order.
Measured: that case returns `server request failed (401): unauthorized`, which is
correct.

The test therefore proves the JSON-error path and says nothing about the
non-JSON-error path. The failure mode requires a body that is not JSON, and no
test produced one. The `Content-Type` header is also never inspected, so a
`text/plain` response carrying JSON is accepted as if it were the envelope.

## Impact

Affects every client call, not only `messages`: `history`, `logs`, `send`, `start`,
`resume`, `stop`, `refresh` and the endpoint listing all share this helper.

## Suggested fix

Check the status before decoding, and fall back to a bounded body excerpt when the
body is not JSON:

1. Read the status first.
2. On a non-2xx status, attempt to decode the envelope; if that fails, report the
   status with a bounded excerpt of the raw body.
3. On a 2xx status, decode and fail loudly if the body is not the expected
   envelope.
4. Surface `envelope.Code` in the returned error so callers can match a stable
   code instead of message text.

## Not fixed in this unit

The `messages` command is complete and verified without this change. Fixing the
shared client alters the error contract of every command, so it needs its own
logical unit, its own regression coverage across the affected commands, and a
review of every caller that currently matches on message text.

## Resolution

Fixed in `internal/client/api.go`. The status is now read before any decode, and
one shared helper builds every non-2xx error.

### What changed

- `request()` checks `resp.StatusCode` first and delegates to `decodeFailure`.
  A 2xx response that is not an envelope now fails with
  `server response (<status>) is not a valid envelope`, so a corrupt success is
  never silently accepted as an empty result.
- `decodeFailure(prefix, resp)` reads at most `failureExcerptBytes` (4096) of the
  body, tries the envelope decode, and otherwise quotes the trimmed excerpt. An
  empty body reports `empty response body` instead of `EOF`.
- `failureCode(any)` renders the envelope code. The field stays `any` because a
  success response carries the integer `0`; only a non-empty rendering is
  reported, so a coded failure reads
  `server request failed (404): session_not_found: provider does not know session x`.
- `FollowOutput` now calls the same helper instead of its own copy. It previously
  decoded with the error ignored, so a non-JSON rejection produced
  `server follow failed (404): ` with an empty message.

### Measured before and after

| Response | Before | After |
|---|---|---|
| plain-text `404 page not found` | `json: cannot unmarshal number into Go value of type struct {...}` | `server request failed (404): page not found` |
| plain-text `Service Unavailable` | `invalid character 'S' looking for beginning of value` | `server request failed (503): Service Unavailable` |
| HTML `502 Bad Gateway` | `invalid character '<' looking for beginning of value` | `server request failed (502): <html>...` |
| empty body | `EOF` | `server request failed (500): empty response body` |
| coded JSON 404 | `server request failed (404): Session not found: x` | `server request failed (404): session_not_found: Session not found: x` |
| non-JSON follow 404 | `server follow failed (404): ` | `server follow failed (404): page not found` |

### Regression coverage

`internal/client/api_test.go` gained four tests, and each one fails against the
previous implementation, so they prove the defect rather than locking in the
current behaviour:

- `TestAPIClientReportsStatusForNonJSONFailure` — four sub-cases (plain-text 404,
  plain-text 503, HTML 502, empty body). Each asserts the status appears and the
  decoder error does not.
- `TestAPIClientSurfacesFailureCode` — asserts `session_not_found` reaches the
  caller.
- `TestAPIClientFollowReportsStatusForNonJSONFailure` — asserts the follow path
  shares the decoder.
- `TestAPIClientRejectsNonEnvelopeSuccess` — asserts a non-envelope 2xx fails
  loudly.

Coverage: `decodeFailure` 100%, `failureCode` 75%, `request` 89.3%,
`FollowOutput` 88.6%, package total 85.9%.

### Caller impact

No test asserted the previous error text, so no assertion had to be relaxed. The
`messages` integration test was tightened instead: it now asserts
`session_not_found` in stderr, which is only possible after this fix. Verified by
running the tightened assertion against the previous client, where it fails with
`server request failed (404): provider does not know session never-recorded`.

### Remaining limitation

`Content-Type` is still not inspected. A `text/plain` response whose body happens
to be a valid envelope is accepted. This is deliberate: the Server sets the header
correctly, and rejecting on a header mismatch would break proxies that rewrite it.
The status-first ordering is what matters, because it is the only evidence that
survives a body that is not JSON at all.
