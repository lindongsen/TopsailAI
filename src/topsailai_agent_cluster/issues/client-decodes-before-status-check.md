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
The caller receives a raw Go unmarshal error such as
`invalid character 'p' looking for beginning of value` instead of
`server request failed (404)`.

This is reachable today. A deployed Server that predates a route answers with
plain-text `404 page not found`, so an operator running a newer CLI against an
older Server sees a JSON parse error and cannot tell that the route is simply
absent. The status code is the only evidence that distinguishes "route missing"
from "response corrupt", and it is discarded before it can be reported.

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

Every existing client test exercises a Server that returns a JSON envelope on both
success and failure, so the decode always succeeds and the status branch is reached
in the intended order. The failure mode requires a response body that is not JSON,
which no test produced.

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
