---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# GetSession Missing x-session-id Header Support

## Description
The `GetSession` endpoint (`GET /api/v1/session/{session_id}`) in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/routes/session.py` only reads `session_id` from query parameters. It does not fall back to the `X-Session-Id` header when the query parameter is missing, as required by `features/00features.md` and `features/19api_key_required.md`.

## Expected Behavior
Per the spec:
> 查询session的时候，支持通过 header 确认出session_id，当 GET api/v1/session 没有传 query 的时候，可以尝试从 header 得到 session_id

## Root Cause
The route handler only extracts `session_id` from the query parameter and does not check the `X-Session-Id` request header.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/routes/session.py`

## Proposed Fix
Add header extraction as fallback:
```python
from fastapi import Header

@router.get("/api/v1/session")
async def get_session(
    session_id: Optional[str] = None,
    x_session_id: Optional[str] = Header(None, alias="x-session-id"),
    ...
):
    effective_session_id = session_id or x_session_id
    if not effective_session_id:
        raise HTTPException(status_code=400, detail="session_id is required")
    ...
```

## Impact
Clients that pass session ID via header (as documented in the spec) cannot retrieve session information.
