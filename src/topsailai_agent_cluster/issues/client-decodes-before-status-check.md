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
