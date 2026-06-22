---
maintainer: AI
status: open
related_files:
  - docs/API.md
  - internal/api/handlers/group_handler.go
  - internal/api/handlers/message_handler.go
  - internal/api/handlers/member_handler.go
---

# API Response Envelope Inconsistency

## Summary

`docs/API.md` states that **all** API responses use the JSON envelope:

```json
{
  "data": { ... },
  "error": "error message if any",
  "trace_id": "uuid-string"
}
```

In practice, creation endpoints return the raw resource object, while list/get
endpoints return the documented envelope (minus the `error` field on success).

## Observed Behavior

| Endpoint | Actual Response | Documented Response |
|----------|----------------|---------------------|
| `POST /api/v1/groups` | raw group object | `{data: group, error, trace_id}` |
| `POST /api/v1/groups/{id}/members` | raw member object | `{data: member, error, trace_id}` |
| `POST /api/v1/groups/{id}/messages` | raw message object | `{data: message, error, trace_id}` |
| `POST /api/v1/accounts` | raw account object | `{data: account, error, trace_id}` |
| `POST /api/v1/accounts/{id}/api-keys` | raw API key object (includes `token`) | `{data: api_key, error, trace_id}` |
| `GET /api/v1/groups` | `{data: {...}, trace_id}` | `{data: {...}, error, trace_id}` |
| `GET /api/v1/groups/{id}/messages` | `{data: {...}, trace_id}` | `{data: {...}, error, trace_id}` |

## Impact

- Integration tests must special-case creation endpoints vs. list/get endpoints.
- New client implementations based on `docs/API.md` fail on creation responses.
- Inconsistent behavior increases maintenance burden and violates the API contract.

## Affected Tests

- `tests/integration/test_agent_trigger_api.py` (worked around in helper functions)
- `tests/integration/test_message_attachments_api.py` (worked around in helper functions)
- `tests/integration/conftest.py` fixtures (`test_group`, `test_member`, etc.)

## Recommended Fix

Choose **one** of the following and apply it consistently:

1. **Align server with docs (preferred):** Wrap all successful creation responses
   in the `{data, error, trace_id}` envelope. This is a breaking change for any
   clients that already depend on raw objects.
2. **Align docs with server:** Update `docs/API.md` to document raw objects for
   `201 Created` responses and the envelope for `200 OK` list/get responses.

If option 1 is chosen, also verify that the `error` field is present (even as an
empty string) on success, or remove it from the documented schema if it is only
used for error responses.

## Workaround

Integration tests currently access creation response fields directly:

```python
response = session.post("/api/v1/groups", json={...})
group = response.json()  # raw object
```

And use `response.json()["data"]` for list/get responses:

```python
response = session.get("/api/v1/groups")
items = response.json()["data"]["items"]
```

## References

- `docs/API.md` > "Response Format"
- `tests/integration/test_agent_trigger_api.py`
- `tests/integration/test_message_attachments_api.py`
