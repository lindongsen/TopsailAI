---
maintainer: AI
status: done
related_test_plan: docs/cases/TestCase_integration_message_attachments.md
---

# Issue: Message Attachments Request/Response Type Mismatch

## Summary

The ACS message API expects `message_attachments` to be a JSON-encoded string in the request body, but returns it as a parsed JSON array in responses. This is inconsistent with `docs/API.md`, which shows `message_attachments` as an array in both directions, and with the database schema (`JSON` column).

## Observed Behavior

- `POST /api/v1/groups/{group_id}/messages` with `"message_attachments": [{"data": "...", "size": 67, "format": "image/png"}]` fails.
- The same request with `"message_attachments": "[{\"data\": \"...\", \"size\": 67, \"format\": \"image/png\"}]"` succeeds.
- The response returns `"message_attachments": [{"data": "...", "size": 67, "format": "image/png"}]` as a parsed array.

## Expected Behavior

The API should accept and return `message_attachments` as a JSON array consistently, matching the documentation.

## Impact

- API clients must encode attachments differently for requests vs. responses.
- Integration tests must include special handling (`json.dumps` on request, `json.loads` or direct array access on response).
- Potential confusion for API consumers and inconsistent behavior with other JSON fields.

## Fix

Updated `internal/api/handlers/message.go`:
- Changed `CreateMessageRequest.MessageAttachments` and `UpdateMessageRequest.MessageAttachments` to `json.RawMessage`.
- Added `normalizeMessageAttachments` helper that accepts either a JSON array or a JSON string containing an array, validates it, and returns a compact JSON string for storage. Returns `"[]"` for nil/empty input and an error for invalid JSON or non-array values.
- Updated `CreateMessage` and `UpdateMessage` handlers to call the helper before storing into `models.GroupMessage.MessageAttachments`.
- Kept `toMessageResponse` unchanged; it already returns parsed JSON arrays.

Updated `internal/api/handlers/message_test.go`:
- Added/updated tests for array input, stringified array input (backward compatibility), invalid JSON, non-array JSON, empty attachments, and update behavior.

Updated `tests/integration/test_message_attachments_api.py`:
- Changed request payloads to use real JSON arrays.
- Added backward-compatibility check for stringified JSON array input.
- Removed the old `_get_attachments` helper that handled both string and array responses.

## Verification

- `go test ./internal/api/handlers/ -count=1` passes.
- `go test ./... -count=1` passes.
- `python3 -m py_compile tests/integration/test_message_attachments_api.py` passes.
