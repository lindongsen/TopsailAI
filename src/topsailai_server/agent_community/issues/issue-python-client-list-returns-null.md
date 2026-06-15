# Issue: Python Client `list-messages` Returns `null`

## Status
Fixed

## Root Cause
The Go server API `ListMessages` (and other list endpoints) return raw JSON directly without a standard envelope:

```json
{"items": [...], "total": N}
```

The Python `api_client.py` unconditionally extracts `body.get("data")` from responses, expecting the standard envelope format:

```json
{"data": {...}, "error": "...", "trace_id": "..."}
```

When the server returns raw JSON without the envelope fields, `body.get("data")` returns `None`, which gets serialized as `null` in the CLI output.

## Fix
Applied envelope detection in `skills/agent_community_client/scripts/api_client.py`:

```python
data = body.get("data")
# Handle raw responses without standard envelope
if data is None and not body.get("error") and not body.get("trace_id"):
    data = body
return data
```

This makes the Python client compatible with both enveloped and raw server responses, matching the fix already applied to the Go CLI (`cmd/cli/api.go`).

## Affected Commands
- `list-messages`
- `list-groups`
- `list-members`
- Any other endpoint returning raw JSON without envelope

## Verification
- Ran `./skills/agent_community_client/scripts/group_lifecycle.py list-messages 89aa879f-822f-4709-9fb8-353468810a91`
- Output now correctly shows the message list with items and total count

## Related Issue
- `issue-cli-message-list-no-output.md` — same root cause, fixed in Go CLI
