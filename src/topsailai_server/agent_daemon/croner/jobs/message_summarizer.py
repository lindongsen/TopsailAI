'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Message summarizer cron job - summarizes messages daily
'''

import os
import subprocess
from datetime import datetime, timedelta
from typing import Optional

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase


class MessageSummarizer(CronJobBase):
    """
    Message Summarizer - Summarizes messages daily
    
    Runs daily at 1:00 AM to:
    1. Query messages from the last 24 hours
    2. Group messages by session
    3. Sort messages by create_time for each session
    4. Call the summarizer script for each session
    """
    
    def __init__(
        self, 
        interval_seconds: int = 86400,  # Run daily (24 hours)
        storage: Optional[Storage] = None,
        worker_manager: Optional[WorkerManager] = None
    ):
        """
        Initialize the message summarizer job.
        
        Args:
            interval_seconds: How often to run (default 86400 seconds = 24 hours)
            storage: Storage instance (optional, will create if not provided)
            worker_manager: WorkerManager instance (optional)
        """
        super().__init__(interval_seconds, storage, worker_manager)
        # Initialize storage if not provided
        if self.storage is None:
            from topsailai_server.agent_daemon.configer import get_engine
            engine = get_engine()
            self.storage = Storage(engine)
        # Get config
        self.config = get_config()
    
    def run(self):
        """Execute the message summarizer job"""
        try:
            logger.info("Starting message summarizer job")
            
            # Get messages from last 24 hours
            cutoff_time = datetime.now() - timedelta(days=1)
            recent_messages = self.storage.message.get_messages_since(cutoff_time)
            
            if not recent_messages:
                logger.info("No recent messages to summarize")
                return
            
            # Group messages by session_id
            sessions_messages = {}
            for msg in recent_messages:
                if msg.session_id not in sessions_messages:
                    sessions_messages[msg.session_id] = []
                sessions_messages[msg.session_id].append(msg)
            
            # Sort messages by create_time for each session
            for session_id in sessions_messages:
                sessions_messages[session_id].sort(key=lambda m: m.create_time)
            
            logger.info("Found %d sessions to summarize", len(sessions_messages))
            
            # Call summarizer for each session
            for session_id, messages in sessions_messages.items():
                self._summarize_session(session_id, messages)
            
            # Mark job as run
            self.mark_run()
            logger.info("Message summarizer job completed")
        
        except Exception as e:
            logger.exception("Error in message summarizer job: %s", e)
    
    def _summarize_session(self, session_id: str, messages):
        """Summarize messages for a single session"""
        try:
            # Combine messages in order
            combined_task = "\n".join([
                f"[{msg.create_time.strftime('%Y-%m-%d %H:%M:%S')}] {msg.role}: {msg.message}"
                for msg in messages
            ])
            
            # Set environment variables
            env = os.environ.copy()
            env['TOPSAILAI_SESSION_ID'] = session_id
            env['TOPSAILAI_TASK'] = combined_task
            
            # Call summarizer script
            logger.info("Calling summarizer for session_id=%s, message_count=%d", 
                       session_id, len(messages))
            
            result = subprocess.run(
                [self.config.summarizer_script],
                env=env,
                capture_output=True,
                text=True,
                timeout=300  # 5 minutes timeout
            )
            
            if result.returncode == 0:
                logger.info("Summarizer completed for session_id=%s", session_id)
            else:
                logger.warning("Summarizer failed for session_id=%s: %s", 
                              session_id, result.stderr)
        
        except subprocess.TimeoutExpired:
            logger.error("Summarizer timed out for session_id=%s", session_id)
        except Exception as e:
            logger.exception("Error summarizing session %s: %s", session_id, e)
