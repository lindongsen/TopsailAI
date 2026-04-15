'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-12
  Purpose: Message summarizer cron job - summarizes messages daily
'''

import time
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import create_engine

from topsailai_server.agent_daemon import logger
from topsailai_server.agent_daemon.configer import get_config
from topsailai_server.agent_daemon.storage import Storage
from topsailai_server.agent_daemon.worker import WorkerManager
from topsailai_server.agent_daemon.croner.jobs.__base import CronJobBase
from topsailai_server.agent_daemon.croner.jobs.utils import (
    CircuitBreaker,
    CircuitBreakerOpenError,
    retry_with_backoff,
)

# Circuit breaker for summarizer failures
SUMMARIZER_CIRCUIT_BREAKER = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60,
)


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
            config = get_config()
            engine = create_engine(config.db_url)
            self.storage = Storage(engine)
        # Initialize worker_manager if not provided
        if self.worker_manager is None:
            config = get_config()
            self.worker_manager = WorkerManager(config)

    def run(self):
        """Execute the message summarizer job"""
        start_time = time.time()
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

            # Log execution duration
            duration_ms = (time.time() - start_time) * 1000
            logger.info("Message summarizer job completed in %.2f ms", duration_ms)

            # Warn if execution is slow
            if duration_ms > 30000:
                logger.warning("Message summarizer job took %.2f ms (>30s threshold)", duration_ms)

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

            # Call summarizer using WorkerManager with retry and circuit breaker
            logger.info("Calling summarizer for session_id=%s, message_count=%d",
                       session_id, len(messages))

            result = self._run_summarizer_with_resilience(session_id, combined_task)

            if result is not None:
                logger.info("Summarizer started for session_id=%s", session_id)
            else:
                logger.warning("Failed to start summarizer for session_id=%s", session_id)

        except Exception as e:
            logger.exception("Error summarizing session %s: %s", session_id, e)

    def _run_summarizer_with_resilience(self, session_id: str, task: str):
        """
        Run summarizer with retry and circuit breaker protection.

        Args:
            session_id: The session ID
            task: The combined task content

        Returns:
            Result from summarizer or None if all retries failed
        """
        def _execute_summarizer():
            return self.worker_manager.start_summarizer(
                session_id=session_id,
                task=task
            )

        try:
            # Use circuit breaker to wrap the retry_with_backoff execution
            def _wrapped_execution():
                return retry_with_backoff(
                    _execute_summarizer,
                    max_retries=3,
                    base_delay=1.0,
                    retryable_exceptions=(Exception,),
                )

            result = SUMMARIZER_CIRCUIT_BREAKER.call(_wrapped_execution)
            return result
        except CircuitBreakerOpenError:
            logger.warning(
                "Circuit breaker is open for summarizer, skipping session_id=%s",
                session_id
            )
            return None
        except Exception as e:
            logger.warning(
                "Summarizer failed for session_id=%s after retries: %s",
                session_id, e
            )
            return None
