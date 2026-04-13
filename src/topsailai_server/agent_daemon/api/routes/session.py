'''
Author: Dawsonlin
Email: lin_dongsen@126.com
Created: 2026-04-12
Purpose: Session API routes for agent_daemon
'''

from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Query, HTTPException
from pydantic import BaseModel

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker.process_manager import WorkerManager

# Create router
router = APIRouter(prefix="/api/v1/session", tags=["session"])

# Global dependencies (set by app.py)
_session_storage = None
_message_storage = None
_worker_manager = None


def set_dependencies(session_storage, message_storage, worker_manager):
    """Set global dependencies for route handlers (called by app.py)"""
    global _session_storage, _message_storage, _worker_manager
    _session_storage = session_storage
    _message_storage = message_storage
    _worker_manager = worker_manager


def get_storage() -> Storage:
    """Get Storage instance"""
    if _session_storage is None:
        raise RuntimeError("Storage not initialized")
    return Storage(_session_storage.engine)


def get_message_storage() -> Storage:
    """Get Message Storage instance"""
    if _message_storage is None:
        raise RuntimeError("Message Storage not initialized")
    return Storage(_message_storage.engine)


# Request/Response models
class ProcessSessionRequest(BaseModel):
    session_id: str


class SessionResponse(BaseModel):
    session_id: str
    session_name: Optional[str] = None
    task: Optional[str] = None
    create_time: Optional[str] = None
    update_time: Optional[str] = None
    processed_msg_id: Optional[str] = None


@router.get("")
async def list_sessions(
    start_time: Optional[str] = Query(None, description="Filter by start time (ISO format)"),
    end_time: Optional[str] = Query(None, description="Filter by end time (ISO format)"),
    offset: int = Query(0, ge=0, description="Offset for pagination"),
    limit: int = Query(1000, ge=1, le=1000, description="Limit for pagination"),
    sort_key: str = Query("create_time", description="Sort key field"),
    order_by: str = Query("desc", description="Order direction: asc or desc")
):
    """
    List all sessions with optional filtering and pagination.
    """
    try:
        storage = get_storage()
        sessions = storage.session.list_sessions(
            start_time=start_time,
            end_time=end_time,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            order_by=order_by
        )
        
        # Format sessions for response
        session_list = []
        for session in sessions:
            session_list.append({
                "session_id": session.session_id,
                "session_name": session.session_name,
                "task": session.task,
                "create_time": session.create_time.strftime("%Y-%m-%d %H:%M:%S") if session.create_time else None,
                "update_time": session.update_time.strftime("%Y-%m-%d %H:%M:%S") if session.update_time else None,
                "processed_msg_id": session.processed_msg_id
            })
        
        return {
            "code": 0,
            "data": session_list,
            "message": "Success"
        }
    except Exception as e:
        logger.exception("Failed to list sessions: %s", e)
        return {
            "code": 1,
            "data": None,
            "message": str(e)
        }


@router.post("/process")
async def process_session(request: ProcessSessionRequest):
    """
    Process a session: check if processed_msg_id is the latest message.
    If not, trigger the processor to handle pending messages.
    """
    try:
        session_id = request.session_id
        
        # Get storage instances
        storage = get_storage()
        message_storage = get_message_storage()
        
        # Get session from storage
        session = storage.session.get(session_id)
        if not session:
            return {
                "code": 1,
                "data": None,
                "message": f"Session {session_id} not found"
            }
        
        # Get all messages for this session, sorted by create_time
        messages = message_storage.message.get_messages(
            session_id=session_id,
            sort_key="create_time",
            order_by="asc"
        )
        
        if not messages:
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "no_messages"},
                "message": "No messages in session"
            }
        
        # Get the latest message
        latest_message = messages[-1]
        latest_msg_id = latest_message.msg_id
        
        # Check if processed_msg_id is the latest
        if session.processed_msg_id == latest_msg_id:
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "already_processed"},
                "message": "Session is already up to date"
            }
        
        # Check if there's a message currently being processed
        from topsailai_server.agent_daemon.configer import get_config
        config = get_config()
        
        # Get session state checker script
        session_state_checker_script = config.session_state_checker_script
        if not session_state_checker_script:
            return {
                "code": 1,
                "data": None,
                "message": "TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER not configured"
            }
        
        # Check session state
        import os
        env = os.environ.copy()
        env["TOPSAILAI_SESSION_ID"] = session_id
        
        worker_mgr = _worker_manager
        
        # Check if session is idle
        is_idle = worker_mgr.check_session_state(session_id)
        
        if not is_idle:
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "processing"},
                "message": "Session is currently being processed"
            }
        
        # Get messages after processed_msg_id
        pending_messages = []
        found_processed = False
        for msg in messages:
            if session.processed_msg_id and msg.msg_id == session.processed_msg_id:
                found_processed = True
                continue
            if found_processed:
                pending_messages.append(msg)
        
        if not pending_messages:
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "no_pending"},
                "message": "No pending messages to process"
            }
        
        # Build the task content from pending messages
        task_content = ""
        for msg in pending_messages:
            role = msg.role if hasattr(msg, 'role') else 'user'
            task_content += f"[{role}]: {msg.message}\n"
            # Include task_id and task_result if present
            if msg.task_id:
                task_content += f"[task_id]: {msg.task_id}\n"
            if msg.task_result:
                task_content += f"[task_result]: {msg.task_result}\n"
        
        # Get the latest pending message's msg_id
        latest_pending_msg = pending_messages[-1]
        
        # Trigger processor
        processor_script = config.processor_script
        if not processor_script:
            return {
                "code": 1,
                "data": None,
                "message": "TOPSAILAI_AGENT_DAEMON_PROCESSOR not configured"
            }
        
        # Set environment variables for processor
        env["TOPSAILAI_MSG_ID"] = latest_pending_msg.msg_id
        env["TOPSAILAI_TASK"] = task_content
        worker_mgr.start_processor(session_id, latest_pending_msg.msg_id, task_content)
        
        # Start the processor

        
        return {
            "code": 0,
            "data": {
                "session_id": session_id,
                "status": "processing",
                "msg_id": latest_pending_msg.msg_id
            },
            "message": "Processor started"
        }
        
    except Exception as e:
        logger.exception("Failed to process session: %s", e)
        return {
            "code": 1,
            "data": None,
            "message": str(e)
        }