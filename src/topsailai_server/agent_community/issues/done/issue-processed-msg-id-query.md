# Issue: Add `processed_msg_id` query filter to message list API

## Status
Done

## Feature Description
Add the ability to query messages by `processed_msg_id` via the `GET /api/v1/groups/:group_id/messages` endpoint.

This allows clients to find agent response messages that were generated in response to a specific user message, by filtering on the `processed_msg_id` field.

## Files Modified

### Code Changes

1. **`internal/api/handlers/message.go`**
   - Added `processed_msg_id` query parameter filter in the `ListMessages` handler.
   - The filter is applied before the total count query, ensuring both count and result set are filtered consistently.

### Documentation Changes

2. **`docs/API.md`**
   - Added `processed_msg_id` to the query parameters table for `GET /api/v1/groups/:group_id/messages`.
   - Added an example request showing how to use the new query parameter.

## Test Files Created (for reference)

3. **`internal/api/handlers/message_test.go`**
   - Unit tests for the `processed_msg_id` filter:
     - Filter by matching `processed_msg_id`
     - No filter returns all messages
     - Empty filter returns all messages
     - Verify field presence in response
     - Non-existent `processed_msg_id` returns empty results

4. **`tests/integration/test_api.py`**
   - Integration tests in `TestMessageProcessedMsgID` class:
     - `test_list_messages_by_processed_msg_id`: Validates filtering returns the correct agent response message
     - `test_list_messages_by_nonexistent_processed_msg_id`: Validates empty results for non-existent IDs

## Summary

The `processed_msg_id` field already existed in the `GroupMessage` model and had a database index (`idx_group_messages_processed_msg_id`). This change exposes it as a query parameter on the message list API, enabling clients to trace agent responses back to the messages that triggered them.

The implementation follows existing handler patterns (trace ID logging, query building, error handling) and required only a minimal code change (~3 lines) in the handler.
