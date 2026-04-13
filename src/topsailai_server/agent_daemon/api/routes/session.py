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
_worker_manager = None

def get_storage() -> Storage:
    """Get storage instance."""
    global _storage
    if _storage is None:
        from topsailai_server.agent_daemon.storage import Storage
        _storage = Storage()
    return _storage

def get_worker_manager():
    """Get worker manager instance."""
    global _worker_manager
    if _worker_manager is None:
        from topsailai_server.agent_daemon.worker import WorkerManager
        _worker_manager = WorkerManager()
    return _worker_manager

def set_dependencies(session_storage, message_storage, worker_manager):
    """Set dependencies for the router."""
    global _storage, _worker_manager
    from topsailai_server.agent_daemon.storage import Storage
    _storage = Storage(session_storage.engine)
    _worker_manager = worker_manager

# Pydantic models for request/response
class SessionResponse(BaseModel):
    session_id: str
    session_name: Optional[str] = None
    task: Optional[str] = None
    create_time: Optional[datetime] = None
    update_time: Optional[datetime] = None
    processed_msg_id: Optional[str] = None


class ProcessSessionRequest(BaseModel):
    session_id: str


class ProcessSessionResponse(BaseModel):
    session_id: str
    processed: bool
    message: str
    worker_result: Optional[str] = None


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


@router.post("/process", response_model=ApiResponse)
async def process_session(
    request: ProcessSessionRequest,
    storage: Storage = Depends(get_storage),
    worker_manager = Depends(get_worker_manager)
) -> ApiResponse:
    """
    Process pending messages for a session.
    
    Checks if session.processed_msg_id is the latest message.
    If not, triggers TOPSAILAI_AGENT_DAEMON_PROCESSOR to process messages.
    
    Parameters:
    - session_id: The session ID to process
    """
    try:
        session_id = request.session_id
        
        # Get session
        session = storage.session.get(session_id)
        if not session:
            logger.warning("Session not found: %s", session_id)
            return error_response(f"Session not found: {session_id}")
        
        # Get latest message for this session
        messages = storage.message.get_messages(
            session_id=session_id,
            limit=1,
            sort_key="create_time",
            order_by="desc"
        )
        
        if not messages:
            logger.info("No messages found for session: %s", session_id)
            return success_response({
                "session_id": session_id,
                "processed": False,
                "message": "No messages in session"
            })
        
        # Get the latest message
        latest_message = messages[0]
        latest_msg_id = latest_message.msg_id
        processed_msg_id = session.processed_msg_id
        
        # Check if already at latest
        if processed_msg_id == latest_msg_id:
            logger.info("Session %s is already at latest message: %s", session_id, latest_msg_id)
            return success_response({
                "session_id": session_id,
                "processed": False,
                "message": "Session is already at the latest message"
            })
        
        # Check session state - is it currently processing?
        from topsailai_server.agent_daemon.configer import Configer
        configer = Configer()
        session_state_checker = configer.get_session_state_checker()
        
        if session_state_checker:
            import os
            env = os.environ.copy()
            env["TOPSAILAI_SESSION_ID"] = session_id
            
            import subprocess
            try:
                result = subprocess.run(
                    [session_state_checker, session_id],
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                state = result.stdout.strip().lower()
                
                if "processing" in state:
                    logger.info("Session %s is currently processing, skipping", session_id)
                    return success_response({
                        "session_id": session_id,
                        "processed": False,
                        "message": "Session is currently processing another message"
                    })
            except Exception as e:
                logger.warning("Failed to check session state: %s", e)
                # Continue anyway - don't block processing
        
        # Get unprocessed messages (after processed_msg_id)
        unprocessed_messages = storage.message.get_unprocessed_messages(
            session_id=session_id,
            processed_msg_id=processed_msg_id
        )
        
        if not unprocessed_messages:
            logger.info("No unprocessed messages for session: %s", session_id)
            return success_response({
                "session_id": session_id,
                "processed": False,
                "message": "No unprocessed messages"
            })
        
        # Combine messages into a single task
        combined_task = "\n".join([msg.message for msg in unprocessed_messages])
        msg_id = unprocessed_messages[0].msg_id
        
        logger.info("Processing session %s with %d messages, starting from msg_id: %s",
                    session_id, len(unprocessed_messages), msg_id)
        
        # Trigger the processor
        processor_script = configer.get_processor()
        
        if not processor_script:
            logger.error("No processor script configured")
            return error_response("No processor script configured")
        
        # Set environment variables
        env = os.environ.copy()
        env["TOPSAILAI_MSG_ID"] = msg_id
        env["TOPSAILAI_TASK"] = combined_task
        env["TOPSAILAI_SESSION_ID"] = session_id
        
        # Start the processor
        worker_manager.start_worker(processor_script, env)
        
        logger.info("Triggered processor for session %s", session_id)
        
        return success_response({
            "session_id": session_id,
            "processed": True,
            "message": f"Processing {len(unprocessed_messages)} message(s)",
            "worker_result": None
        })
    
    except Exception as e:
        logger.exception("Error processing session: %s", e)
        return error_response(f"Failed to process session: {str(e)}")