---
maintainer: AI
workspace: /TopsailAI/src/topsailai_server/agent_community
---

# Test Case: Integration — Message Attachments

## Overview

Verify creation, retrieval, update, and deletion of messages that include file/image attachments.

---

## TC-INT-ATT-001: Create Message with Single Attachment

### Objective

Verify a message can be created with one attachment.

### Steps

1. Create a group and add a user member.
2. Send `POST /groups/{group_id}/messages` with `message_attachments`.

### Input

```json
{
  "message_text": "See this image",
  "message_attachments": [
    {
      "data": "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
      "size": 67,
      "format": "image/png"
    }
  ]
}
```

### Expected Output

Status: 201
```json
{
  "data": {
    "message_id": "msg-001",
    "message_text": "See this image",
    "message_attachments": [
      {
        "data": "iVBORw0KGgo...",
        "size": 67,
        "format": "image/png"
      }
    ],
    "sender_id": "user-001",
    "sender_type": "user",
    "create_at_ms": 1704067200000,
    "update_at_ms": 1704067200000
  },
  "trace_id": "..."
}
```

### Pass Criteria

- Message created.
- Attachment data, size, and format preserved.

---

## TC-INT-ATT-002: Create Message with Multiple Attachments

### Objective

Verify a message can include multiple attachments.

### Steps

1. Send message with two attachments (image + file).

### Input

```json
{
  "message_text": "Here are two files",
  "message_attachments": [
    {
      "data": "base64-image-data",
      "size": 1024,
      "format": "image/png"
    },
    {
      "data": "base64-pdf-data",
      "size": 2048,
      "format": "application/pdf"
    }
  ]
}
```

### Expected Output

Status: 201
- Both attachments returned in order.

### Pass Criteria

- Multiple attachments preserved.

---

## TC-INT-ATT-003: List Messages Includes Attachments

### Objective

Verify message list endpoint returns attachments.

### Steps

1. Create a message with attachment.
2. Send `GET /groups/{group_id}/messages`.

### Expected Output

Status: 200
- Listed message includes `message_attachments` array.

### Pass Criteria

- Attachments visible in list response.

---

## TC-INT-ATT-004: Get Message Includes Attachments

### Objective

Verify there is no dedicated GET message endpoint or list returns full attachment data.

### Steps

1. Create message with attachment.
2. List messages and verify attachment data.

### Expected Output

Status: 200
- Attachment data is complete.

### Pass Criteria

- Attachment data retrievable.

---

## TC-INT-ATT-005: Update Message Text Preserves Attachments

### Objective

Verify updating only `message_text` preserves existing attachments.

### Steps

1. Create message with attachment.
2. Send `PUT /messages/{message_id}` with only `message_text`.

### Input

```json
{
  "message_text": "Updated text"
}
```

### Expected Output

Status: 200
- `message_text` updated.
- `message_attachments` unchanged.

### Pass Criteria

- Partial update preserves attachments.

---

## TC-INT-ATT-006: Update Message Attachments

### Objective

Verify updating `message_attachments` replaces the attachment list.

### Steps

1. Create message with one attachment.
2. Send PUT with new attachments.

### Input

```json
{
  "message_attachments": [
    {
      "data": "new-base64-data",
      "size": 512,
      "format": "image/jpeg"
    }
  ]
}
```

### Expected Output

Status: 200
- Attachment list replaced with new data.

### Pass Criteria

- Attachments can be updated.

---

## TC-INT-ATT-007: Delete Message with Attachments

### Objective

Verify soft-deleting a message with attachments clears content and marks deleted.

### Steps

1. Create message with attachment.
2. Send DELETE.
3. List messages with `include_deleted=true` (admin only; deleted messages are excluded by default).

### Expected Output

Status: 200 or 204
- `is_deleted=true`.
- `message_text` empty.
- `message_attachments` empty.

### Pass Criteria

- Soft delete clears message content and attachments.
- Deleted message is retrievable by admin when `include_deleted=true`.

---

## TC-INT-ATT-008: Attachment with S3 URL Data

### Objective

Verify attachment `data` can be an S3 URL instead of base64.

### Input

```json
{
  "message_attachments": [
    {
      "data": "s3://bucket/path/object.png",
      "size": 1024,
      "format": "image/png"
    }
  ]
}
```

### Expected Output

Status: 201
- S3 URL preserved.

### Pass Criteria

- S3 URLs accepted.

---

## TC-INT-ATT-009: Large Attachment Handling

### Objective

Verify reasonably large base64 attachments are accepted.

### Steps

1. Create attachment with ~1MB base64 data.
2. Send message.

### Expected Output

Status: 201
- Attachment stored.

### Pass Criteria

- Large attachments handled within server limits.

---

## TC-INT-ATT-010: Invalid Attachment Format

### Objective

Verify invalid attachment structure is rejected.

### Steps

1. Send message with attachment missing required fields.

### Input

```json
{
  "message_attachments": [
    {
      "data": "missing-size-and-format"
    }
  ]
}
```

### Expected Output

Status: 400

### Pass Criteria

- Invalid attachments rejected.

---

## TC-INT-ATT-011: Empty Attachments Array

### Objective

Verify empty `message_attachments` array is accepted.

### Input

```json
{
  "message_text": "No attachments",
  "message_attachments": []
}
```

### Expected Output

Status: 201
- `message_attachments` is empty array.

### Pass Criteria

- Empty attachment array handled.

---

## TC-INT-ATT-012: Mentions and Attachments Together

### Objective

Verify a message can include both mentions and attachments.

### Input

```json
{
  "message_text": "@agent-001 please analyze this image",
  "message_attachments": [
    {
      "data": "base64-image",
      "size": 1024,
      "format": "image/png"
    }
  ]
}
```

### Expected Output

Status: 201
- `mentions` array extracted.
- `message_attachments` preserved.

### Pass Criteria

- Mentions and attachments coexist.

---

## Test Execution

```bash
cd /TopsailAI/src/topsailai_server/agent_community/tests/integration
pytest test_message_attachments.py -v
```

## Notes

- Base64 data should be valid to avoid decoding errors.
- Large attachment limits depend on server configuration and database constraints.
- S3 URL support is implementation-dependent; verify actual behavior.
