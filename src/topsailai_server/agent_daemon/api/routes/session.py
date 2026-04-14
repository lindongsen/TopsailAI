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


async def _check_and_process_messages(
    session_id: str,
    storage: Storage,
    worker_manager: WorkerManager
):
    """
    Check if there are unprocessed messages and start processor if needed.

    This is called after receiving a message or setting a task result.

    Flow:
    1. If processed_msg_id is the latest message -> exit
    2. If all messages from processed_msg_id to latest are role=assistant -> log and exit (avoid infinite loop)
    3. Run TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER -> if processing, exit
    4. Start the processor
    """
    try:
        # Get session
        session = storage.session.get(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return None

        # Get latest message
        latest_message = storage.message.get_latest_message(session_id)
        if not latest_message:
            logger.warning("No messages found for session: %s", session_id)
            return None

        # Step 1: Check if processed_msg_id is at the latest message
        if session.processed_msg_id == latest_message.msg_id:
            logger.debug("Session %s is up to date", session_id)
            return None

        # Get unprocessed messages
        unprocessed = storage.message.get_unprocessed_messages(session_id, session.processed_msg_id)
        if not unprocessed:
            logger.debug("No unprocessed messages for session: %s", session_id)
            return None

        # Step 2: Check if ALL unprocessed messages are assistant (avoid infinite loop)
        if all(msg.role == "assistant" for msg in unprocessed):
            logger.info("All unprocessed messages are assistant, skipping session %s to avoid infinite loop", session_id)
            return None

        # Step 3: Check if session is idle
        if not worker_manager.is_session_idle(session_id):
            logger.info("Session %s is processing, skipping", session_id)
            return None

        # Step 4: Combine unprocessed messages into a task and start processor
        task = "\n".join([msg.message for msg in unprocessed])
        logger.info("Starting processor for session: %s, msg_id: %s", session_id, latest_message.msg_id)

        success = worker_manager.start_processor(
            session_id=session_id,
            msg_id=latest_message.msg_id,
            task=task
        )

        if success:
            return {
                "processed_msg_id": session.processed_msg_id,
                "processing_msg_id": latest_message.msg_id,
                "messages": [
                    {
                        "msg_id": msg.msg_id,
                        "session_id": msg.session_id,
                        "message": msg.message,
                        "role": msg.role,
                        "create_time": msg.create_time.isoformat() if msg.create_time else None,
                        "update_time": msg.update_time.isoformat() if msg.update_time else None,
                        "task_id": msg.task_id,
                        "task_result": msg.task_result
                    }
                    for msg in unprocessed
                ],
                "processor_pid": worker_manager.running_processes.get(session_id).pid if session_id in worker_manager.running_processes else None
            }
        return None

    except Exception as e:
        logger.exception("Error checking/processing messages: %s", e)
        return None


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

        # Get session
        session = storage.session.get(session_id)
        if not session:
            return error_response(message=f"Session not found: {session_id}")

        # Get latest message
        latest_message = storage.message.get_latest_message(session_id)
        if not latest_message:
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="No messages in session"
            )

        # Check if processed_msg_id is at the latest message
        if session.processed_msg_id == latest_message.msg_id:
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="Session is up to date, no pending messages"
            )

        # Get unprocessed messages
        unprocessed = storage.message.get_unprocessed_messages(session_id, session.processed_msg_id)
        if not unprocessed:
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="No unprocessed messages"
            )

        # Check if ALL unprocessed messages are assistant (avoid infinite loop)
        if all(msg.role == "assistant" for msg in unprocessed):
            logger.info("All unprocessed messages are assistant, skipping session %s to avoid infinite loop", session_id)
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="All unprocessed messages are from assistant, skipping to avoid infinite loop"
            )

        # Check if session is idle
        if not worker_manager.is_session_idle(session_id):
            logger.info("Session %s is processing, skipping", session_id)
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="Session is currently processing"
            )

        # Start the processor
        result = await _check_and_process_messages(session_id, storage, worker_manager)

        if result:
            return success_response(
                data=result,
                message="Processor started for unprocessed messages"
            )
        else:
            return success_response(
                data={"processed_msg_id": session.processed_msg_id},
                message="Failed to start processor"
            )

    except Exception as e:
        logger.exception("Error processing session: %s", e)
        return error_response(message=f"Failed to process session: {str(e)}")
