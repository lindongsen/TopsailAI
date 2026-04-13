'''
  Author: DawsonLin
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


class ProcessSessionRequest(BaseModel):
    """Request model for ProcessSession endpoint"""
    session_id: str


@router.get("")
async def list_sessions(
    start_time: Optional[str] = Query(None, description="Filter by create_time >= start_time (ISO format)"),
    end_time: Optional[str] = Query(None, description="Filter by create_time <= end_time (ISO format)"),
    offset: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(1000, ge=1, le=10000, description="Maximum number of records to return"),
    sort_key: str = Query("create_time", description="Field to sort by"),
    order_by: str = Query("desc", description="Sort order: asc or desc")
) -> dict:
    """
    List sessions with filtering, sorting, and pagination.
    
    Args:
        start_time: Filter sessions created after this time (ISO format)
        end_time: Filter sessions created before this time (ISO format)
        offset: Number of records to skip
        limit: Maximum number of records to return
        sort_key: Field to sort by (default: create_time)
        order_by: Sort order (asc or desc, default: desc)
    
    Returns:
        Unified response format with list of sessions
    """
    logger.info("ListSessions request: start_time=%s, end_time=%s, offset=%d, limit=%d, sort_key=%s, order_by=%s",
                start_time, end_time, offset, limit, sort_key, order_by)
    
    try:
        storage = get_storage()
        
        # Parse time filters
        start_dt = None
        end_dt = None
        
        if start_time:
            try:
                start_dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            except ValueError:
                return {"code": 1, "data": None, "message": "Invalid start_time format. Use ISO format."}
        
        if end_time:
            try:
                end_dt = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
            except ValueError:
                return {"code": 1, "data": None, "message": "Invalid end_time format. Use ISO format."}
        
        # Get sessions from storage
        sessions = storage.list_sessions(
            start_time=start_dt,
            end_time=end_dt,
            offset=offset,
            limit=limit,
            sort_key=sort_key,
            order_by=order_by
        )
        
        # Convert to dict format
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
        
        logger.info("ListSessions response: count=%d", len(session_list))
        return {"code": 0, "data": session_list, "message": "success"}
        
    except Exception as e:
        logger.exception("ListSessions error: %s", e)
        return {"code": 1, "data": None, "message": str(e)}


@router.post("/process")
async def process_session(request: ProcessSessionRequest) -> dict:
    """
    Process a session - check if there are unprocessed messages and trigger processor.
    
    Args:
        session_id: The session ID to process
    
    Returns:
        Unified response format with processing result
    """
    logger.info("ProcessSession request: session_id=%s", request.session_id)
    
    try:
        storage = get_storage()
        worker_manager = get_worker_manager()
        
        # Get session
        session = storage.get_session(request.session_id)
        if not session:
            return {"code": 1, "data": None, "message": f"Session not found: {request.session_id}"}
        
        # Get all messages for this session
        messages = storage.list_messages(
            session_id=request.session_id,
            sort_key="create_time",
            order_by="asc"
        )
        
        if not messages:
            return {"code": 0, "data": {"processed": False, "reason": "no_messages"}, "message": "No messages to process"}
        
        # Get latest message
        latest_message = messages[-1]
        
        # Check if processed_msg_id is the latest
        if session.processed_msg_id == latest_message.msg_id:
            logger.info("Session %s already processed up to message %s", request.session_id, session.processed_msg_id)
            return {"code": 0, "data": {"processed": False, "reason": "already_processed"}, "message": "Session is up to date"}
        
        # Find unprocessed messages (after processed_msg_id)
        unprocessed_messages = []
        found_processed = session.processed_msg_id is None
        
        for msg in messages:
            if not found_processed:
                unprocessed_messages.append(msg)
            if msg.msg_id == session.processed_msg_id:
                found_processed = True
        
        if not unprocessed_messages:
            return {"code": 0, "data": {"processed": False, "reason": "no_unprocessed"}, "message": "No unprocessed messages"}
        
        # Combine unprocessed messages into a single task
        combined_task = "\n".join([
            f"[{msg.create_time.isoformat()}] {msg.message}"
            for msg in unprocessed_messages
        ])
        
        # Include task_id and task_result if present in the last message
        last_msg = unprocessed_messages[-1]
        if last_msg.task_id:
            combined_task += f"\n\nTask ID: {last_msg.task_id}"
        if last_msg.task_result:
            combined_task += f"\nTask Result: {last_msg.task_result}"
        
        # Get processor script from environment
        import os
        processor_script = os.environ.get("TOPSAILAI_AGENT_DAEMON_PROCESSOR")
        if not processor_script:
            return {"code": 1, "data": None, "message": "TOPSAILAI_AGENT_DAEMON_PROCESSOR not configured"}
        
        # Get session state checker
        session_state_checker = os.environ.get("TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER")
        
        # Check session state if checker is available
        if session_state_checker:
            try:
                import subprocess
                result = subprocess.run(
                    [session_state_checker, request.session_id],
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                state = result.stdout.strip().lower()
                if "processing" in state:
                    logger.info("Session %s is currently processing", request.session_id)
                    return {"code": 0, "data": {"processed": False, "reason": "session_processing"}, "message": "Session is being processed"}
            except Exception as e:
                logger.warning("Failed to check session state: %s", e)
        
        # Trigger processor
        env = {
            "TOPSAILAI_MSG_ID": last_msg.msg_id,
            "TOPSAILAI_SESSION_ID": request.session_id,
            "TOPSAILAI_TASK": combined_task
        }
        
        try:
            worker_manager.start_processor(processor_script, env)
            logger.info("Started processor for session %s, message %s", request.session_id, last_msg.msg_id)
            return {"code": 0, "data": {"processed": True, "msg_id": last_msg.msg_id}, "message": "Processor started"}
        except Exception as e:
            logger.exception("Failed to start processor: %s", e)
            return {"code": 1, "data": None, "message": f"Failed to start processor: {e}"}
        
    except Exception as e:
        logger.exception("ProcessSession error: %s", e)
        return {"code": 1, "data": None, "message": str(e)}