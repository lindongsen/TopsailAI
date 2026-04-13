'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Message consumer cron job - processes unprocessed messages periodically
'''

from datetime import datetime, timedelta
from typing import Optional

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase


class MessageConsumer(CronJobBase):
    """
    Message Consumer - Consumes unprocessed messages periodically
    
    Runs every minute to:
    1. Query messages from the last 10 minutes
    2. Get unique session IDs
    3. Check if each session has unprocessed messages
    4. If so, start the processor for that session
    """
    
    def __init__( 
        self, 
        interval_seconds: int = 60,
        storage: Optional[Storage] = None,
        worker_manager: Optional[WorkerManager] = None
    ):
        """
        Initialize the message consumer job.
        
        Args:
            interval_seconds: How often to run (default 60 seconds)
            storage: Storage instance (optional, will create if not provided)
            worker_manager: WorkerManager instance (optional, will create if not provided)
        """
        super().__init__(interval_seconds, storage, worker_manager)
        # Initialize storage and worker_manager if not provided
        if self.storage is None:
            from topsailai_server.agent_daemon.configer import get_engine
            engine = get_engine()
            self.storage = Storage(engine)
        if self.worker_manager is None:
            from topsailai_server.agent_daemon.configer import get_config
            config = get_config()
            self.worker_manager = WorkerManager(config)
    
    def run(self):
        """Execute the message consumer job"""
        try:
            logger.info("Starting message consumer job")
            
            # Get messages from last 10 minutes
            cutoff_time = datetime.now() - timedelta(minutes=10)
            recent_messages = self.storage.message.get_messages_since(cutoff_time)
            
            if not recent_messages:
                logger.info("No recent messages found")
                return
            
            # Get unique session IDs
            session_ids = set(msg.session_id for msg in recent_messages)
            logger.info("Found %d sessions with recent messages", len(session_ids))
            
            for session_id in session_ids:
                self._process_session(session_id)
            
            # Mark job as run
            self.mark_run()
            logger.info("Message consumer job completed")
        
        except Exception as e:
            logger.exception("Error in message consumer job: %s", e)
    
    def _process_session(self, session_id: str):
        """Process a single session"""
        try:
            # Get session
            session = self.storage.session.get(session_id)
            if not session:
                logger.warning("Session not found: %s", session_id)
                return
            
            # Get latest message for this session
            latest_message = self.storage.message.get_latest_message(session_id)
            if not latest_message:
                logger.warning("No messages found for session: %s", session_id)
                return
            
            # Step 1: Check if there are unprocessed messages
            if session.processed_msg_id == latest_message.msg_id:
                logger.debug("Session %s is up to date", session_id)
                return
            
            # Get unprocessed messages
            processed_msg_id = session.processed_msg_id or ""
            unprocessed_messages = self.storage.message.get_unprocessed_messages(
                session_id, processed_msg_id
            )
            
            if not unprocessed_messages:
                logger.debug("No unprocessed messages for session: %s", session_id)
                return
            
            # Step 2: Check if all unprocessed messages are from assistant (avoid infinite loop)
            if all(msg.role == "assistant" for msg in unprocessed_messages):
                logger.info("All unprocessed messages are assistant, skipping session %s to avoid infinite loop", session_id)
                return
            
            # Step 3: Check session state
            session_state = self.worker_manager.check_session_state(session_id)
            
            if session_state != "idle":
                logger.info("Session %s is currently processing, skipping", session_id)
                return
            
            # Step 4: Start processor
            # Combine messages into a single task
            combined_task = "\n".join([msg.message for msg in unprocessed_messages])
            
            # Start processor
            self.worker_manager.start_processor(
                session_id=session_id,
                msg_id=latest_message.msg_id,
                task=combined_task
            )
            logger.info("Started processor for session_id=%s, msg_id=%s, message_count=%d", 
                       session_id, latest_message.msg_id, len(unprocessed_messages))
        
        except Exception as e:
            logger.exception("Error processing session %s: %s", session_id, e)