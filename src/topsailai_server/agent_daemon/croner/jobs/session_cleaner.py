'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Session cleaner cron job - cleans old sessions monthly
'''

from datetime import datetime, timedelta
from typing import Optional

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase


class SessionCleaner(CronJobBase):
    """
    Session Cleaner - Cleans old sessions monthly
    
    Runs monthly on the 1st at 1:00 AM to:
    1. Query sessions with update_time older than 1 year
    2. Delete related messages first (foreign key constraint)
    3. Delete the sessions
    """
    
    def __init__(
        self, 
        interval_seconds: int = 2592000,  # Run monthly (~30 days)
        storage: Optional[Storage] = None,
        worker_manager: Optional[WorkerManager] = None
    ):
        """
        Initialize the session cleaner job.
        
        Args:
            interval_seconds: How often to run (default 2592000 seconds ≈ 30 days)
            storage: Storage instance (optional, will create if not provided)
            worker_manager: WorkerManager instance (optional)
        """
        super().__init__(interval_seconds, storage, worker_manager)
        # Initialize storage if not provided
        if self.storage is None:
            from topsailai_server.agent_daemon.configer import get_engine
            engine = get_engine()
            self.storage = Storage(engine)
    
    def run(self):
        """Execute the session cleaner job"""
        try:
            logger.info("Starting session cleaner job")
            
            # Calculate cutoff date (1 year ago)
            cutoff_date = datetime.now() - timedelta(days=365)
            
            # Get old sessions
            old_sessions = self.storage.session.get_sessions_older_than(cutoff_date)
            
            if not old_sessions:
                logger.info("No old sessions to clean")
                return
            
            logger.info("Found %d sessions older than %s", len(old_sessions), cutoff_date.isoformat())
            
            # Delete sessions and their messages
            deleted_count = 0
            for session in old_sessions:
                try:
                    session_id = session.session_id
                    
                    # Delete messages first
                    self.storage.message.delete_messages_by_session(session_id)
                    
                    # Delete session
                    self.storage.session.delete(session_id)
                    
                    deleted_count += 1
                    logger.info("Deleted session: %s", session_id)
                
                except Exception as e:
                    logger.exception("Error deleting session %s: %s", session.session_id, e)
            
            # Mark job as run
            self.mark_run()
            logger.info("Session cleaner job completed: deleted %d/%d sessions", 
                       deleted_count, len(old_sessions))
        
        except Exception as e:
            logger.exception("Error in session cleaner job: %s", e)
