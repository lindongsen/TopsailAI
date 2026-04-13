'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Session API routes - FastAPI implementation
'''

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.api.utils import ApiResponse, success_response, error_response

# Create router
router = APIRouter(prefix="/api/v1/session", tags=["session"])

# Dependency injection for storage
_storage = None

def get_storage() -> Storage:
    """Get storage instance."""
    global _storage
    if _storage is None:
        from topsailai_server.agent_daemon.storage import Storage
        _storage = Storage()
    return _storage

def set_dependencies(session_storage, message_storage, worker_manager):
    """Set dependencies for the router."""
    global _storage
    from topsailai_server.agent_daemon.storage import Storage
    _storage = Storage(session_storage.engine)

# Pydantic models for request/response
class SessionResponse(BaseModel):
    session_id: str
    session_name: Optional[str] = None
    task: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    processed_msg_id: Optional[str] = None

@router.get("", response_model=ApiResponse)
async def list_sessions(
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    offset: int = 0,
    limit: int = 1000,
    sort_key: str = "create_time",
    order_by: str = "desc",
    storage: Storage = Depends(get_storage)
) -> ApiResponse:
    """
    List sessions with filtering and pagination.
    
    Parameters:
    - start_time: Filter sessions created after this time (ISO format)
    - end_time: Filter sessions created before this time (ISO format)
    - offset: Number of records to skip (default: 0)
    - limit: Maximum number of records to return (default: 1000)
    - sort_key: Field to sort by (default: create_time)
    - order_by: Sort order - 'asc' or 'desc' (default: desc)
    """
    try:
        # Validate sort_key
        allowed_sort_keys = ["create_time", "update_time", "session_id", "session_name"]
        if sort_key not in allowed_sort_keys:
            return error_response(f"Invalid sort_key. Allowed values: {allowed_sort_keys}")
        
        # Validate order_by
        if order_by not in ["asc", "desc"]:
            return error_response("Invalid order_by. Must be 'asc' or 'desc'")
        
        # Validate limit
        if limit < 1:
            return error_response("Limit must be greater than 0")
        if limit > 1000:
            return error_response("Limit must not exceed 1000")
        
        # Validate offset
        if offset < 0:
            return error_response("Offset must be non-negative")
        
        # Parse time filters
        start_dt = None
        end_dt = None
        
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except ValueError:
                return error_response("Invalid start_time format. Use ISO format.")
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except ValueError:
                return error_response("Invalid end_time format. Use ISO format.")
        
        # Get sessions from storage
        sessions = storage.session.list_sessions(
            start_time=start_dt,
            end_time=end_dt,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            order_by=order_by
        )
        
        # Convert to response format
        session_list = []
        for session in sessions:
            session_list.append({
                "session_id": session.session_id,
                "session_name": session.session_name,
                "task": session.task,
                "create_time": session.create_time.isoformat() if session.create_time else None,
                "update_time": session.update_time.isoformat() if session.update_time else None,
                "processed_msg_id": session.processed_msg_id
            })
        
        logger.info("Listed %d sessions (offset=%d, limit=%d)", len(session_list), offset, limit)
        return success_response(session_list)
    
    except Exception as e:
        logger.exception("Error listing sessions: %s", e)
        return error_response(f"Failed to list sessions: {str(e)}")