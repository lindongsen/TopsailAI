"""
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Croner scheduler - manages periodic tasks
"""

import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Callable, Optional

from topsailai_server.agent_daemon import logger


class CronJob:
    """Represents a cron job"""

    def __init__(self, name: str, func: Callable, interval_seconds: int, run_at_start: bool = False):
        self.name = name
        self.func = func
        self.interval_seconds = interval_seconds
        self.run_at_start = run_at_start
        self.last_run: Optional[datetime] = None
        self._stop_event = threading.Event()

    def should_run(self) -> bool:
        """Check if the job should run"""
        if self.last_run is None:
            return True
        elapsed = (datetime.now() - self.last_run).total_seconds()
        return elapsed >= self.interval_seconds

    def execute(self):
        """Execute the job"""
        try:
            logger.info("Executing cron job: %s", self.name)
            self.func()
            self.last_run = datetime.now()
            logger.info("Cron job completed: %s", self.name)
        except Exception as e:
            logger.exception("Error executing cron job %s: %s", self.name, e)

    def stop(self):
        """Stop the job"""
        self._stop_event.set()


class CronScheduler:
    """Scheduler for periodic tasks"""

    def __init__(self):
        self.jobs: Dict[str, CronJob] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def add_job(self, name: str, func: Callable, interval_seconds: int, run_at_start: bool = False):
        """Add a cron job"""
        job = CronJob(name, func, interval_seconds, run_at_start)
        self.jobs[name] = job
        logger.info("Added cron job: %s with interval %d seconds", name, interval_seconds)

    def remove_job(self, name: str):
        """Remove a cron job"""
        if name in self.jobs:
            self.jobs[name].stop()
            del self.jobs[name]
            logger.info("Removed cron job: %s", name)

    def start(self):
        """Start the scheduler"""
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()
        logger.info("Cron scheduler started with %d jobs", len(self.jobs))

    def stop(self):
        """Stop the scheduler"""
        if not self._running:
            return

        self._running = False
        for job in self.jobs.values():
            job.stop()

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Cron scheduler stopped")

    def _run_loop(self):
        """Main scheduler loop"""
        while self._running:
            try:
                for job in self.jobs.values():
                    if job.should_run():
                        # Run job in a separate thread to not block the scheduler
                        thread = threading.Thread(target=job.execute, daemon=True)
                        thread.start()

                # Sleep for a bit before checking again
                time.sleep(1)
            except Exception as e:
                logger.exception("Error in scheduler loop: %s", e)
                time.sleep(1)


def create_scheduler(session_storage, message_storage, worker_manager, config) -> CronScheduler:
    """Create and configure the cron scheduler"""
    from topsailai_server.agent_daemon.storage import Storage
    
    scheduler = CronScheduler()
    
    # Create Storage instance from session and message storage
    storage = Storage(session_storage.get_engine())
    
    # Message Consumer - every minute (60 seconds)
    from topsailai_server.agent_daemon.croner.jobs import MessageConsumer
    consumer_job = MessageConsumer(
        interval_seconds=60,
        storage=storage,
        worker_manager=worker_manager
    )
    scheduler.add_job("message_consumer", consumer_job.run, interval_seconds=60, run_at_start=True)

    # Message Summarizer - daily at 1:00 AM (86400 seconds)
    from topsailai_server.agent_daemon.croner.jobs import MessageSummarizer
    summarizer_job = MessageSummarizer(
        interval_seconds=86400,
        storage=storage,
        worker_manager=worker_manager
    )
    scheduler.add_job("message_summarizer", summarizer_job.run, interval_seconds=86400, run_at_start=False)

    # Session Cleaner - monthly (30 days = 2592000 seconds)
    from topsailai_server.agent_daemon.croner.jobs import SessionCleaner
    cleaner_job = SessionCleaner(
        interval_seconds=2592000,
        storage=storage,
        worker_manager=worker_manager
    )

    def monthly_cleaner():
        """Wrapper to run cleaner only on 1st of month"""
        if datetime.now().day == 1 and datetime.now().hour == 1:
            cleaner_job.run()

    scheduler.add_job("session_cleaner", monthly_cleaner, interval_seconds=86400, run_at_start=False)

    return scheduler
