'''
  Author: mm-m25
  Created: 2026-04-15
  Purpose: Shared processor helper - message formatting and processing logic
'''

from typing import Optional, List
from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage


def format_pending_messages(unprocessed_messages: list) -> str:
    """
    Format unprocessed messages into the "待处理消息" (pending messages) format.
    
    The format is markdown with "---" separators:
    ---
    msg1内容
    ---
    msg2内容
    >>> task_id: msg2的task_id
    >>> task_result: msg2的task_result
    ---
    
    Rules:
    - Each message is wrapped between "---" separators
    - The content starts and ends with "---"
    - task_id and task_result are only included when they have values
    - Assistant messages WITHOUT task_id are EXCLUDED
    - Assistant messages WITH task_id are INCLUDED
    """
    parts = []
    
    for msg in unprocessed_messages:
        # Skip assistant messages without task_id
        if msg.role == "assistant" and not msg.task_id:
            continue
        
        msg_parts = []
        msg_parts.append(msg.message)
        
        # Include task_id if present
        if msg.task_id:
            msg_parts.append(">>> task_id: %s" % msg.task_id)
        
        # Include task_result if present
        if msg.task_result:
            msg_parts.append(">>> task_result: %s" % msg.task_result)
        
        parts.append("\n".join(msg_parts))
    
    if not parts:
        return ""
    
    return "---\n" + "\n---\n".join(parts) + "\n---"


def check_and_process_messages(
    session_id: str,
    storage: Storage,
    worker_manager
) -> Optional[dict]:
    """
    Check if there are unprocessed messages and start processor if needed.
    
    Flow per spec:
    1. If processed_msg_id is the latest message -> log and return None
    2. If all messages from processed_msg_id to latest are role=assistant -> log and return None (avoid infinite loop)
    3. Run TOPSAILAI_AGENT_DAEMON_SESSION_STATE_CHECKER -> if processing, return None
    4. Format the pending messages and start the processor
    5. Return the processing info dict
    
    Args:
        session_id: The session ID to check
        storage: Storage instance for database operations
        worker_manager: WorkerManager instance for process management
        
    Returns:
        dict with processing info, or None if no processing needed
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

        # Get unprocessed messages (includes ALL roles now)
        unprocessed = storage.message.get_unprocessed_messages(
            session_id, session.processed_msg_id
        )
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

        # Step 4: Format pending messages and start processor
        task = format_pending_messages(unprocessed)
        if not task:
            logger.info("No pending messages to process after formatting for session: %s", session_id)
            return None

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
