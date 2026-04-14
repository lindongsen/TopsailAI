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


def get_message_storage():
    """Get Message Storage instance (MessageSQLAlchemy)"""
    if _message_storage is None:
        raise RuntimeError("Message Storage not initialized")
    return _message_storage  # Return MessageSQLAlchemy instance directly


def _are_all_messages_assistant(
    session_id: str, 
    processed_msg_id: Optional[str], 
    latest_msg_id: str
) -> bool:
    """
    Check if all messages between processed_msg_id and latest_msg_id are assistant.
    
    Returns:
        True if all messages are assistant (or no messages exist)
        False if any user message exists
    """
    # New session - assume has work to do
    if not processed_msg_id:
        return False
    
    try:
        message_storage = get_message_storage()
        
        # Get the create_time of processed_msg_id
        processed_msg = message_storage.get(processed_msg_id, session_id)
        if not processed_msg:
            # If processed_msg_id doesn't exist, treat as new session
            return False
        
        # Get all messages for this session after processed_msg_id using storage method
        all_messages = message_storage.get_messages(
            session_id=session_id,
            sort_key="create_time",
            order_by="asc"
        )
        
        # Filter messages after processed_msg_id
        found_processed = False
        pending_messages = []
        for msg in all_messages:
            if msg.msg_id == processed_msg_id:
                found_processed = True
                continue
            if found_processed:
                pending_messages.append(msg)
        
        if not pending_messages:
            return True  # No messages = all (zero) are assistant
        
        # Check if ALL are assistant
        return all(msg.role == "assistant" for msg in pending_messages)
    except Exception as e:
        logger.exception("Failed to check messages: %s", e)
        # On error, assume there are messages to process
        return False


# Request/Response models
class ProcessSessionRequest(BaseModel):
    session_id: str


class DeleteSessionsRequest(BaseModel):
    session_ids: list[str]


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
        
        # Parse time strings to datetime objects
        start_dt = datetime.fromisoformat(start_time) if start_time else None
        end_dt = datetime.fromisoformat(end_time) if end_time else None
        
        sessions = storage.session.list_sessions(
            start_time=start_dt,
            end_time=end_dt,
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
    Process a session:
    Step 1: If processed_msg_id is the latest message, exit
    Step 2: If all messages between processed_msg_id and latest are assistant, log and exit (avoid infinite loop)
    Step 3: Execute TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER script - if idle, continue; if processing, exit
    Step 4: Set latest message ID as TOPSAILAI_MSG_ID, execute processor script
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
        messages = message_storage.get_messages(
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
        
        # Step 1: If processed_msg_id is the latest message, exit
        if session.processed_msg_id == latest_msg_id:
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "already_processed"},
                "message": "Session is already up to date"
            }
        
        # Step 2: If all messages between processed_msg_id and latest are assistant, exit (avoid infinite loop)
        all_assistant = _are_all_messages_assistant(session_id, session.processed_msg_id, latest_msg_id)
        if all_assistant:
            logger.info("All messages are assistant, skipping session %s to avoid infinite loop", session_id)
            return {
                "code": 0,
                "data": {"session_id": session_id, "status": "skipped", "reason": "all_assistant"},
                "message": "All messages are assistant, skipping to avoid infinite loop"
            }
        
        # Step 3: Check session state using TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER
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
        
        worker_mgr = _worker_manager
        
        # Check if session is idle
        is_idle = worker_mgr.is_session_idle(session_id)
        
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
        
        # Step 4: Trigger processor with LATEST message ID (not pending)
        processor_script = config.processor_script
        if not processor_script:
            return {
                "code": 1,
                "data": None,
                "message": "TOPSAILAI_AGENT_DAEMON_PROCESSOR not configured"
            }
        
        # Set environment variables for processor - use latest_msg_id
        worker_mgr.start_processor(session_id, latest_msg_id, task_content)
        
        return {
            "code": 0,
            "data": {
                "session_id": session_id,
                "status": "processing",
                "msg_id": latest_msg_id
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


@router.post("/delete")
async def delete_sessions(request: DeleteSessionsRequest):
    """
    Delete sessions and their associated messages.
    
    Parameters:
        session_ids: list of session IDs to delete
    
    Returns:
        deleted_sessions: count of deleted sessions
        deleted_messages: count of deleted messages
        session_ids: list of deleted session IDs
    """
    try:
        session_ids = request.session_ids
        
        if not session_ids:
            return {
                "code": 1,
                "data": None,
                "message": "session_ids is required and cannot be empty"
            }
        
        # Get storage instances
        storage = get_storage()
        message_storage = get_message_storage()
        
        deleted_sessions = 0
        deleted_messages = 0
        
        for session_id in session_ids:
            # Delete messages first (foreign key relationship)
            try:
                count = message_storage.delete_messages_by_session(session_id)
                deleted_messages += count
            except Exception as e:
                logger.warning("Failed to delete messages for session %s: %s", session_id, e)
            
            # Delete session
            try:
                storage.session.delete(session_id)
                deleted_sessions += 1
            except Exception as e:
                logger.warning("Failed to delete session %s: %s", session_id, e)
        
        return {
            "code": 0,
            "data": {
                "deleted_sessions": deleted_sessions,
                "deleted_messages": deleted_messages,
                "session_ids": session_ids
            },
            "message": "Success"
        }
        
    except Exception as e:
        logger.exception("Failed to delete sessions: %s", e)
        return {
            "code": 1,
            "data": None,
            "message": str(e)
        }
