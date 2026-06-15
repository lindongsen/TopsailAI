# Issue: CLI `/group:list` Command Produces No Output

## Status
**Fixed**

## Description
The `/group:list` command in the ACS CLI terminal always prints "No groups found." even when groups exist in the database.

## Root Cause
The server API handlers (e.g., `internal/api/handlers/group.go`) return raw JSON responses directly without wrapping them in a standard `APIResponse` envelope:

```json
{"items": [...], "total": N}
```

However, the CLI's `APIClient.doRequest()` unconditionally unmarshals every response into the `APIResponse` struct:

```go
type APIResponse struct {
    Data    json.RawMessage `json:"data"`
    Error   string          `json:"error"`
    TraceID string          `json:"trace_id"`
}
```

When the server returns a raw `ListGroupsResponse` (with fields `items`, `total`, etc.), unmarshaling into `APIResponse` results in all fields being zero (`Data == nil`, `Error == ""`, `TraceID == ""`).

The `GetData()` method then returns `nil` because `Data` is `nil`:

```go
func (r *APIResponse) GetData(target interface{}) error {
    if r.Data == nil {
        return nil  // <-- silently returns nil, target remains zero-valued
    }
    return json.Unmarshal(r.Data, target)
}
```

Consequently, `handleGroupList` sees an empty `result.Items` slice and prints "No groups found."

## Impact
This bug affects **all** CLI list commands that rely on `doRequest` + `GetData`, including:
- `/group:list`
- `/member:list`
- `/message:list`

## Fix
Modified `cmd/cli/api.go` (`doRequest` method) to detect raw server responses that lack the `APIResponse` envelope. When `Data`, `Error`, and `TraceID` are all zero, the raw response body is wrapped into `apiResp.Data`:

```go
// Detect raw server response without envelope (data/error/trace_id fields).
// When all envelope fields are zero, wrap the raw body as Data.
if apiResp.Data == nil && apiResp.Error == "" && apiResp.TraceID == "" {
    apiResp.Data = respBody
}
```

This makes the CLI compatible with both enveloped and raw server responses.

## Files Changed
- `cmd/cli/api.go` — added envelope detection logic
- `cmd/cli/api_test.go` — added `TestAPIClientRawResponseWithoutEnvelope` to cover this case

## Verification
```bash
cd /TopsailAI/src/topsailai_server/agent_community
go test ./cmd/cli/...
# ok  github.com/topsailai/agent-community/cmd/cli  0.017s
```

## Lessons Learned
- Client and server response formats must be kept in sync; when the server returns raw data without an envelope, the client must handle it gracefully.
- Silent nil returns in helper methods like `GetData` can mask data-mismatch bugs.
