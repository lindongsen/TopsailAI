'''
  Author: Dawsonlin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Task API routes - FastAPI implementation
'''

from typing import Optional, List
from datetime import datetime
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage, MessageData
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.validator import (
    validate_session_id,
    validate_task_id,
    validate_msg_id,
)
from topsailai_server.agent_daemon.api.utils import ApiResponse, success_response, error_response
from topsailai_server.agent_daemon.api.processor_helper import check_and_process_messages
# Import from message module - they share the same globals set by app.py
from topsailai_server.agent_daemon.api.routes.message import get_storage, get_worker_manager


# Router
router = APIRouter(prefix="/api/v1/task", tags=["task"])

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


# Request/Response Models
class SetTaskResultRequest(BaseModel):
    """Request model for setting task result"""
    session_id: str
    processed_msg_id: str
    task_id: str
    task_result: str


class RetrieveTasksRequest(BaseModel):
    """Request model for retrieving tasks"""
    task_ids: Optional[List[str]] = None
    session_id: str
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    offset: int = 0
    limit: int = 1000
    sort_key: str = "create_time"
    order_by: str = "desc"


class TaskResponse(BaseModel):
    """Response model for a task"""
    msg_id: str
    session_id: str
    message: str
    task_id: str
    task_result: str
    create_time: datetime
    update_time: datetime


@router.post("", response_model=ApiResponse)
async def set_task_result(
    request: SetTaskResultRequest,
    storage: Storage = Depends(get_storage),
    worker_manager: WorkerManager = Depends(get_worker_manager)
) -> ApiResponse:
    """
    Set task result for a processed message.

    This endpoint:
    1. Updates the message with task_id and task_result
    2. Updates the session's processed_msg_id
    3. Checks if there are more unprocessed messages
    """
    try:
        # Validate inputs
        validate_session_id(request.session_id)
        validate_msg_id(request.processed_msg_id)
        validate_task_id(request.task_id)

        # Update message with task info
        message = storage.message.update_task_info(
            msg_id=request.processed_msg_id,
            session_id=request.session_id,
            task_id=request.task_id,
            task_result=request.task_result
        )

        if not message:
            return error_response(message="Message not found", code=404)

        # Update session's processed_msg_id
        storage.session.update_processed_msg_id(request.session_id, request.processed_msg_id)

        logger.info("Task result set: session_id=%s, msg_id=%s, task_id=%s",
                   request.session_id, request.processed_msg_id, request.task_id)

        # Check if there are more messages to process
        check_and_process_messages(request.session_id, storage, worker_manager)

        return success_response(data={"task_id": request.task_id}, message="Task result saved")

    except ValueError as e:
        logger.warning("Validation error in set_task_result: %s", e)
        return error_response(message=str(e), code=400)

    except IntegrityError as e:
        logger.exception("Database integrity error in set_task_result: %s", e)
        return error_response(message="Database constraint violation. Please check your input data.", code=409)

    except Exception as e:
        logger.exception("Error setting task result: %s", e)
        return error_response(message="Failed to set task result", code=500)


@router.get("", response_model=ApiResponse)
async def retrieve_tasks(
    session_id: str,
    task_ids: Optional[str] = None,
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    offset: int = 0,
    limit: int = 1000,
    sort_key: str = "create_time",
    order_by: str = "desc",
    storage: Storage = Depends(get_storage)
) -> ApiResponse:
    """
    Retrieve tasks for a session.

    Args:
        session_id: Session identifier
        task_ids: Comma-separated list of task IDs to filter
        start_time: Start time filter (ISO format string)
        end_time: End time filter (ISO format string)
        offset: Pagination offset
        limit: Maximum number of tasks to return
        sort_key: Field to sort by
        order_by: Sort order (asc or desc)
    """
    try:
        # Validate session_id
        validate_session_id(session_id)

        # Validate task_ids if provided
        if task_ids:
            task_id_list = [tid.strip() for tid in task_ids.split(',')]
            for tid in task_id_list:
                validate_task_id(tid)
        else:
            task_id_list = None

        # Parse datetime strings if provided
        start_dt = None
        end_dt = None

        if start_time:
            start_dt = datetime.fromisoformat(start_time)
        if end_time:
            end_dt = datetime.fromisoformat(end_time)

        # Get messages with task_id from storage
        messages = storage.message.get_messages(
            session_id=session_id,
            start_time=start_dt,
            end_time=end_dt,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            order_by=order_by
        )

        # Filter by task_ids if provided
        if task_id_list:
            messages = [m for m in messages if m.task_id in task_id_list]

        # Filter to only messages with task_id
        messages_with_tasks = [m for m in messages if m.task_id is not None]

        # Convert to response format
        task_list = []
        for msg in messages_with_tasks:
            task_list.append(TaskResponse(
                msg_id=msg.msg_id,
                session_id=msg.session_id,
                message=msg.message,
                task_id=msg.task_id,
                task_result=msg.task_result,
                create_time=msg.create_time,
                update_time=msg.update_time
            ))

        return success_response(data=task_list)

    except ValueError as e:
        logger.warning("Validation error in retrieve_tasks: %s", e)
        return error_response(message=str(e), code=400)

    except IntegrityError as e:
        logger.exception("Database integrity error in retrieve_tasks: %s", e)
        return error_response(message="Database constraint violation. Please check your input data.", code=409)

    except Exception as e:
        logger.exception("Error retrieving tasks: %s", e)
        return error_response(message="Failed to retrieve tasks", code=500)
