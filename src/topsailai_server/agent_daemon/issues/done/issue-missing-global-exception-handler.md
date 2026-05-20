---
maintainer: AI
workspace: /root/ai/TopsailAI/src/topsailai_server/agent_daemon
status: open
---

# Missing Global Exception Handler for HTTP 500 Errors

## Description
The FastAPI application in `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/app.py` does not have a global exception handler for unhandled exceptions. When an internal server error (HTTP 500) occurs, the traceback is not logged centrally, making production debugging difficult.

## Root Cause
No custom exception handler is registered for `Exception` or `HTTPException(status_code=500)` in the FastAPI app.

## Affected Files
- `/root/ai/TopsailAI/src/topsailai_server/agent_daemon/api/app.py`

## Proposed Fix
Add a global exception handler:
```python
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled exception in request to %s: %s", request.url.path, exc)
    return JSONResponse(
        status_code=500,
        content={"code": 500, "data": None, "message": "Internal server error"}
    )
```

## Impact
Without this fix, unhandled exceptions may silently fail or only produce FastAPI's default error response without detailed logging, making production issues hard to diagnose.
