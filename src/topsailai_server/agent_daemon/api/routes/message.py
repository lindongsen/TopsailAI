'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Message API routes - FastAPI implementation
'''

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage, MessageData, SessionData
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.api.utils import ApiResponse, success_response, error_response
from topsailai_server.agent_daemon.storage.processor_helper import check_and_process_messages
from topsailai_server.agent_daemon.validator import (
    validate_session_id,
    validate_message_content,
    validate_role,
    validate_msg_id,
)


# Router
router = APIRouter(prefix="/api/v1/message", tags=["message"])

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
    # Get engine from session_storage
    return Storage(_session_storage.engine)


def get_worker_manager() -> WorkerManager:
    """Get WorkerManager instance"""
    if _worker_manager is None:
        raise RuntimeError("WorkerManager not initialized")
    return _worker_manager


# Request/Response Models
class ReceiveMessageRequest(BaseModel):
    """Request model for receiving a message"""
    message: str
    session_id: str
    role: str = "user"
    processed_msg_id: Optional[str] = None


class MessageResponse(BaseModel):
    """Response model for a message"""
    msg_id: str
    session_id: str
    message: str
    role: str
    create_time: datetime
    update_time: datetime
    task_id: Optional[str] = None
    task_result: Optional[str] = None


@router.post("", response_model=ApiResponse)
async def receive_message(
    request: ReceiveMessageRequest,
    storage: Storage = Depends(get_storage),
    worker_manager: WorkerManager = Depends(get_worker_manager)
) -> ApiResponse:
    """
    Receive a new message and process it if needed.

    This endpoint:
    1. Saves the message to storage
    2. Creates session if it doesn't exist
    3. Checks if the session's processed_msg_id is at the latest message
    4. If not, triggers the processor to handle unprocessed messages
    """
    msg_id = None
    try:
        # Validate inputs
        validate_session_id(request.session_id)
        validate_message_content(request.message)
        validate_role(request.role)
        
        # Create message data
        now = datetime.now()
        message_data = MessageData(
            msg_id=msg_id,
            session_id=request.session_id,
            message=request.message,
            role=request.role,
            create_time=now,
            update_time=now
        )
        msg_id = message_data.msg_id

        # Save message to storage
        storage.message.create(message_data)

        # Create session if it doesn't exist
        session = storage.session.get(request.session_id)
        if not session:
            session_data = SessionData(
                session_id=request.session_id,
                session_name=request.session_id,
                task=None
            )
            storage.session.create(session_data)
            logger.info("Session created: %s", request.session_id)

        logger.info("Message received: session_id=%s, msg_id=%s", request.session_id, msg_id)

        # Update session's processed_msg_id if provided
        if request.processed_msg_id:
            storage.session.update_processed_msg_id(request.session_id, request.processed_msg_id)
            logger.info("Updated processed_msg_id for session %s: %s",
                       request.session_id, request.processed_msg_id)

        # Always check for more unprocessed messages after any update
        check_and_process_messages(request.session_id, storage, worker_manager)

        return success_response(data={"msg_id": msg_id}, message="Message received")

    except IntegrityError as e:
        logger.exception("Database integrity error receiving message: %s", e)
        return error_response(
            message="Database constraint violation: unable to save message. "
                    "Please check if the session exists and data is valid."
        )
    except ValueError as e:
        logger.warning("Validation error in receive_message: %s", e)
        return error_response(message=str(e))
    except Exception as e:
        logger.exception("Error receiving message: %s", e)
        return error_response(message=f"Failed to receive message: {str(e)}")


@router.get("", response_model=ApiResponse)
async def retrieve_messages(
    session_id: str,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    offset: int = 0,
    limit: int = 1000,
    sort_key: str = "create_time",
    order_by: str = "desc",
    processed_msg_id: Optional[str] = None,
    storage: Storage = Depends(get_storage)
) -> ApiResponse:
    """
    Retrieve messages for a session.

    Args:
        session_id: Session identifier
        start_time: Start time filter (ISO format string)
        end_time: End time filter (ISO format string)
        offset: Pagination offset
        limit: Maximum number of messages to return
        sort_key: Field to sort by
        order_by: Sort order (asc or desc)
        processed_msg_id: Filter messages by processed_msg_id field
    """
    try:
        # Validate session_id
        validate_session_id(session_id)
        
        # Parse datetime strings if provided
        start_dt = None
        end_dt = None

        if start_time:
            start_dt = datetime.fromisoformat(start_time)
        if end_time:
            end_dt = datetime.fromisoformat(end_time)

        # Get messages from storage
        messages = storage.message.get_messages(
            session_id=session_id,
            start_time=start_dt,
            end_time=end_dt,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            order_by=order_by,
            processed_msg_id=processed_msg_id
        )

        # Convert to response format
        message_list = []
        for msg in messages:
            message_list.append(MessageResponse(
                msg_id=msg.msg_id,
                session_id=msg.session_id,
                message=msg.message,
                role=msg.role,
                create_time=msg.create_time,
                update_time=msg.update_time,
                task_id=msg.task_id,
                task_result=msg.task_result
            ))

        # DEBUG: Log query operation at debug level
        logger.debug("Retrieved %d messages for session: %s", len(message_list), session_id)

        return success_response(data=message_list)

    except IntegrityError as e:
        logger.exception("Database integrity error retrieving messages: %s", e)
        return error_response(
            message="Database constraint violation: unable to retrieve messages. "
                    "Please check if the session exists."
        )
    except ValueError as e:
        logger.warning("Validation error in retrieve_messages: %s", e)
        return error_response(message=str(e))
    except Exception as e:
        logger.exception("Error retrieving messages: %s", e)
        return error_response(message=f"Failed to retrieve messages: {str(e)}")
