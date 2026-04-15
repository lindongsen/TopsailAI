'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-14
  Purpose: Session API routes - FastAPI implementation
'''

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage, MessageData
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.api.utils import ApiResponse, success_response, error_response
from topsailai_server.agent_daemon.api.processor_helper import check_and_process_messages


# Router
router = APIRouter(prefix="/api/v1/session", tags=["session"])

# Global dependencies (set by app.py)
_session_storage = None
_message_storage = None
_worker_manager = None


def set_dependencies(session_storage, message_storage, worker_manager):
    """Set dependencies for the routes (called by app.py)"""
    global _session_storage, _message_storage, _worker_manager
    _session_storage = session_storage
    _message_storage = message_storage
    _worker_manager = worker_manager


def get_storage() -> Storage:
    """Get Storage instance"""
    if _session_storage is None:
        raise RuntimeError("Storage not initialized")
    return Storage(_session_storage.engine)


def get_worker_manager() -> WorkerManager:
    """Get WorkerManager instance"""
    if _worker_manager is None:
        raise RuntimeError("WorkerManager not initialized")
    return _worker_manager


# Request/Response Models
class SessionResponse(BaseModel):
    """Response model for a session"""
    session_id: str
    session_name: str
    task: Optional[str] = None
    create_time: datetime
    update_time: datetime
    processed_msg_id: Optional[str] = None


class ProcessSessionRequest(BaseModel):
    """Request model for processing a session"""
    session_id: str


class ProcessSessionResponse(BaseModel):
    """Response model for process session"""
    processed_msg_id: Optional[str] = None
    processing_msg_id: Optional[str] = None
    messages: Optional[List[dict]] = None
    processor_pid: Optional[int] = None


@router.get("", response_model=ApiResponse)
async def list_sessions(
    session_ids: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    offset: int = 0,
    limit: int = 1000,
    sort_key: str = "create_time",
    order_by: str = "desc",
    storage: Storage = Depends(get_storage)
) -> ApiResponse:
    """
    List sessions with optional filtering and pagination.

    Args:
        session_ids: Comma-separated list of session IDs to filter
        start_time: Start time filter (ISO format string)
        end_time: End time filter (ISO format string)
        offset: Pagination offset
        limit: Maximum number of sessions to return
        sort_key: Field to sort by (default: create_time)
        order_by: Sort order (asc or desc, default: desc)
    """
    try:
        # Parse datetime strings if provided
        start_dt = None
        end_dt = None

        if start_time:
            start_dt = datetime.fromisoformat(start_time)
        if end_time:
            end_dt = datetime.fromisoformat(end_time)

        # Parse session_ids if provided
        session_id_list = None
        if session_ids:
            session_id_list = [s.strip() for s in session_ids.split(",") if s.strip()]

        # Get sessions from storage
        sessions = storage.session.list_sessions(
            session_ids=session_id_list,
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
            session_list.append(SessionResponse(
                session_id=session.session_id,
                session_name=session.session_name,
                task=session.task,
                create_time=session.create_time,
                update_time=session.update_time,
                processed_msg_id=session.processed_msg_id
            ))

        logger.info("Listed %d sessions", len(session_list))
        return success_response(data=session_list)

    except Exception as e:
        logger.exception("Error listing sessions: %s", e)
        return error_response(message=f"Failed to list sessions: {str(e)}")


@router.delete("", response_model=ApiResponse)
async def delete_sessions(
    session_ids: str,
    storage: Storage = Depends(get_storage)
) -> ApiResponse:
    """
    Delete sessions and their related messages.

    Args:
        session_ids: Comma-separated list of session IDs to delete
    """
    try:
        # Parse session_ids
        session_id_list = [s.strip() for s in session_ids.split(",") if s.strip()]

        if not session_id_list:
            return error_response(message="No session IDs provided")

        deleted_count = 0
        for session_id in session_id_list:
            # Delete messages first (cascade)
            storage.message.delete_by_session_id(session_id)
            # Delete session
            storage.session.delete(session_id)
            deleted_count += 1
            logger.info("Deleted session and messages: %s", session_id)

        return success_response(
            data={"deleted_count": deleted_count},
            message=f"Deleted {deleted_count} session(s)"
        )

    except Exception as e:
        logger.exception("Error deleting sessions: %s", e)
        return error_response(message=f"Failed to delete sessions: {str(e)}")


@router.post("/process", response_model=ApiResponse)
async def process_session(
    request: ProcessSessionRequest,
    storage: Storage = Depends(get_storage),
    worker_manager: WorkerManager = Depends(get_worker_manager)
) -> ApiResponse:
    """
    Process a session - check if there are unprocessed messages and start processor if needed.

    This endpoint:
    1. Checks if processed_msg_id is the latest message
    2. If not, triggers the processor to handle unprocessed messages
    3. Returns information about the processing status

    Args:
        request: ProcessSessionRequest with session_id
    """
    try:
        session_id = request.session_id

        result = check_and_process_messages(session_id, storage, worker_manager)

        if result:
            return success_response(
                data=result,
                message="Processor started for unprocessed messages"
            )
        else:
            # Get current processed_msg_id for the response
            session = storage.session.get(session_id)
            processed_msg_id = session.processed_msg_id if session else None
            return success_response(
                data={"processed_msg_id": processed_msg_id},
                message="No processing needed"
            )

    except Exception as e:
        logger.exception("Error processing session: %s", e)
        return error_response(message=f"Failed to process session: {str(e)}")
