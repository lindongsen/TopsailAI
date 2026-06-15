# Issue: `/message:list` No Output in CLI Terminal

## Status
Fixed (same root cause as `/group:list`)

## Root Cause
The server API `ListMessages` returns raw JSON directly without a standard envelope:

```json
{"items": [...], "total": N}
```

The CLI's `APIClient.doRequest()` unconditionally unmarshals responses into `APIResponse{Data, Error, TraceID}`. When the server returns raw JSON without the envelope fields, `Data` is `nil` and `GetData()` silently returns `nil`, leaving the result struct empty → "No messages found."

## Fix
The fix was already applied in `cmd/cli/api.go` (envelope detection in `doRequest()`):

```go
if apiResp.Data == nil && apiResp.Error == "" && apiResp.TraceID == "" {
    apiResp.Data = respBody
}
```

This makes the CLI compatible with both enveloped and raw server responses.

## Verification
- Added `TestAPIClientRawResponseWithoutEnvelopeMessages` in `cmd/cli/api_test.go`
- All CLI tests pass: `go test ./cmd/cli/...` ✅

## Affected Commands
- `/group:list` — fixed
- `/member:list` — fixed (same path)
- `/message:list` — fixed (same path)

## Related Issue
- `issue-cli-group-list-no-output.md` — same root cause
