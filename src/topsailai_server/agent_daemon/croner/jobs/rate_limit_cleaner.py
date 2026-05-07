'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-05-04
  Purpose: Rate limit log cleaner cron job - cleans old rate limit log records hourly
'''

from datetime import datetime, timedelta
from typing import Optional

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase


class RateLimitCleaner(CronJobBase):
    """
    Rate Limit Log Cleaner - Cleans old rate limit log records hourly

    Runs every hour to:
    1. Delete rate_limit_log records older than 1 hour
    2. Keep the database clean and prevent unbounded growth
    """

    def __init__(
        self,
        interval_seconds: int = 3600,  # Run hourly (1 hour)
        storage: Optional[Storage] = None,
        worker_manager: Optional[WorkerManager] = None
    ):
        """
        Initialize the rate limit cleaner job.

        Args:
            interval_seconds: How often to run (default 3600 seconds = 1 hour)
            storage: Storage instance (optional, will create if not provided)
            worker_manager: WorkerManager instance (optional)
        """
        super().__init__(interval_seconds, storage, worker_manager)

    def run(self):
        """Execute the rate limit cleaner job"""
        try:
            logger.info("Starting rate limit cleaner job")

            # Calculate cutoff time (1 hour ago)
            cutoff_time = datetime.now() - timedelta(hours=1)

            # Clean old rate limit logs via the api_key storage
            deleted_count = self.storage.api_key.clean_rate_limit_logs(before=cutoff_time)

            # Mark job as run
            self.mark_run()

            if deleted_count > 0:
                logger.info(
                    "Rate limit cleaner job completed: deleted %d old records",
                    deleted_count
                )
            else:
                logger.info("Rate limit cleaner job completed: no old records to delete")

        except Exception as e:
            logger.exception("Error in rate limit cleaner job: %s", e)
